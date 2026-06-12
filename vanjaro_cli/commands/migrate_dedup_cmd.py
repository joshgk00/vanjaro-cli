"""vanjaro migrate dedup-sections — collapse cross-page duplicate sections.

Sections that repeat verbatim across multiple pages are rewritten to a global
block reference so editing the block once updates every page. The command
writes a ``global-sections-plan.json`` for ``blocks build-library`` and
rewrites each duplicate section file to a Mode-A stub whose wrapper carries a
``{{global:KEY}}`` placeholder. ``migrate assemble-page --global-guids``
swaps the placeholder for the real GUID after registration.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, print_table
from vanjaro_cli.migration.dedup import (
    DuplicateGroup,
    find_duplicate_groups,
    global_placeholder,
    humanize_key,
)
from vanjaro_cli.migration.global_blocks import make_global_block_wrapper
from vanjaro_cli.migration.overrides import crawl_content_to_overrides

__all__ = ["dedup_sections"]

GLOBAL_SECTIONS_PLAN_NAME = "global-sections-plan.json"
GLOBAL_SECTIONS_CATEGORY = "Global Sections"


def _plan_entry(group: DuplicateGroup) -> dict:
    """Build a build-library plan entry for a duplicate group's canonical section."""
    content = group.canonical.get("content")
    overrides = crawl_content_to_overrides(content) if isinstance(content, dict) else {}
    return {
        "template": group.canonical.get("template", ""),
        "name": humanize_key(group.key),
        "key": group.key,
        "category": GLOBAL_SECTIONS_CATEGORY,
        "type": "global",
        "overrides": overrides,
    }


def _make_placeholder_wrapper(group: DuplicateGroup) -> dict:
    """Build a globalblockwrapper whose data-guid is a ``{{global:KEY}}`` token."""
    return make_global_block_wrapper(
        f"Global: {group.name}", global_placeholder(group.key)
    )


def _stub_section(group: DuplicateGroup, original: dict) -> dict:
    """Build the Mode-A stub that replaces a duplicate section file.

    The original section is embedded under ``original_backup`` so the rewrite
    is reversible and inspectable; ``global_key`` records which global block
    the wrapper resolves to.
    """
    return {
        "components": [_make_placeholder_wrapper(group)],
        "global_key": group.key,
        "original_backup": original,
    }


def _print_groups(groups: list[DuplicateGroup]) -> None:
    """Print each group's key, pages, and member section files."""
    for group in groups:
        click.echo(f"\n{group.key}  ({len(group.member_files)} sections across {len(group.pages)} pages)")
        click.echo(f"  pages: {', '.join(group.pages)}")
        for member in group.member_files:
            click.echo(f"  - {member}")


@click.command("dedup-sections")
@click.argument("migration_root", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, help="Print duplicate groups without writing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def dedup_sections(migration_root: str, dry_run: bool, as_json: bool) -> None:
    """Collapse sections that repeat across pages into global block references.

    MIGRATION_ROOT is the crawl output directory containing a ``pages/``
    subdirectory. Sections sharing identical normalized content across two or
    more distinct pages are treated as duplicates.

    \b
    Default run writes:
      - global-sections-plan.json at the migration root.
      - a Mode-A stub over every duplicate section file (original embedded
        under "original_backup").

    \b
    Example:
      vanjaro migrate dedup-sections artifacts/migration/acme
      vanjaro blocks build-library --plan artifacts/migration/acme/global-sections-plan.json \\
        --guids-out artifacts/migration/acme/global-guids.json
      vanjaro migrate assemble-page --sections "artifacts/migration/acme/pages/home/section-*.json" \\
        --output home.json --global-guids artifacts/migration/acme/global-guids.json
    """
    root = Path(migration_root)
    pages_dir = root / "pages"
    if not pages_dir.is_dir():
        exit_error(f"No pages/ directory under {migration_root}.", as_json)

    groups = find_duplicate_groups(pages_dir)

    if dry_run:
        if as_json:
            output_result(
                as_json,
                status="ok",
                human_message="",
                groups=[
                    {
                        "key": group.key,
                        "pages": group.pages,
                        "files": [str(member) for member in group.member_files],
                    }
                    for group in groups
                ],
            )
        elif not groups:
            click.echo("No cross-page duplicate sections found.")
        else:
            click.echo(f"Found {len(groups)} duplicate group(s):")
            _print_groups(groups)
        return

    if not groups:
        output_result(
            as_json,
            status="ok",
            human_message="No cross-page duplicate sections found — nothing to dedup.",
            groups=[],
            plan=None,
        )
        return

    plan = [_plan_entry(group) for group in groups]
    plan_path = root / GLOBAL_SECTIONS_PLAN_NAME
    try:
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {plan_path}: {exc}", as_json)

    rewritten = 0
    for group in groups:
        for member, original in group.member_sections:
            stub = _stub_section(group, original)
            try:
                member.write_text(json.dumps(stub, indent=2), encoding="utf-8")
            except OSError as exc:
                exit_error(f"Cannot rewrite {member}: {exc}", as_json)
            rewritten += 1

    if as_json:
        output_result(
            as_json,
            status="ok",
            human_message="",
            plan=str(plan_path),
            groups=[
                {"key": group.key, "name": group.name, "pages": group.pages,
                 "sections": len(group.member_files)}
                for group in groups
            ],
            sections_rewritten=rewritten,
        )
    else:
        click.echo(f"Wrote {plan_path}")
        click.echo(f"Rewrote {rewritten} section file(s) across {len(groups)} group(s).\n")
        print_table(
            ["key", "name", "pages", "sections"],
            [
                {
                    "key": group.key,
                    "name": group.name,
                    "pages": len(group.pages),
                    "sections": len(group.member_files),
                }
                for group in groups
            ],
        )
