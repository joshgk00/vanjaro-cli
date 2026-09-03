"""CLI presentation for deterministic agency handoff artifacts."""

from __future__ import annotations

from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.orchestration import ProjectHandoffError, generate_project_handoff


@click.command("handoff")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def handoff_project(directory: Path, as_json: bool) -> None:
    """Generate an editor handoff and maintenance scorecard from verify evidence."""

    try:
        result = generate_project_handoff(directory)
    except ProjectHandoffError as exc:
        exit_error(str(exc), as_json)
    output_result(
        as_json,
        status=result.status,
        human_message=(
            f"Agency handoff: {result.status}; maintenance score {result.score}/100.\n"
            f"Scorecard: {result.scorecard_path}\n"
            f"Editor handoff: {result.handoff_path}\n"
            + (
                "This project is not publish-ready; resolve failed and unavailable checks."
                if result.status == "review_required"
                else "All handoff checks passed; publication still requires its separate approval."
            )
        ),
        score=result.score,
        fingerprint=result.fingerprint,
        scorecard_path=str(result.scorecard_path),
        handoff_path=str(result.handoff_path),
    )


__all__ = ["handoff_project"]
