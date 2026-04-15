"""vanjaro migrate assemble-page — merge per-section JSON files into a page content JSON."""

from __future__ import annotations

import glob
import json
import re
import uuid
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, read_json_file
from vanjaro_cli.migration.overrides import crawl_content_to_overrides
from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides,
    check_overflow,
    find_template,
)

__all__ = ["assemble_page"]

# The globalblockwrapper component type is registered in Vanjaro's core
# GrapesJS schema. Its ``data-block-guid`` is a fixed identifier for the
# wrapper TYPE itself — the ``data-guid`` attribute points at the specific
# global block instance the wrapper references.
GLOBAL_BLOCK_WRAPPER_TYPE_GUID = "7a4be0f2-56ab-410a-9422-6bc91b488150"


def _natural_sort_key(value: str) -> list:
    """Natural sort key so `section-2-*.json` sorts before `section-10-*.json`."""
    return [
        int(token) if token.isdigit() else token.lower()
        for token in re.split(r"(\d+)", value)
    ]


def _expand_sections(patterns: tuple[str, ...], as_json: bool) -> list[Path]:
    """Expand section path patterns into a de-duplicated, ordered list of files.

    Glob patterns are expanded per-input and each expansion is sorted by
    natural key (so `section-2` sorts before `section-10`). Non-glob paths
    that don't exist produce an error. Patterns that match nothing also
    produce an error.
    """
    resolved: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        is_glob = any(ch in pattern for ch in "*?[")
        if is_glob:
            matches = sorted(glob.glob(pattern), key=_natural_sort_key)
            if not matches:
                exit_error(f"No files matched pattern: {pattern}", as_json)
        else:
            if not Path(pattern).exists():
                exit_error(f"Section file not found: {pattern}", as_json)
            matches = [pattern]

        for match in matches:
            key = str(Path(match).resolve())
            if key in seen:
                continue
            seen.add(key)
            resolved.append(Path(match))
    return resolved


def _read_section_file(path: Path, as_json: bool) -> dict:
    """Read a section JSON file, requiring a top-level object."""
    data = read_json_file(path, "Section file", as_json)
    if not isinstance(data, dict):
        exit_error(f"Section file {path} must contain a JSON object.", as_json)
    return data


# Override extraction used to live here; moved to
# ``vanjaro_cli.migration.overrides.crawl_content_to_overrides`` so
# ``migrate compose-global`` can reuse the same mapping for header and
# footer JSONs without duplicating the logic.


def _compose_template_section(
    template_name: str,
    overrides: dict[str, str],
    source_file: Path,
    as_json: bool,
) -> tuple[dict, list]:
    """Compose a template by name and return (section_component, styles)."""
    try:
        template_data = find_template(template_name)
    except TemplateNotFoundError as exc:
        exit_error(
            f"Template '{template_name}' referenced in {source_file} not found: {exc}",
            as_json,
        )

    try:
        composed = apply_overrides(template_data, overrides)
    except (KeyError, ValueError) as exc:
        exit_error(f"Failed to compose template for {source_file}: {exc}", as_json)

    overflow_keys = check_overflow(template_data, overrides)
    if overflow_keys:
        click.echo(
            f"Warning: {source_file.name}: {len(overflow_keys)} override(s) "
            f"exceed template '{template_name}' capacity and were dropped: "
            f"{', '.join(overflow_keys)}",
            err=True,
        )

    section = composed.get("template")
    if not isinstance(section, dict):
        exit_error(
            f"Template '{template_name}' (referenced by {source_file}) is missing a 'template' block.",
            as_json,
        )

    styles = composed.get("styles") or []
    if not isinstance(styles, list):
        styles = []
    return section, styles


def _classify_and_resolve(
    section_data: dict,
    source_file: Path,
    as_json: bool,
) -> tuple[dict, list]:
    """Return (section_component, styles) for a single section file."""
    if "components" in section_data and "template" not in section_data:
        styles = section_data.get("styles") or []
        if not isinstance(styles, list):
            styles = []
        return section_data, styles

    if "template" in section_data:
        template_name = section_data.get("template")
        if not isinstance(template_name, str) or not template_name:
            exit_error(
                f"Section file {source_file} has a 'template' key that is not a non-empty string.",
                as_json,
            )

        raw_overrides = section_data.get("overrides")
        if raw_overrides is None and "content" in section_data:
            content_block = section_data.get("content")
            if not isinstance(content_block, dict):
                exit_error(
                    f"Section file {source_file} has a 'content' key that is not an object.",
                    as_json,
                )
            overrides = crawl_content_to_overrides(content_block)
        elif raw_overrides is None:
            overrides = {}
        elif isinstance(raw_overrides, dict):
            overrides = {str(k): str(v) for k, v in raw_overrides.items()}
        else:
            exit_error(
                f"Section file {source_file} has an 'overrides' key that is not an object.",
                as_json,
            )

        return _compose_template_section(template_name, overrides, source_file, as_json)

    exit_error(
        f"Section file {source_file} must have either a 'template' key or a 'components' array.",
        as_json,
    )


