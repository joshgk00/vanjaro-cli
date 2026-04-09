"""vanjaro blocks templates — list available block templates from the library."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import print_table
from vanjaro_cli.utils.block_compose import get_templates_dir

__all__ = ["block_templates"]


def _load_templates(templates_dir: Path, category: str | None = None) -> list[dict]:
    """Scan the templates directory and return metadata from each JSON file."""
    if not templates_dir.is_dir():
        return []

    templates: list[dict] = []
    for json_file in sorted(templates_dir.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        tpl_category = data.get("category", json_file.parent.name)
        if category and tpl_category.lower() != category.lower():
            continue

        templates.append({
            "name": data.get("name", json_file.stem),
            "category": tpl_category,
            "description": data.get("description", ""),
            "file": json_file.relative_to(templates_dir).as_posix(),
        })

    return templates


@click.command("templates")
@click.option("--category", "-c", default=None, help="Filter by category name.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def block_templates(category: str | None, as_json: bool) -> None:
    """List available block templates from the library."""
    templates_dir = get_templates_dir()
    templates = _load_templates(templates_dir, category)

    if as_json:
        click.echo(json.dumps(templates, indent=2))
    else:
        if not templates:
            msg = "No block templates found"
            if category:
                msg += f" in category '{category}'"
            click.echo(f"{msg}.")
            return
        print_table(["name", "category", "description"], templates)
