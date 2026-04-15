"""vanjaro migrate compose-global — compose a global block from a crawled header/footer.

Bridges the shape mismatch between what the crawler writes (a section-shaped
``{type, template, content}`` dict in ``global/header.json`` /
``global/footer.json``) and what ``vanjaro blocks compose`` expects (a flat
``{key: value}`` overrides file against a named block template).

Reads a crawled global element, derives the override dict via
``crawl_content_to_overrides``, merges any ``--set`` extras, applies them to
the requested template, and writes a composed block JSON ready to feed
``vanjaro global-blocks create --file ...``. The follow-up create step
returns the GUID Stage 5.1's ``assemble-page --header-block-guid`` /
``--footer-block-guid`` flags need.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, read_json_object
from vanjaro_cli.migration.overrides import crawl_content_to_overrides
from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides,
    check_overflow,
    find_template,
)

__all__ = ["compose_global"]


def _parse_set_pairs(pairs: tuple[str, ...]) -> dict[str, str]:
    """Parse ``--set key=value`` pairs into a dict. Raises ``click.BadParameter``."""
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(
                f"Invalid format '{pair}', expected key=value",
                param_hint="'--set'",
            )
        key, _, value = pair.partition("=")
        result[key.strip()] = value
    return result


@click.command("compose-global")
@click.option(
    "--source",
    "source_file",
    type=click.Path(),
    required=True,
    help="Path to the crawled global element JSON (global/header.json or "
    "global/footer.json).",
)
@click.option(
    "--template",
    "template_name",
    required=True,
    help="Block template name to compose the extracted content against. "
    "Use `vanjaro blocks templates` to list available templates.",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    required=True,
    help="Destination path for the composed block JSON — pass this to "
    "`vanjaro global-blocks create --file ...`.",
)
@click.option(
    "--set",
    "-s",
    "set_pairs",
    multiple=True,
    help="Additional override as key=value (repeatable). Overrides take "
    "precedence over values derived from the source.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def compose_global(
    source_file: str,
    template_name: str,
    output_file: str,
    set_pairs: tuple[str, ...],
    as_json: bool,
) -> None:
    """Compose a global block from a crawled header/footer file.

    \b
    Example:
      vanjaro migrate compose-global \\
        --source artifacts/migration/example-com/global/footer.json \\
        --template "Footer (3-column)" \\
        --output artifacts/migration/example-com/global/footer-composed.json \\
        --set heading_1="Quick Links" --set heading_2="Contact" --set heading_3="Follow Us"
    """
    source_path = Path(source_file)
    source = read_json_object(source_path, "Global element file", as_json)

    content = source.get("content")
    if not isinstance(content, dict):
        exit_error(
            f"{source_path} is missing a top-level 'content' object — "
            "is this a crawled header/footer file?",
            as_json,
        )

    derived_overrides = crawl_content_to_overrides(content)

    try:
        extra_overrides = _parse_set_pairs(set_pairs)
    except click.BadParameter as exc:
        exit_error(str(exc), as_json)

    # --set values override derived ones so callers can patch per-site
    # specifics (canonical logo path, preferred section headings, ...)
    # without re-running the crawl.
    overrides = {**derived_overrides, **extra_overrides}

    try:
        template_data = find_template(template_name)
    except TemplateNotFoundError as exc:
        exit_error(str(exc), as_json)

    composed = apply_overrides(template_data, overrides)

    unused = check_overflow(template_data, overrides) if overrides else []
    if unused and not as_json:
        click.echo(
            f"Warning: {len(unused)} override(s) had no matching slot and were dropped: "
            + ", ".join(unused),
            err=True,
        )

    output_path = Path(output_file)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(composed, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {output_path}: {exc}", as_json)

    output_result(
        as_json,
        status="composed",
        human_message=(
            f"Composed '{template_data['name']}' from {source_path.name} "
            f"with {len(overrides)} override(s) -> {output_path}"
        ),
        source=str(source_path),
        template_name=template_data["name"],
        output=str(output_path),
        overrides_applied=len(overrides),
        dropped_overrides=unused,
    )
