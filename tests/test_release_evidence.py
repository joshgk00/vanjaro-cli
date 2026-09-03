"""Focused operator evidence tooling tests."""

from __future__ import annotations

import json
from pathlib import Path
import hashlib

from click.testing import CliRunner
import pytest
from pydantic import ValidationError

from vanjaro_cli.commands.release_cmd import release
from vanjaro_cli.release.models import (
    LiveAttestationReceipt,
    LiveEvidenceReceipt,
    ProjectEffortEvidence,
    ProjectQualityEvidence,
    ProjectReleaseReceipt,
)
from vanjaro_cli.release.scaffolding import project_evidence_templates
from vanjaro_cli.release.test_evidence import (
    PytestRunObservation,
    run_governed_tests,
    sanitized_test_environment,
)
from vanjaro_cli.release.verifier import _run_current_tests
from vanjaro_cli.reliability import canonical_json_bytes


TEMPLATE_NAMES = (
    "quality-counts.template.json",
    "effort-sessions.template.json",
    "project-receipt-bindings.template.json",
    "live-receipt.template.json",
    "live-attestation.template.json",
)


def _scaffold_args(root: Path, *, write: bool = False, overwrite: bool = False) -> list[str]:
    args = [
        "scaffold-project-evidence",
        "--candidate-id", "rc-1",
        "--project-id", "p1",
        "--source-kind", "image",
        "--workspace", "workspace",
        "--output-dir", "evidence",
        "--repository-root", str(root),
        "--json",
    ]
    if write:
        args.append("--write")
    if overwrite:
        args.append("--overwrite")
    return args


def _seed_originals(output: Path, prior_state: str) -> dict[str, bytes]:
    selected = {
        "none": (),
        "partial": TEMPLATE_NAMES[:2],
        "all": TEMPLATE_NAMES,
    }[prior_state]
    if selected:
        output.mkdir()
    before: dict[str, bytes] = {}
    for index, name in enumerate(selected):
        content = f"original-{index}\n".encode()
        (output / name).write_bytes(content)
        before[name] = content
    return before


def _assert_prior_state(output: Path, before: dict[str, bytes]) -> None:
    if not before:
        assert not output.exists()
        return
    actual = {path.name: path.read_bytes() for path in output.iterdir()}
    assert actual == before


def _canonical_templates() -> dict[str, bytes]:
    templates = project_evidence_templates(
        candidate_id="rc-1",
        project_id="p1",
        source_kind="image",
        workspace="workspace",
    )
    return {
        name: canonical_json_bytes(template)
        for name, template in templates.items()
    }


def _policy(root: Path) -> Path:
    (root / "tests").mkdir()
    (root / "tests" / "test_sample.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    path = root / "release" / "test-policy.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "schema_version": "agency-test-policy-v1",
        "command": "python -m pytest -m not integration -q",
        "allowed_deselected": 0,
        "source_globs": ["tests/test_*.py"],
        "required_controls": {
            "structured_diagnostics": ["tests/test_sample.py::test_ok"],
            "recovery_tests": ["tests/test_sample.py::test_ok"],
            "contract_migrations": ["tests/test_sample.py::test_ok"],
            "import_boundaries": ["tests/test_sample.py::test_ok"],
        },
    }), encoding="utf-8")
    return path


