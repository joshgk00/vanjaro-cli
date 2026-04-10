"""vanjaro blocks compose — customize a template with content overrides."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, print_table, write_output
from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides,
    check_overflow,
    enumerate_slots,
    find_template,
)

__all__ = ["block_compose"]


def _parse_set_pairs(pairs: tuple[str, ...]) -> dict[str, str]:
    """Parse --set key=value pairs into a dict."""
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


@click.command("compose")
@click.argument("template_name")
@click.option("--set", "-s", "set_pairs", multiple=True, help="Content override as key=value (repeatable).")
@click.option(
    "--overrides", "-O", "overrides_file",
    type=click.Path(exists=True),
    default=None,
    help="JSON file with override key-value pairs.",
)
@click.option("--output", "-o", type=click.Path(), default=None, help="Write composed template to file.")
@click.option("--list-slots", "list_slots", is_flag=True, help="Show available override slots instead of composing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def block_compose(
    template_name: str,
    set_pairs: tuple[str, ...],
    overrides_file: str | None,
    output: str | None,
    list_slots: bool,
    as_json: bool,
) -> None:
    """Customize a block template with content overrides.

    TEMPLATE_NAME is matched case-insensitively against the template library.

    \b
    Examples:
      vanjaro blocks compose "Centered Hero" --list-slots
      vanjaro blocks compose "Centered Hero" -s heading_1="Welcome" -o hero.json
      vanjaro blocks compose "Feature Cards (3-up)" -O overrides.json
    """
    try:
        template_data = find_template(template_name)
    except TemplateNotFoundError as exc:
        exit_error(str(exc), as_json)

    if list_slots:
        slots = enumerate_slots(template_data["template"])
        if as_json:
            click.echo(json.dumps(slots, indent=2))
        else:
            if not slots:
                click.echo(f"Template '{template_data['name']}' has no overridable slots.")
                return
            truncated = [
                {
                    "key": s["key"],
                    "type": s["type"],
                    "value": s["value"][:50] + "..." if len(s["value"]) > 50 else s["value"],
                }
                for s in slots
            ]
            print_table(["key", "type", "value"], truncated)
        return

    overrides: dict[str, str] = {}
    if overrides_file:
        try:
            overrides = json.loads(Path(overrides_file).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            exit_error(f"Cannot read overrides file: {exc}", as_json)

    try:
        overrides.update(_parse_set_pairs(set_pairs))
    except click.BadParameter as exc:
        exit_error(str(exc), as_json)

    composed = apply_overrides(template_data, overrides)

    unused = check_overflow(template_data, overrides) if overrides else []
    if unused:
        click.echo(
            f"Warning: {len(unused)} override(s) had no matching slot and were dropped: "
            + ", ".join(unused),
            err=True,
        )

    if output:
        payload = json.dumps(composed, indent=2)
        write_output(output, payload, as_json)
        override_count = len(overrides)
        if as_json:
            output_result(
                as_json,
                status="composed",
                human_message="",
                template_name=template_data["name"],
                overrides_applied=override_count,
                output_file=output,
            )
        else:
            click.echo(f"Composed '{template_data['name']}' with {override_count} override(s) -> {output}")
    elif as_json:
        click.echo(json.dumps({"status": "composed", "template_name": template_data["name"], "overrides_applied": len(overrides), "result": composed}, indent=2))
    else:
        click.echo(json.dumps(composed, indent=2))
