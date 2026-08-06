"""vanjaro fidelity rank — regenerate the work queue from current corpus evidence."""

from __future__ import annotations

import json
from pathlib import Path

import click
from pydantic import ValidationError

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.design.finding_ledger import CorpusLedger
from vanjaro_cli.design.finding_rank import (
    rank_ledger,
    render_ranked_queue,
)


__all__ = ["fidelity"]


@click.group()
def fidelity() -> None:
    """Inspect and rank corpus-wide fidelity evidence."""


def _read_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise click.ClickException(f"{label} not found: {path}") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise click.ClickException(f"{label} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException(f"{label} must contain an object")
    return payload


@fidelity.command("rank")
@click.argument("ledger_path", type=click.Path(path_type=Path))
@click.option(
    "--effort",
    type=click.Path(path_type=Path),
    help=(
        "JSON object mapping cluster key to estimated effort. Any cluster left "
        "out ranks at the default effort and is reported as not estimated."
    ),
)
@click.option(
    "--blocked",
    type=click.Path(path_type=Path),
    help=(
        "JSON object mapping cluster key to the reason it is blocked. Blocked "
        "clusters keep their evidence and sort last."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def rank(
    ledger_path: Path,
    effort: Path | None,
    blocked: Path | None,
    as_json: bool,
) -> None:
    """Rank LEDGER_PATH by corpus-wide impact over declared effort.

    The queue is recomputed from the file on every invocation and never cached,
    so it cannot report work that the current evidence no longer supports.
    """

    try:
        ledger = CorpusLedger.model_validate(_read_json(ledger_path, "corpus ledger"))
    except ValidationError as exc:
        exit_error(f"corpus ledger does not match the ledger schema: {exc}", as_json)

    effort_map = _read_json(effort, "effort map") if effort else None
    blocked_map = _read_json(blocked, "blocked map") if blocked else None
    if effort_map is not None and not all(
        isinstance(value, (int, float)) for value in effort_map.values()
    ):
        exit_error("effort map values must be numbers", as_json)
    if blocked_map is not None and not all(
        isinstance(value, str) for value in blocked_map.values()
    ):
        exit_error("blocked map values must be strings", as_json)

    queue = rank_ledger(ledger, effort=effort_map, blocked=blocked_map)
    next_up = queue.next_unblocked
    output_result(
        as_json,
        status="ok",
        human_message=render_ranked_queue(queue),
        queue=json.loads(queue.model_dump_json()),
        next_cluster=next_up.key if next_up else None,
    )