def test_capture_tests_preview_has_no_execution_or_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path)
    output = tmp_path / "evidence" / "receipt.json"
    monkeypatch.setattr(
        "vanjaro_cli.commands.release_cmd.run_governed_tests",
        lambda *_: pytest.fail("preview executed tests"),
    )
    result = CliRunner().invoke(release, [
        "capture-tests", str(policy.relative_to(tmp_path)), "--repository-root", str(tmp_path),
        "--output", str(output.relative_to(tmp_path)), "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "preview"
    assert payload["command"] == "python -m pytest -m not integration -q"
    assert payload["contract_fragment"]["test_evidence"]["receipt"]["sha256"] is None
    assert not output.exists()
    assert not output.parent.exists()


def test_capture_tests_execute_writes_reproducible_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path)
    output = tmp_path / "evidence" / "receipt.json"
    observation = PytestRunObservation(
        1, 1, 0, 0, 0, ("tests/test_sample.py::test_ok",)
    )
    monkeypatch.setattr(
        "vanjaro_cli.commands.release_cmd.run_governed_tests",
        lambda *_: observation,
    )
    args = ["capture-tests", "release/test-policy.json", "--repository-root", str(tmp_path),
            "--output", "evidence/receipt.json", "--execute-tests", "--json"]
    first = CliRunner().invoke(release, args)
    assert first.exit_code == 0, first.output
    original = output.read_bytes()
    second = CliRunner().invoke(release, args)
    assert second.exit_code == 0, second.output
    assert output.read_bytes() == original
    payload = json.loads(second.output)
    assert payload["contract_fragment"]["test_evidence"]["receipt"]["sha256"] == (
        hashlib.sha256(output.read_bytes()).hexdigest()
    )
    assert len(payload["contract_fragment"]["test_evidence"]["source_files"]) == 1


def test_scaffold_project_evidence_is_preview_first(tmp_path: Path) -> None:
    (tmp_path / "workspace").mkdir()
    args = _scaffold_args(tmp_path)
    preview = CliRunner().invoke(release, args)
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["mode"] == "preview"
    assert not (tmp_path / "evidence").exists()
    written = CliRunner().invoke(release, [*args, "--write"])
    assert written.exit_code == 0, written.output
    payload = json.loads(written.output)
    assert payload["warnings"] == []
    templates = _canonical_templates()
    output = tmp_path / "evidence"
    assert {path.name for path in output.iterdir()} == set(TEMPLATE_NAMES)
    for name, payload_bytes in templates.items():
        assert (output / name).read_bytes() == payload_bytes
    assert not tuple(tmp_path.glob(".evidence.scaffold-*"))
    refused = CliRunner().invoke(release, [*args, "--write"])
    assert refused.exit_code != 0
    assert "--overwrite" in refused.output
    for name in TEMPLATE_NAMES:
        (output / name).write_bytes(b"old\n")
    overwritten = CliRunner().invoke(release, [*args, "--write", "--overwrite"])
    assert overwritten.exit_code == 0, overwritten.output
    for name, payload_bytes in templates.items():
        assert (output / name).read_bytes() == payload_bytes
    assert not tuple(tmp_path.glob(".evidence.scaffold-*"))


@pytest.mark.parametrize("failure_position", range(1, 6))
@pytest.mark.parametrize("prior_state", ("none", "partial", "all"))
def test_scaffold_transaction_restores_entire_set_after_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_position: int,
    prior_state: str,
) -> None:
    (tmp_path / "workspace").mkdir()
    output = tmp_path / "evidence"
    before = _seed_originals(output, prior_state)

    import vanjaro_cli.release.scaffolding as scaffolding

    real_replace = scaffolding._replace_path
    calls = 0

    def fail_once(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == failure_position:
            raise OSError("injected commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(scaffolding, "_replace_path", fail_once)
    args = _scaffold_args(tmp_path, write=True, overwrite=bool(before))
    result = CliRunner().invoke(release, args)

    assert result.exit_code != 0
    assert "prior worksheet set was restored" in result.output
    _assert_prior_state(output, before)
    assert not tuple(tmp_path.glob(".evidence.scaffold-*"))


@pytest.mark.parametrize("failure_position", range(1, 6))
@pytest.mark.parametrize("prior_state", ("none", "partial", "all"))
def test_scaffold_transaction_never_mutates_destinations_after_staging_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_position: int,
    prior_state: str,
) -> None:
    (tmp_path / "workspace").mkdir()
    output = tmp_path / "evidence"
    before = _seed_originals(output, prior_state)

    import vanjaro_cli.release.scaffolding as scaffolding

    real_write = scaffolding._write_staged_file
    calls = 0

    def fail_once(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == failure_position:
            raise OSError("injected staging failure")
        real_write(path, payload)

    monkeypatch.setattr(scaffolding, "_write_staged_file", fail_once)
    args = _scaffold_args(tmp_path, write=True, overwrite=bool(before))
    result = CliRunner().invoke(release, args)

    assert result.exit_code != 0
    assert "prior worksheet set was restored" in result.output
    _assert_prior_state(output, before)
    assert not tuple(tmp_path.glob(".evidence.scaffold-*"))


BACKUP_FAILURES = (
    *(("partial", position) for position in range(1, 3)),
    *(("all", position) for position in range(1, 6)),
)


@pytest.mark.parametrize(("prior_state", "failure_position"), BACKUP_FAILURES)
def test_scaffold_transaction_preserves_originals_after_backup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
    failure_position: int,
) -> None:
    (tmp_path / "workspace").mkdir()
    output = tmp_path / "evidence"
    before = _seed_originals(output, prior_state)

    import vanjaro_cli.release.scaffolding as scaffolding

    real_copy = scaffolding._copy_backup
    calls = 0

    def fail_once(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == failure_position:
            raise OSError("injected backup failure")
        real_copy(source, destination)

    monkeypatch.setattr(scaffolding, "_copy_backup", fail_once)
    result = CliRunner().invoke(
        release, _scaffold_args(tmp_path, write=True, overwrite=True)
    )

    assert result.exit_code != 0
    assert "prior worksheet set was restored" in result.output
    _assert_prior_state(output, before)
    assert not tuple(tmp_path.glob(".evidence.scaffold-*"))


@pytest.mark.parametrize(
    ("failing_helper", "prior_state"),
    (
        ("_create_backup_directory", "partial"),
        ("_create_backup_directory", "all"),
        ("_create_output_directory", "none"),
        ("_create_output_directory", "partial"),
        ("_create_output_directory", "all"),
    ),
)
def test_scaffold_transaction_cleans_staging_after_directory_setup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_helper: str,
    prior_state: str,
) -> None:
    (tmp_path / "workspace").mkdir()
    output = tmp_path / "evidence"
    before = _seed_originals(output, prior_state)

    def fail(_path: Path) -> None:
        raise OSError("injected directory setup failure")

    monkeypatch.setattr(
        f"vanjaro_cli.release.scaffolding.{failing_helper}", fail
    )
    result = CliRunner().invoke(
        release,
        _scaffold_args(tmp_path, write=True, overwrite=bool(before)),
    )

    assert result.exit_code != 0
    assert "prior worksheet set was restored" in result.output
    _assert_prior_state(output, before)
    assert not tuple(tmp_path.glob(".evidence.scaffold-*"))


ROLLBACK_FAILURES = tuple(
    (commit_failure, rollback_failure)
    for commit_failure in range(2, 6)
    for rollback_failure in range(1, commit_failure)
)


@pytest.mark.parametrize(("commit_failure", "rollback_failure"), ROLLBACK_FAILURES)
def test_scaffold_transaction_preserves_recovery_backups_when_restore_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    commit_failure: int,
    rollback_failure: int,
) -> None:
    (tmp_path / "workspace").mkdir()
    output = tmp_path / "evidence"
    before = _seed_originals(output, "all")
    canonical = _canonical_templates()

    import vanjaro_cli.release.scaffolding as scaffolding

    real_replace = scaffolding._replace_path
    commit_calls = 0
    rollback_calls = 0

    def fail_commit_and_restore(source: Path, destination: Path) -> None:
        nonlocal commit_calls, rollback_calls
        if source.parent.name == "new":
            commit_calls += 1
            if commit_calls == commit_failure:
                raise OSError("injected commit failure")
        elif source.parent.name == "backups":
            rollback_calls += 1
            if rollback_calls == rollback_failure:
                raise OSError("injected restore failure")
        real_replace(source, destination)

    monkeypatch.setattr(scaffolding, "_replace_path", fail_commit_and_restore)
    result = CliRunner().invoke(
        release, _scaffold_args(tmp_path, write=True, overwrite=True)
    )

    assert result.exit_code != 0
    assert "rollback was incomplete" in result.output
    recovery = tuple(tmp_path.glob(".evidence.scaffold-*"))
    assert len(recovery) == 1
    failed_index = commit_failure - 1 - rollback_failure
    failed_name = TEMPLATE_NAMES[failed_index]
    expected_backup_names = {
        failed_name,
        *TEMPLATE_NAMES[commit_failure - 1 :],
    }
    backups = recovery[0] / "backups"
    assert {path.name for path in backups.iterdir()} == expected_backup_names
    for name in expected_backup_names:
        assert (backups / name).read_bytes() == before[name]
    staged = recovery[0] / "new"
    expected_staged_names = set(TEMPLATE_NAMES[commit_failure - 1 :])
    assert {path.name for path in staged.iterdir()} == expected_staged_names
    for name in expected_staged_names:
        assert (staged / name).read_bytes() == canonical[name]
    expected_output = {
        name: canonical[name] if name == failed_name else before[name]
        for name in TEMPLATE_NAMES
    }
    assert {path.name: path.read_bytes() for path in output.iterdir()} == expected_output