def _validate_section_component(section: dict, source_file: Path, as_json: bool) -> None:
    """Ensure a composed section looks like a real section component."""
    if not isinstance(section, dict):
        exit_error(f"Composed section from {source_file} is not a JSON object.", as_json)

    if section.get("type") == "section":
        return

    attributes = section.get("attributes")
    if isinstance(attributes, dict) and attributes.get("id"):
        return

    exit_error(
        f"Composed section from {source_file} is not a valid section "
        "(expected type='section' or an attributes.id).",
        as_json,
    )


def _merge_styles(existing: list, additions: list) -> list:
    """Append style entries from `additions` to `existing`, de-duping hashable ones."""
    serialized_seen: set[str] = set()
    for item in existing:
        try:
            serialized_seen.add(json.dumps(item, sort_keys=True))
        except (TypeError, ValueError):
            continue

    for item in additions:
        try:
            key = json.dumps(item, sort_keys=True)
        except (TypeError, ValueError):
            existing.append(item)
            continue
        if key in serialized_seen:
            continue
        serialized_seen.add(key)
        existing.append(item)
    return existing


def _make_global_block_wrapper(name: str, block_guid: str) -> dict:
    """Build a ``globalblockwrapper`` component referencing a global block.

    Vanjaro renders these as empty divs at save time and expands them
    server-side by looking up the ``data-guid``, so the wrapper's nested
    ``components`` array is intentionally empty.
    """
    return {
        "type": "globalblockwrapper",
        "name": name,
        "content": "",
        "attributes": {
            "data-block-type": "global",
            "data-block-guid": GLOBAL_BLOCK_WRAPPER_TYPE_GUID,
            "data-guid": block_guid,
            "id": uuid.uuid4().hex[:5],
        },
        "components": [],
    }


@click.command("assemble-page")
@click.option(
    "--sections",
    "section_patterns",
    multiple=True,
    required=True,
    help="Section JSON file or glob pattern (repeatable).",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    required=True,
    help="Destination path for the assembled content JSON.",
)
@click.option(
    "--header-block-guid",
    default=None,
    help="Global block GUID to wrap the page with as a top-level header. "
    "Get the value from `vanjaro global-blocks list --json`.",
)
@click.option(
    "--footer-block-guid",
    default=None,
    help="Global block GUID to wrap the page with as a top-level footer.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def assemble_page(
    section_patterns: tuple[str, ...],
    output_file: str,
    header_block_guid: str | None,
    footer_block_guid: str | None,
    as_json: bool,
) -> None:
    """Merge per-section JSON files into a single page content JSON.

    Each --sections value may be a path or a glob pattern (expanded on Windows
    and Unix alike). Two section file formats are supported:

    \b
      1. Raw component tree with top-level "components".
      2. Template reference: {"template": "Name", "overrides": {...}}
         or the crawler shape: {"template": "Name", "content": {...}}.

    When ``--header-block-guid`` and/or ``--footer-block-guid`` are provided,
    the merged components are wrapped with ``globalblockwrapper`` entries
    referencing those global block instances. Vanjaro's renderer requires
    these wrappers to emit the site chrome around page content.

    \b
    Example:
      vanjaro migrate assemble-page \\
        --sections "pages/home/section-*.json" \\
        --output home-content.json \\
        --header-block-guid 20020077-89f8-468f-a488-017421ce5a0b \\
        --footer-block-guid fe37ff48-2c99-4201-85fc-913cac94914d
    """
    if not section_patterns:
        exit_error("At least one --sections value is required.", as_json)

    section_files = _expand_sections(section_patterns, as_json)

    components: list[dict] = []
    styles: list = []
    for source_file in section_files:
        section_data = _read_section_file(source_file, as_json)
        section_component, section_styles = _classify_and_resolve(
            section_data, source_file, as_json
        )
        _validate_section_component(section_component, source_file, as_json)
        components.append(section_component)
        _merge_styles(styles, section_styles)

    if header_block_guid:
        components.insert(0, _make_global_block_wrapper("Global: Header", header_block_guid))
    if footer_block_guid:
        components.append(_make_global_block_wrapper("Global: Footer", footer_block_guid))

    result = {"components": components, "styles": styles}

    output_path = Path(output_file)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {output_file}: {exc}", as_json)

    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Assembled {len(components)} section(s) from {len(section_files)} file(s) "
            f"-> {output_file}"
        ),
        output=str(output_path),
        sections=len(section_files),
        components=len(components),
    )
