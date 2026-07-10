"""vanjaro migrate assemble-page — merge per-section JSON files into a page content JSON."""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, read_json_file
from vanjaro_cli.migration.dedup import parse_global_placeholder
from vanjaro_cli.migration.global_blocks import _section_group, make_global_block_wrapper
from vanjaro_cli.migration.overrides import crawl_content_to_overrides
from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides,
    apply_section_background,
    attach_form_placeholder,
    check_overflow,
    enumerate_slots,
    find_template,
    promote_background_images,
    prune_unfilled_images,
)
from vanjaro_cli.utils.theme_palette import PaletteError, load_palette

__all__ = ["assemble_page"]

# The composition audit counts direct children of #vjEditor and rewards 3-9.
# Once header/footer chrome plus interior sections would exceed this, group the
# interior sections into a few full-width wrapper nodes to pull the count back
# in range without changing the page's visual layout.
_MAX_TOP_LEVEL_CHILDREN = 9
_TARGET_SECTION_GROUPS = 3


def _group_interior_sections(sections: list[dict], reserved_chrome: int) -> list[dict]:
    """Wrap interior sections in container nodes to cap top-level child count.

    ``reserved_chrome`` is the number of top-level header/footer wrappers that
    will bracket these sections (0-2). Those wrappers must stay top-level and
    unwrapped so Vanjaro expands them server-side, so they only factor into the
    child budget here, never the grouping. Sections are split into contiguous,
    order-preserving, size-balanced groups; each group becomes one full-width
    wrapper node, so the top-level count drops to ``reserved_chrome`` + group
    count. Left unchanged when the count already fits (idempotent-safe).
    """
    if len(sections) + reserved_chrome <= _MAX_TOP_LEVEL_CHILDREN:
        return sections

    group_count = min(_TARGET_SECTION_GROUPS, len(sections))
    base_size, remainder = divmod(len(sections), group_count)

    groups: list[dict] = []
    start = 0
    for index in range(group_count):
        size = base_size + (1 if index < remainder else 0)
        groups.append(_section_group(sections[start:start + size]))
        start += size
    return groups


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


def _blank_unfilled_content_slots(
    template_name: str,
    overrides: dict[str, str],
    as_json: bool,
) -> dict[str, str]:
    """Blank every content slot the crawled overrides don't fill.

    Slots are enumerated from the EXPANDED template (column units and
    text/image slots cloned to fit the overrides) — cloned units carry the
    template's placeholder copy, which must never ship either.
    """
    try:
        template_data = find_template(template_name)
    except TemplateNotFoundError:
        return overrides  # the compose step reports this with full context
    expanded = apply_overrides(template_data, overrides)
    filled = dict(overrides)
    for slot in enumerate_slots(expanded["template"]):
        if slot["field"] == "content" and slot["key"] not in filled:
            filled[slot["key"]] = ""
    return filled


def _detect_heading_text_offset(slots: list[dict], content: dict) -> int:
    """Detect whether a template's heading/text numbering is offset from its images.

    Some templates (Gallery (3-up)/(6-up)) place a leading section-title
    heading+text pair ahead of a repeating per-item group — the title
    occupies heading_1/text_1 while image_1 belongs to item 1, so direct
    index-for-index mapping puts item 1's heading in the title slot and
    shifts every subsequent heading/text one position ahead of its sibling
    image. Detected structurally (heading/text slot count is exactly one
    more than image slot count) rather than by template name, so any
    template with this shape benefits automatically.

    Only apply the shift when the crawled content itself has no separate
    title of its own — i.e. exactly one heading and one paragraph per image.
    If the content already supplies an extra leading heading/paragraph,
    direct mapping is already correct.
    """
    heading_slots = sum(1 for s in slots if s["type"] == "heading" and s["field"] == "content")
    text_slots = sum(1 for s in slots if s["type"] == "text" and s["field"] == "content")
    image_slots = sum(1 for s in slots if s["type"] == "image" and s["key"].endswith("_src"))

    if image_slots == 0 or heading_slots != image_slots + 1 or text_slots != image_slots + 1:
        return 0

    headings = content.get("headings")
    paragraphs = content.get("paragraphs")
    images = content.get("images")
    if not (isinstance(headings, list) and isinstance(paragraphs, list) and isinstance(images, list)):
        return 0
    if len(images) == 0 or len(headings) != len(images) or len(paragraphs) != len(images):
        return 0

    return 1