@pytest.mark.parametrize(("commit_failure", "rollback_failure"), ROLLBACK_FAILURES)
def test_scaffold_transaction_preserves_recovery_files_when_new_file_removal_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    commit_failure: int,
    rollback_failure: int,
) -> None:
    (tmp_path / "workspace").mkdir()
    canonical = _canonical_templates()

    import vanjaro_cli.release.scaffolding as scaffolding

    real_replace = scaffolding._replace_path
    real_remove = scaffolding._remove_destination
    commit_calls = 0
    rollback_calls = 0

    def fail_commit(source: Path, destination: Path) -> None:
        nonlocal commit_calls
        if source.parent.name == "new":
            commit_calls += 1
            if commit_calls == commit_failure:
                raise OSError("injected commit failure")
        real_replace(source, destination)

    def fail_removal(path: Path) -> None:
        nonlocal rollback_calls
        rollback_calls += 1
        if rollback_calls == rollback_failure:
            raise OSError("injected removal failure")
        real_remove(path)

    monkeypatch.setattr(scaffolding, "_replace_path", fail_commit)
    monkeypatch.setattr(scaffolding, "_remove_destination", fail_removal)
    result = CliRunner().invoke(release, _scaffold_args(tmp_path, write=True))

    assert result.exit_code != 0
    assert "rollback was incomplete" in result.output
    recovery = tuple(tmp_path.glob(".evidence.scaffold-*"))
    assert len(recovery) == 1
    failed_index = commit_failure - 1 - rollback_failure
    failed_name = TEMPLATE_NAMES[failed_index]
    output = tmp_path / "evidence"
    assert {path.name: path.read_bytes() for path in output.iterdir()} == {
        failed_name: canonical[failed_name]
    }
    assert not (recovery[0] / "backups").exists()
    staged = recovery[0] / "new"
    expected_staged_names = set(TEMPLATE_NAMES[commit_failure - 1 :])
    assert {path.name for path in staged.iterdir()} == expected_staged_names
    for name in expected_staged_names:
        assert (staged / name).read_bytes() == canonical[name]


