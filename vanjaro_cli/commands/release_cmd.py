"""Fail-closed release-readiness commands for agency operators and CI."""

from __future__ import annotations

from pathlib import Path
import re

import click

from vanjaro_cli.release import ReleaseVerificationError, verify_release
from vanjaro_cli.release.scaffolding import (
    project_evidence_templates,
    validate_scaffold_paths,
    write_scaffold_transaction,
)
from vanjaro_cli.release.test_evidence import (
    TestEvidenceError,
    build_test_receipt,
    contract_fragment,
    discover_test_source_files,
    load_test_policy,
    repository_path,
    repository_root as resolve_repository_root,
    run_governed_tests,
)
from vanjaro_cli.reliability import (
    ArtifactContractError,
    DiagnosticContext,
    atomic_write_json,
    build_diagnostic,
    canonical_json_bytes,
)


@click.group("release")
def release() -> None:
    """Audit local evidence for an agency release candidate."""


@release.command("verify")
@click.argument("contract", type=click.Path(path_type=Path))
@click.option(
    "--repository-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("."),
    show_default=True,
    help="Root used to resolve every evidence path; no path may escape it.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Write the canonical audit report to this path.",
)
@click.option(
    "--execute-tests",
    is_flag=True,
    help="Explicitly authorize execution of the governed repository pytest command.",
)
@click.option("--json", "as_json", is_flag=True, help="Output canonical JSON.")
def verify_release_command(
    contract: Path,
    repository_root: Path,
    output: Path | None,
    execute_tests: bool,
    as_json: bool,
) -> None:
    """Audit CONTRACT; repository test execution requires explicit opt-in."""

    try:
        report = verify_release(
            contract,
            repository_root=repository_root,
            execute_tests=execute_tests,
        )
        if output is not None:
            atomic_write_json(output, report)
    except (ReleaseVerificationError, ArtifactContractError) as exc:
        diagnostic = build_diagnostic(
            code="release.contract.invalid",
            category="contract",
            message=str(exc),
            recommended_action="Correct the local release contract and rerun the read-only audit.",
            stage="release-verify",
            context=DiagnosticContext(artifact_path=contract.name),
        )
        if as_json:
            click.echo(canonical_json_bytes(diagnostic).decode("utf-8"), nl=False)
            raise SystemExit(1)
        raise click.ClickException(diagnostic.diagnostic.message)

    if as_json:
        click.echo(canonical_json_bytes(report).decode("utf-8"), nl=False)
    else:
        click.echo(
            f"Release candidate {report.candidate_id}: {report.status}; "
            f"passed={report.summary.passed}, failed={report.summary.failed}, "
            f"incomplete={report.summary.incomplete}."
        )
        for gate in report.gates:
            if gate.status != "passed":
                click.echo(
                    f"- {gate.gate_id}: {gate.status} "
                    f"({', '.join(gate.reason_codes)})"
                )
        if output is not None:
            click.echo(f"Report: {output}")
    if report.status != "passed":
        raise SystemExit(1)


@release.command("capture-tests")
@click.argument("policy", type=click.Path(path_type=Path))
@click.option("--repository-root", type=click.Path(path_type=Path, file_okay=False),
              default=Path("."), show_default=True)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), required=True,
              help="Repository-local destination for the canonical test receipt.")
@click.option("--execute-tests", is_flag=True,
              help="Explicitly authorize the exact governed pytest command and receipt write.")
