"""Every `vanjaro ...` command named in an agent skill must exist in the CLI.

Skills are the interface agents build sites through. When a command is renamed
or removed, the skill silently keeps instructing agents to call it, so this
guards documentation drift the unit suite cannot otherwise see.
"""

from __future__ import annotations

from pathlib import Path
import re

import click
import pytest

from vanjaro_cli.cli import cli

SKILLS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills"

# `vanjaro group sub` or `vanjaro command`, ignoring options and placeholders.
_INVOCATION = re.compile(r"\bvanjaro\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*))?")


def _skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.rglob("*.md"))


def _referenced_commands(text: str) -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for group, sub in _INVOCATION.findall(text):
        found.add((group, sub) if sub else (group,))
    return found


def _resolve(parts: tuple[str, ...]) -> click.Command | None:
    command: click.Command | None = cli
    for part in parts:
        if not isinstance(command, click.Group):
            return None
        command = command.get_command(click.Context(command), part)
        if command is None:
            return None
    return command


def test_skills_directory_is_present() -> None:
    assert _skill_files(), f"No skill documents found under {SKILLS_DIR}"


@pytest.mark.parametrize("skill_file", _skill_files(), ids=lambda p: p.name)
def test_referenced_commands_exist(skill_file: Path) -> None:
    unknown: list[str] = []
    for parts in sorted(_referenced_commands(skill_file.read_text(encoding="utf-8"))):
        if _resolve(parts) is not None:
            continue
        # A bare group name is fine; a two-token miss is real drift.
        if len(parts) == 1:
            unknown.append(f"vanjaro {parts[0]}")
        elif _resolve(parts[:1]) is None:
            unknown.append(f"vanjaro {parts[0]}")
        else:
            unknown.append(f"vanjaro {' '.join(parts)}")

    assert not unknown, (
        f"{skill_file.relative_to(SKILLS_DIR.parent.parent)} references commands "
        f"that do not exist: {sorted(set(unknown))}"
    )