def test_scaffold_transaction_reports_residual_directory_after_successful_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "workspace").mkdir()

    def fail_cleanup(_path: Path) -> None:
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(
        "vanjaro_cli.release.scaffolding._remove_staging", fail_cleanup
    )
    result = CliRunner().invoke(release, _scaffold_args(tmp_path, write=True))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["warnings"]) == 1
    assert "temporary cleanup failed" in payload["warnings"][0]
    assert "recovery files remain" in payload["warnings"][0]
    assert len(tuple(tmp_path.glob(".evidence.scaffold-*"))) == 1
    assert {path.name for path in (tmp_path / "evidence").iterdir()} == set(
        TEMPLATE_NAMES
    )


def test_scaffold_transaction_reports_incomplete_new_directory_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "workspace").mkdir()

    import vanjaro_cli.release.scaffolding as scaffolding

    real_replace = scaffolding._replace_path
    commit_calls = 0

    def fail_second_commit(source: Path, destination: Path) -> None:
        nonlocal commit_calls
        if source.parent.name == "new":
            commit_calls += 1
            if commit_calls == 2:
                raise OSError("injected commit failure")
        real_replace(source, destination)

    def fail_directory_removal(_path: Path) -> None:
        raise OSError("injected output directory removal failure")

    monkeypatch.setattr(scaffolding, "_replace_path", fail_second_commit)
    monkeypatch.setattr(
        scaffolding, "_remove_output_directory", fail_directory_removal
    )
    result = CliRunner().invoke(release, _scaffold_args(tmp_path, write=True))

    assert result.exit_code != 0
    assert "rollback was incomplete" in result.output
    assert (tmp_path / "evidence").is_dir()
    assert not tuple((tmp_path / "evidence").iterdir())
    assert len(tuple(tmp_path.glob(".evidence.scaffold-*"))) == 1


