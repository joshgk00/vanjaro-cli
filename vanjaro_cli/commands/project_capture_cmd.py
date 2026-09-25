"""CLI presentation for operator-facing design-to-build page capture.

Click handling stays thin: every planning, identity, and route decision
lives in `vanjaro_cli.orchestration.project_capture_cli_plan`, which this
module treats as the single source of truth for what is safe to preview or
capture. The real capture collector (`project_capture_collect.py`) is owned
by a concurrent workstream and is not implemented here -- it is imported
lazily, only on an actual (non-dry-run) invocation, through the
`_collect_page_capture` module-level wrapper below, so `--help` and
`--dry-run` never require it to exist and tests can substitute a fake
collector by patching that one name.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click

from vanjaro_cli.commands.helpers import exit_error
from vanjaro_cli.design.capture_references import SourceReference
from vanjaro_cli.design.capture_session import PlaywrightCaptureSession
from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.orchestration.portal_identity import verify_project_portal
from vanjaro_cli.orchestration.project_capture_cli_plan import (
    CaptureCliPlan,
    CapturePlanError,
    CaptureReferenceDecodeError,
    build_capture_cli_plan,
    decode_capture_references,
    describe_page_capture_result,
    load_resolved_design_document,
    parse_built_url_overrides,
    render_dry_run_preview,
    resolve_references_path,
    summarize_capture_results,
)
from vanjaro_cli.project import ProjectWorkspaceError, load_manifest
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json
from vanjaro_cli.reliability.diagnostics import redact_diagnostic_text

__all__ = ["project_capture"]


def _default_collect_page_capture(
    root: Path,
    document: DesignDocument,
    manifest: ProjectManifest,
    *,
    page_id: str,
    built_url: str,
    capture_session: PlaywrightCaptureSession,
    references: Sequence[SourceReference],
    target_verifier: Any,
) -> dict[str, Any]:
    """Lazily import and invoke the concurrently-developed capture collector.

    Deferred so importing this command module -- for `--help`, `--dry-run`,
    or any test that never reaches real capture -- never requires
    `project_capture_collect.py` to exist or be importable.
    """

    from vanjaro_cli.orchestration.project_capture_collect import collect_page_capture

    return collect_page_capture(
        root,
        document,
        manifest,
        page_id=page_id,
        built_url=built_url,
        capture_session=capture_session,
        references=references,
        target_verifier=target_verifier,
    )


# Module-level indirection so tests can substitute a fake collector with
# `monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)`.
_collect_page_capture = _default_collect_page_capture


@click.command("capture")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--page",
    "page_ids",
    multiple=True,
    metavar="PAGE_ID",
    help="Capture only this design page id; repeatable. Defaults to every page.",
)
@click.option(
    "--references",
    "references_path",
    type=click.Path(path_type=Path),
    default=None,
    help="capture-references-v1 JSON document of explicit live/static source references.",
)
@click.option(
    "--built-url",
    "built_url_specs",
    multiple=True,
    metavar="PAGE_ID=URL",
    help="Explicit built-route override for one page id; repeatable.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Preview the capture plan from local files only: no config lookup, "
        "portal health check, browser, or evidence writes."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def project_capture(
    directory: Path,
    page_ids: tuple[str, ...],
    references_path: Path | None,
    built_url_specs: tuple[str, ...],
    dry_run: bool,
    as_json: bool,
) -> None:
    """Capture built-output evidence against live, image, or Figma design references.

    Pages are selected by opaque design page id (`--page`, repeatable;
    defaults to every page in `plans/resolved-design-document.json`). Each
    selected page must have exactly one managed mapping in
    `build/page-manifest.json`; its built route comes from that record's
    server-returned path unless overridden with `--built-url
    PAGE_ID=URL`. `--dry-run` never loads credentials, contacts the target,
    launches a browser, or writes evidence -- it only resolves and previews
    the plan from files already on disk.
    """

    root = directory.expanduser().resolve()

    try:
        manifest = load_manifest(root)
    except ProjectWorkspaceError as exc:
        exit_error(str(exc), as_json)

    try:
        document = load_resolved_design_document(root)
    except CapturePlanError as exc:
        exit_error(str(exc), as_json)

    references: tuple[SourceReference, ...] = ()
    if references_path is not None:
        try:
            resolved_references_path = resolve_references_path(root, references_path)
        except CapturePlanError as exc:
            exit_error(str(exc), as_json)
        try:
            payload = load_strict_json(resolved_references_path)
        except ArtifactContractError as exc:
            exit_error(
                f"cannot read {redact_diagnostic_text(str(references_path))}: {exc}", as_json
            )
        try:
            references = decode_capture_references(payload)
        except CaptureReferenceDecodeError as exc:
            exit_error(str(exc), as_json)

    try:
        overrides = parse_built_url_overrides(built_url_specs)
    except CapturePlanError as exc:
        exit_error(str(exc), as_json)

    try:
        plan = build_capture_cli_plan(
            root,
            manifest,
            document,
            requested_page_ids=page_ids,
            built_url_overrides=overrides,
            references=references,
        )
    except CapturePlanError as exc:
        exit_error(str(exc), as_json)

    if dry_run:
        _emit_dry_run(manifest, plan, as_json)
        return

    _run_capture(root, document, manifest, plan, references, as_json)


def _emit_dry_run(manifest: ProjectManifest, plan: CaptureCliPlan, as_json: bool) -> None:
    payload = render_dry_run_preview(manifest, plan)
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(f"Capture plan for {payload['project_id']} (dry run; no capture performed):")
    for page in payload["pages"]:
        click.echo(f"- {page['page_id']} (DNN page {page['dnn_page_id']}) -> {page['built_url']}")
        for breakpoint in page["breakpoints"]:
            click.echo(f"    {breakpoint['breakpoint']}: {breakpoint['status']}")
            for diagnostic in breakpoint["diagnostics"]:
                click.echo(f"      - {diagnostic}")
    for diagnostic in payload["diagnostics"]:
        click.echo(f"warning: {diagnostic}")


def _run_capture(
    root: Path,
    document: DesignDocument,
    manifest: ProjectManifest,
    plan: CaptureCliPlan,
    references: Sequence[SourceReference],
    as_json: bool,
) -> None:
    session = PlaywrightCaptureSession()
    page_results: list[dict[str, Any]] = []
    for route in plan.routes:
        try:
            result = _collect_page_capture(
                root,
                document,
                manifest,
                page_id=route.page_id,
                built_url=route.built_url,
                capture_session=session,
                references=references,
                target_verifier=verify_project_portal,
            )
        except Exception as exc:  # noqa: BLE001 - collector integration boundary: recorded
            # as an explicit page failure below, never silently upgraded to a
            # success. See notes.md for the documented integration assumption.
            result = {
                "status": "error",
                "page_id": route.page_id,
                "message": redact_diagnostic_text(str(exc)),
            }
        page_results.append(
            {
                "page_id": route.page_id,
                "dnn_page_id": route.dnn_page_id,
                "built_url": redact_diagnostic_text(route.built_url),
                "built_url_source": route.built_url_source,
                "result": result,
            }
        )

    summary = summarize_capture_results(page_results)
    payload = {
        "status": summary["status"],
        "project_id": manifest.project.id,
        "dry_run": False,
        "captured": summary["captured"],
        "total": summary["total"],
        "pages": page_results,
    }

    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
    else:
        click.echo(
            f"Project capture for {manifest.project.id}: "
            f"{summary['captured']}/{summary['total']} page(s) captured."
        )
        for entry in page_results:
            state = describe_page_capture_result(entry["result"])
            click.echo(f"- {entry['page_id']} (DNN page {entry['dnn_page_id']}): {state}")

    if summary["status"] != "ok":
        raise SystemExit(1)