@click.option("--json", "as_json", is_flag=True, help="Output canonical JSON.")
def capture_tests_command(
    policy: Path, repository_root: Path, output: Path, execute_tests: bool, as_json: bool
) -> None:
    """Preview or explicitly execute governed tests from POLICY."""

    try:
        root = resolve_repository_root(repository_root)
        policy_path = repository_path(root, policy, label="test policy", must_exist=True)
        output_path = repository_path(root, output, label="test receipt output")
        governed_policy = load_test_policy(policy_path)
        source_files = discover_test_source_files(root, governed_policy.source_globs)
        receipt = None
        if execute_tests:
            receipt = build_test_receipt(
                governed_policy, run_governed_tests(root, governed_policy), source_files
            )
            atomic_write_json(output_path, receipt)
        fragment = contract_fragment(
            root=root, policy_path=policy_path, receipt_path=output_path,
            source_files=source_files, receipt=receipt,
        )
        result = {
            "mode": "executed" if execute_tests else "preview",
            "command": governed_policy.command,
            "output": output_path.relative_to(root).as_posix(),
            "contract_fragment": fragment,
            "contract_updated": False,
        }
    except (TestEvidenceError, ArtifactContractError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(canonical_json_bytes(result).decode("utf-8"), nl=False)
    else:
        click.echo(f"Mode: {result['mode']}")
        click.echo(f"Command: {result['command']}")
        click.echo(f"Output: {result['output']}")
        click.echo(canonical_json_bytes(fragment).decode("utf-8"), nl=False)
        click.echo("Release contract was not edited.")


@release.command("scaffold-project-evidence")
@click.option("--candidate-id", required=True)
@click.option("--project-id", required=True)
@click.option(
    "--source-kind",
    type=click.Choice(["live_html", "figma", "image"]),
    required=True,
)
@click.option("--workspace", type=click.Path(path_type=Path), required=True)
@click.option("--output-directory", "--output-dir", "output_dir",
              type=click.Path(path_type=Path, file_okay=False), required=True)
@click.option("--repository-root", type=click.Path(path_type=Path, file_okay=False),
              default=Path("."), show_default=True)
@click.option("--write", is_flag=True, help="Create the intentionally incomplete worksheets.")
@click.option(
    "--overwrite",
    is_flag=True,
    help="Replace existing worksheet files (requires --write).",
)
@click.option("--json", "as_json", is_flag=True, help="Output canonical JSON.")
def scaffold_project_evidence_command(
    candidate_id: str, project_id: str, source_kind: str, workspace: Path,
    output_dir: Path, repository_root: Path, write: bool, overwrite: bool, as_json: bool,
) -> None:
    """Preview or write incomplete operator evidence worksheets."""

    try:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", candidate_id):
            raise TestEvidenceError("candidate ID is invalid")
        if not project_id.strip():
            raise TestEvidenceError("project ID cannot be empty")
        if overwrite and not write:
            raise TestEvidenceError("--overwrite requires --write")
        root = resolve_repository_root(repository_root)
        safe_workspace, safe_output = validate_scaffold_paths(root, workspace, output_dir)
        templates = project_evidence_templates(
            candidate_id=candidate_id, project_id=project_id, source_kind=source_kind,
            workspace=safe_workspace.relative_to(root).as_posix(),
        )
        destinations = [safe_output / name for name in templates]
        for destination in destinations:
            repository_path(root, destination, label="worksheet output")
        warnings: list[str] = []
        if write:
            transaction = write_scaffold_transaction(
                safe_output, templates, overwrite=overwrite
            )
            if transaction.cleanup_warning:
                warnings.append(transaction.cleanup_warning)
        result = {
            "mode": "written" if write else "preview",
            "workspace": safe_workspace.relative_to(root).as_posix(),
            "output_directory": safe_output.relative_to(root).as_posix(),
            "files": [path.relative_to(root).as_posix() for path in destinations],
            "templates_are_valid_evidence": False,
            "portal_contacted": False,
            "contract_updated": False,
            "warnings": warnings,
        }
    except (TestEvidenceError, ArtifactContractError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(canonical_json_bytes(result).decode("utf-8"), nl=False)
    else:
        click.echo(f"Mode: {result['mode']}")
        for path in result["files"]:
            click.echo(f"- {path}")
        click.echo("Templates remain invalid until real operator observations are supplied.")
        click.echo("No portal was contacted and the release contract was not edited.")
        for warning in result["warnings"]:
            click.echo(f"Warning: {warning}", err=True)


__all__ = ["release"]