def test_scaffold_templates_cannot_validate_as_evidence(tmp_path: Path) -> None:
    (tmp_path / "workspace").mkdir()
    result = CliRunner().invoke(release, [
        "scaffold-project-evidence", "--candidate-id", "rc-1", "--project-id", "p1",
        "--source-kind", "live_html", "--workspace", "workspace", "--output-dir", "evidence",
        "--repository-root", str(tmp_path), "--write",
    ])
    assert result.exit_code == 0, result.output
    models = {
        "quality-counts.template.json": ProjectQualityEvidence,
        "effort-sessions.template.json": ProjectEffortEvidence,
        "project-receipt-bindings.template.json": ProjectReleaseReceipt,
        "live-receipt.template.json": LiveEvidenceReceipt,
        "live-attestation.template.json": LiveAttestationReceipt,
    }
    for name, model in models.items():
        with pytest.raises(ValidationError):
            model.model_validate(json.loads((tmp_path / "evidence" / name).read_text()))


def test_release_evidence_help_paths_environment_and_verifier_parity(tmp_path: Path) -> None:
    help_result = CliRunner().invoke(release, ["--help"])
    assert help_result.exit_code == 0
    assert "capture-tests" in help_result.output
    assert "scaffold-project-evidence" in help_result.output
    environment = sanitized_test_environment({
        "HOME": "/safe/home", "USERPROFILE": "C:/safe", "PATH": "/bin",
        "VANJARO_PASSWORD": "secret", "HTTPS_PROXY": "secret", "FIGMA_ACCESS_TOKEN": "secret",
        "OPENAI_API_KEY": "secret", "SOME_TOKEN": "secret",
    })
    assert environment["HOME"] == "/safe/home"
    assert environment["USERPROFILE"] == "C:/safe"
    forbidden_words = ("PASSWORD", "PROXY", "FIGMA", "OPENAI", "TOKEN")
    assert not any(
        word in key.upper() for key in environment for word in forbidden_words
    )
    assert sanitized_test_environment({}) == {"PYTHONDONTWRITEBYTECODE": "1"}
    assert _run_current_tests is run_governed_tests

    outside = tmp_path.parent / "outside-policy.json"
    outside.write_text("{}", encoding="utf-8")
    escaped = CliRunner().invoke(release, [
        "capture-tests", str(outside), "--repository-root", str(tmp_path),
        "--output", "receipt.json",
    ])
    assert escaped.exit_code != 0
    if hasattr(Path, "symlink_to"):
        link = tmp_path / "policy-link.json"
        try:
            link.symlink_to(outside)
        except OSError:
            return
        linked = CliRunner().invoke(release, [
            "capture-tests", "policy-link.json", "--repository-root", str(tmp_path),
            "--output", "receipt.json",
        ])
        assert linked.exit_code != 0
        assert "symlink" in linked.output
