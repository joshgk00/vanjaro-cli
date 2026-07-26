"""CLI presentation for explicit project image evidence generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import click
from pydantic import ValidationError

from vanjaro_cli.evidence.openai_provider import (
    DEFAULT_IMAGE_EVIDENCE_MODEL,
    OpenAIImageEvidenceConfig,
    OpenAIImageEvidenceError,
    OpenAIImageEvidenceProvider,
)
from vanjaro_cli.orchestration import (
    ProjectImageEvidenceError,
    generate_project_image_evidence,
    plan_project_image_evidence,
)
from vanjaro_cli.project import ProjectWorkspaceError


@click.group("evidence")
def evidence() -> None:
    """Generate and inspect source evidence before project analysis."""


@evidence.command("generate")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--source",
    "source_ids",
    multiple=True,
    metavar="SOURCE_ID",
    help="Generate only this image source; repeat for multiple breakpoints.",
)
@click.option(
    "--provider",
    type=click.Choice(["openai"]),
    default="openai",
    show_default=True,
)
@click.option(
    "--model",
    default=None,
    help=(
        "Vision-capable structured-output model. Defaults to "
        "VANJARO_IMAGE_EVIDENCE_MODEL or " + DEFAULT_IMAGE_EVIDENCE_MODEL + "."
    ),
)
@click.option(
    "--detail",
    type=click.Choice(["low", "high", "auto"]),
    default="high",
    show_default=True,
)
@click.option(
    "--max-output-tokens",
    type=click.IntRange(min=1024, max=128000),
    default=32768,
    show_default=True,
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Regenerate existing sidecars after snapshotting them under history/evidence.",
)
@click.option("--by", "generated_by", default="cli-user", show_default=True)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Validate images and report actions without reading credentials, calling a provider, or writing files.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def generate_evidence(
    directory: Path,
    source_ids: tuple[str, ...],
    provider: str,
    model: str | None,
    detail: str,
    max_output_tokens: int,
    overwrite: bool,
    generated_by: str,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Create strict, hash-bound sidecars for declared project images."""

    try:
        plan = plan_project_image_evidence(
            directory,
            source_ids=source_ids,
            overwrite=overwrite,
        )
        if dry_run:
            payload = plan.as_dict()
            if as_json:
                click.echo(json.dumps({"status": "ok", "dry_run": True, **payload}))
            else:
                click.echo(
                    f"Image evidence dry run: {payload['generate_count']} generate, "
                    f"{payload['skip_count']} skip."
                )
                for item in payload["items"]:
                    click.echo(
                        f"- {item['source_id']}: {item['action']} -> "
                        f"{item['evidence_reference']}"
                    )
            return
        selected_provider = None
        if any(item.action != "skip" for item in plan.items):
            if provider != "openai":  # pragma: no cover - guarded by Click
                raise ValueError(f"unsupported image evidence provider: {provider}")
            config = OpenAIImageEvidenceConfig.from_environment(
                model=model,
                detail=detail,  # type: ignore[arg-type]
                max_output_tokens=max_output_tokens,
            )
            selected_provider = OpenAIImageEvidenceProvider(config)
        result = generate_project_image_evidence(
            directory,
            selected_provider,
            source_ids=source_ids,
            overwrite=overwrite,
            generated_by=generated_by,
        )
    except ProjectImageEvidenceError as exc:
        _exit_structured(exc.as_dict(), as_json)
    except OpenAIImageEvidenceError as exc:
        _exit_structured(exc.as_dict(), as_json)
    except (ProjectWorkspaceError, ValidationError, ValueError) as exc:
        _exit_structured(
            {
                "category": "image_evidence_configuration_error",
                "message": str(exc),
                "recommended_action": "Check the project image declarations and provider options.",
            },
            as_json,
        )

    payload = result.as_dict()
    if as_json:
        click.echo(json.dumps({"status": "ok", "dry_run": False, **payload}))
        return
    click.echo(
        f"Generated image evidence for {len(result.generated_sources)} source(s); "
        f"skipped {len(result.skipped_sources)}."
    )
    for artifact in result.artifacts:
        click.echo(f"- {artifact}")


def _exit_structured(error: dict[str, object], as_json: bool) -> NoReturn:
    if as_json:
        click.echo(json.dumps({"status": "error", "error": error}))
        raise SystemExit(1)
    message = str(error.get("message", "image evidence generation failed"))
    action = error.get("recommended_action")
    if action:
        message += f"\nRecommended action: {action}"
    raise click.ClickException(message)


__all__ = ["evidence"]