def _classify_and_resolve(
    section_data: dict,
    source_file: Path,
    as_json: bool,
    palette: dict[str, tuple[int, int, int]] | None = None,
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

        content_block = section_data.get("content")
        if isinstance(content_block, dict):
            promote_background_images(content_block, section_data.get("type"))

        raw_overrides = section_data.get("overrides")
        is_crawler_content = raw_overrides is None and "content" in section_data
        if is_crawler_content:
            content_block = section_data.get("content")
            if not isinstance(content_block, dict):
                exit_error(
                    f"Section file {source_file} has a 'content' key that is not an object.",
                    as_json,
                )
            try:
                template_slots = enumerate_slots(find_template(template_name)["template"])
            except TemplateNotFoundError:
                template_slots = []
            offset = _detect_heading_text_offset(template_slots, content_block)
            overrides = crawl_content_to_overrides(content_block, index_offset=offset)
            # Crawled content is the complete source of truth for the section:
            # any template slot it doesn't fill must render empty, not leak
            # the template's placeholder copy ("Your Headline Here").
            overrides = _blank_unfilled_content_slots(template_name, overrides, as_json)
        elif raw_overrides is None:
            overrides = {}
        elif isinstance(raw_overrides, dict):
            overrides = {str(k): str(v) for k, v in raw_overrides.items()}
        else:
            exit_error(
                f"Section file {source_file} has an 'overrides' key that is not an object.",
                as_json,
            )

        section, styles = _compose_template_section(
            template_name, overrides, source_file, as_json
        )
        if is_crawler_content:
            # Same rationale as the content-slot blanking above: an unfilled
            # image slot must not ship the template's placehold.co placeholder
            # image. Manual --overrides mode leaves images untouched — a
            # designer may want the placeholder there.
            prune_unfilled_images(section, overrides)
        content_block = section_data.get("content")
        if isinstance(content_block, dict):
            form_fields = content_block.get("form_fields")
            if isinstance(form_fields, list) and form_fields:
                attach_form_placeholder(section, form_fields)
            apply_section_background(section, content_block, palette=palette, styles=styles)
        return section, styles

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


def _load_global_guids(manifest_path: str | None, as_json: bool) -> dict[str, str]:
    """Load a {dedup-key -> GUID} manifest, or return an empty mapping."""
    if not manifest_path:
        return {}
    data = read_json_file(Path(manifest_path), "Global GUID manifest", as_json)
    if not isinstance(data, dict):
        exit_error(f"Global GUID manifest {manifest_path} must be a JSON object.", as_json)
    return {str(key): str(value) for key, value in data.items()}


def _resolve_global_placeholders(
    component: dict,
    guid_manifest: dict[str, str],
    source_file: Path,
    as_json: bool,
) -> None:
    """Swap ``{{global:KEY}}`` data-guid placeholders for manifest GUIDs in place.

    Recurses the composed component tree. A placeholder with no manifest entry
    is a hard error — assembling a page with an unresolved global reference
    would emit a wrapper Vanjaro can't expand.
    """
    attributes = component.get("attributes")
    if isinstance(attributes, dict):
        data_guid = attributes.get("data-guid")
        if isinstance(data_guid, str):
            key = parse_global_placeholder(data_guid)
            if key is not None:
                guid = guid_manifest.get(key)
                if not guid:
                    exit_error(
                        f"Section file {source_file} references global block '{key}' "
                        "but no matching entry exists in the --global-guids manifest. "
                        "Run `vanjaro blocks build-library --guids-out` on the dedup plan first.",
                        as_json,
                    )
                attributes["data-guid"] = guid

    nested = component.get("components")
    if isinstance(nested, list):
        for child in nested:
            if isinstance(child, dict):
                _resolve_global_placeholders(child, guid_manifest, source_file, as_json)


def _resolve_global_stub(
    stub: dict,
    guid_manifest: dict[str, str],
    source_file: Path,
    as_json: bool,
) -> tuple[list[dict], list]:
    """Extract a dedup stub's wrapper components with placeholders resolved.

    The stub's helper keys (``global_key``, ``original_backup``) never reach
    output — only the wrapper components inside its ``components`` array do.
    """
    wrappers = stub.get("components")
    if not isinstance(wrappers, list) or not wrappers:
        exit_error(
            f"Global stub {source_file} has no 'components' wrapper to assemble.",
            as_json,
        )
    for wrapper in wrappers:
        if isinstance(wrapper, dict):
            _resolve_global_placeholders(wrapper, guid_manifest, source_file, as_json)
    styles = stub.get("styles") or []
    if not isinstance(styles, list):
        styles = []
    return [wrapper for wrapper in wrappers if isinstance(wrapper, dict)], styles


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
@click.option(
    "--global-guids",
    "global_guids_file",
    type=click.Path(),
    default=None,
    help="Manifest mapping dedup keys to registered global block GUIDs. "
    "Resolves {{global:KEY}} placeholders left by `migrate dedup-sections`.",
)
@click.option(
    "--theme-palette",
    "theme_palette_file",
    type=click.Path(),
    default=None,
    help="Palette JSON (from `vanjaro theme palette-export`). Maps section band "
    "colors to theme classes (bg-primary, text-light, ...) instead of inline "
    "color, so re-theming the site cascades through migrated sections.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def assemble_page(
    section_patterns: tuple[str, ...],
    output_file: str,
    header_block_guid: str | None,
    footer_block_guid: str | None,
    global_guids_file: str | None,
    theme_palette_file: str | None,
    as_json: bool,
) -> None:
    """Merge per-section JSON files into a single page content JSON.

    Each --sections value may be a path or a glob pattern (expanded on Windows
    and Unix alike). Two section file formats are supported:

    \b
      1. Raw component tree with top-level "components".
      2. Template reference: {"template": "Name", "overrides": {...}}
         or the crawler shape: {"template": "Name", "content": {...}}.
      3. Dedup stub (from `migrate dedup-sections`): a "global_key" plus a
         globalblockwrapper whose data-guid is a {{global:KEY}} placeholder,
         resolved against the --global-guids manifest.

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
    guid_manifest = _load_global_guids(global_guids_file, as_json)

    palette: dict[str, tuple[int, int, int]] | None = None
    if theme_palette_file:
        try:
            palette = load_palette(theme_palette_file)
        except PaletteError as exc:
            exit_error(str(exc), as_json)

    components: list[dict] = []
    styles: list = []
    for source_file in section_files:
        section_data = _read_section_file(source_file, as_json)
        if section_data.get("global_key") is not None:
            wrappers, section_styles = _resolve_global_stub(
                section_data, guid_manifest, source_file, as_json
            )
            components.extend(wrappers)
        else:
            section_component, section_styles = _classify_and_resolve(
                section_data, source_file, as_json, palette
            )
            _validate_section_component(section_component, source_file, as_json)
            components.append(section_component)
        _merge_styles(styles, section_styles)

    reserved_chrome = bool(header_block_guid) + bool(footer_block_guid)
    components = _group_interior_sections(components, reserved_chrome)

    if header_block_guid:
        components.insert(0, make_global_block_wrapper("Global: Header", header_block_guid))
    if footer_block_guid:
        components.append(make_global_block_wrapper("Global: Footer", footer_block_guid))

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
