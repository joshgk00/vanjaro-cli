"""Contracts for deterministic agency editor handoff artifacts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from vanjaro_cli.commands.project_cmd import project
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.orchestration.project_handoff import (
    HANDOFF_PATH,
    SCORECARD_PATH,
    ProjectHandoffError,
    generate_project_handoff,
)
from vanjaro_cli.project import (
    ProjectSource,
    ProjectStage,
    StageRecord,
    StageStatus,
    create_manifest,
    fingerprint_files,
    initialize_workspace,
    load_manifest,
    write_manifest,
)


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _complete_stage(
    root: Path,
    manifest,
    stage: ProjectStage,
    artifacts: tuple[Path, ...],
    minute: int,
) -> None:
    manifest.stages[stage] = StageRecord(
        stage=stage,
        status=StageStatus.COMPLETED,
        attempt=1,
        input_fingerprint=hashlib.sha256(stage.value.encode("utf-8")).hexdigest(),
        output_fingerprint=fingerprint_files(root, artifacts),
        started_at=NOW + timedelta(minutes=minute - 1),
        completed_at=NOW + timedelta(minutes=minute),
        artifacts=[path.as_posix() for path in artifacts],
        message=f"Completed {stage.value}.",
    )


def _refresh_stage_fingerprint(root: Path, stage: ProjectStage) -> None:
    manifest = load_manifest(root)
    record = manifest.stages[stage]
    record.output_fingerprint = fingerprint_files(
        root, tuple(Path(path) for path in record.artifacts)
    )
    write_manifest(root, manifest)


def _workspace(
    tmp_path: Path,
    *,
    ready: bool = True,
    warning: str | None = None,
) -> Path:
    root = tmp_path / ("ready" if ready else "review")
    manifest = create_manifest(
        name="Agency Handoff",
        project_id="agency-handoff",
        target_profile="client-one",
        expected_portal_id=7,
        expected_base_url="https://vanjaro.example/client-one",
        sources=[
            ProjectSource(
                id="live-home",
                kind=SourceKind.LIVE_HTML,
                reference="https://source.example/",
            )
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="2.0.0",
        clock=lambda: NOW,
    )
    initialize_workspace(root, manifest)

    _write(
        root / "plans/validation.json",
        {
            "schema_version": "1.0",
            "valid": ready,
            "issues": [] if ready else ["Resolve the unmatched contact section."],
            "content_loss_count": 0 if ready else 1,
            "content_losses": {} if ready else {"home.contact": ["form_field"]},
            "editable_content_coverage": 0.94 if ready else 0.72,
            "native_component_ratio": 0.97,
        },
    )
    _write(
        root / "verify/draft-verification.json",
        {
            "schema_version": "1.1",
            "valid": ready,
            "target": {
                "profile": "client-one",
                "portal_id": 7,
                "base_url": "https://vanjaro.example/client-one",
            },
            "source_text_coverage": 0.98 if ready else 0.91,
            "missing_action_url_count": 0 if ready else 1,
            "blocker_count": 0 if ready else 1,
            "blockers": [] if ready else ["Contact action has no destination."],
            "warnings": [warning] if warning else [],
            "visual_fidelity": {"passed": ready, "overall_score": 91.0 if ready else 70.0},
        },
    )
    _write(
        root / "build/asset-manifest.json",
        {
            "schema_version": "1.0",
            "assets": [
                {
                    "asset_id": "logo",
                    "portal_url": "/Portals/7/logo.svg",
                    "status": "reused",
                }
            ],
        },
    )
    _write(
        root / "build/block-manifest.json",
        {
            "schema_version": "1.0",
            "blocks": [
                {
                    "name": "agency-handoff / Home Hero",
                    "category": "Agency - agency-handoff",
                    "type": "custom",
                    "status": "created",
                }
            ],
        },
    )
    _write(
        root / "build/global-page-manifest.json",
        {
            "schema_version": "1.0",
            "pages": [
                {
                    "page_id": 101,
                    "title": "[Agency Draft] Home",
                    "path": "/agency-handoff-home",
                    "published": False,
                    "status": "created",
                }
            ],
        },
    )
    _write(
        root / "build/global-block-manifest.json",
        {
            "schema_version": "1.0",
            "blocks": [
                {
                    "kind": "header",
                    "name": "agency-handoff / Site Header",
                    "published": False,
                    "status": "created",
                },
                {
                    "kind": "footer",
                    "name": "agency-handoff / Site Footer",
                    "published": False,
                    "status": "created",
                },
            ],
        },
    )
    _complete_stage(
        root, manifest, ProjectStage.PLAN, (Path("plans/validation.json"),), 1
    )
    _complete_stage(
        root, manifest, ProjectStage.ASSETS, (Path("build/asset-manifest.json"),), 2
    )
    _complete_stage(
        root, manifest, ProjectStage.LIBRARY, (Path("build/block-manifest.json"),), 3
    )
    _complete_stage(
        root,
        manifest,
        ProjectStage.GLOBAL_BLOCKS,
        (
            Path("build/global-page-manifest.json"),
            Path("build/global-block-manifest.json"),
        ),
        4,
    )
    _complete_stage(
        root,
        manifest,
        ProjectStage.VERIFY,
        (Path("verify/draft-verification.json"),),
        5,
    )
    manifest.project.updated_at = NOW + timedelta(minutes=5)
    write_manifest(root, manifest)
    return root


def test_publish_ready_handoff_is_deterministic_and_inventory_backed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    manifest_before = (root / "project.json").read_bytes()

    first = generate_project_handoff(root)
    scorecard_bytes = (root / SCORECARD_PATH).read_bytes()
    handoff_bytes = (root / HANDOFF_PATH).read_bytes()
    second = generate_project_handoff(root)

    assert first.status == second.status == "publish_ready"
    assert first.score == second.score == 100
    assert first.fingerprint == second.fingerprint
    assert (root / SCORECARD_PATH).read_bytes() == scorecard_bytes
    assert (root / HANDOFF_PATH).read_bytes() == handoff_bytes
    assert (root / "project.json").read_bytes() == manifest_before

    scorecard = json.loads(scorecard_bytes)
    assert scorecard["schema_version"] == "agency-maintenance-scorecard-v1"
    assert scorecard["generated_at"] == "2026-08-30T12:05:00Z"
    assert sum(check["weight"] for check in scorecard["checks"]) == 100
    assert scorecard["inventory"] == {
        "asset_count": 1,
        "assets": [{"asset_id": "logo", "status": "reused"}],
        "global_block_count": 2,
        "global_blocks": [
            {"kind": "footer", "name": "agency-handoff / Site Footer", "published": False, "status": "created"},
            {"kind": "header", "name": "agency-handoff / Site Header", "published": False, "status": "created"},
        ],
        "library_block_count": 1,
        "library_blocks": [{"category": "Agency - agency-handoff", "name": "agency-handoff / Home Hero", "status": "created", "type": "custom"}],
        "page_count": 1,
        "pages": [{"page_id": 101, "path": "/agency-handoff-home", "published": False, "status": "created", "title": "[Agency Draft] Home"}],
    }
    evidence = {item["path"]: item["sha256"] for item in scorecard["evidence"]}
    assert set(evidence) == {
        "project.json",
        "plans/validation.json",
        "verify/draft-verification.json",
        "build/asset-manifest.json",
        "build/block-manifest.json",
        "build/global-page-manifest.json",
        "build/global-block-manifest.json",
    }
    assert evidence["project.json"] == hashlib.sha256(manifest_before).hexdigest()
    assert "This handoff is read-only evidence. It does not publish" in handoff_bytes.decode()


def test_review_required_handoff_redacts_secret_text_and_does_not_use_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(
        tmp_path,
        ready=False,
        warning="Retry with Authorization: Bearer top.secret and api_key=abc123.",
    )

    def fail_network(*args, **kwargs):  # pragma: no cover - executes only on regression
        raise AssertionError("handoff must not use a network client")

    monkeypatch.setattr("requests.sessions.Session.request", fail_network)
    result = generate_project_handoff(root)
    text = (root / HANDOFF_PATH).read_text(encoding="utf-8")
    scorecard = json.loads((root / SCORECARD_PATH).read_text(encoding="utf-8"))

    assert result.status == "review_required"
    assert result.score < 100
    assert "top.secret" not in text
    assert "abc123" not in text
    assert "top.secret" not in json.dumps(scorecard)
    assert "abc123" not in json.dumps(scorecard)
    assert "Authorization=[REDACTED]" in text
    assert "api_key=[REDACTED]" in text
    assert {item["category"] for item in scorecard["open_items"]} == {
        "blocker",
        "content_loss",
        "plan",
        "warning",
    }


def test_handoff_redacts_identity_and_every_inventory_surface(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    secrets = {
        "project": "project-secret",
        "asset": "asset-secret",
        "library": "library-secret",
        "page": "page-secret",
        "global": "global-secret",
    }
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    project["project"]["name"] = f"api_key={secrets['project']}"
    _write(root / "project.json", project)

    asset_path = root / "build/asset-manifest.json"
    assets = json.loads(asset_path.read_text(encoding="utf-8"))
    assets["assets"][0]["status"] = f"password={secrets['asset']}"
    _write(asset_path, assets)
    _refresh_stage_fingerprint(root, ProjectStage.ASSETS)

    block_path = root / "build/block-manifest.json"
    blocks = json.loads(block_path.read_text(encoding="utf-8"))
    blocks["blocks"][0]["name"] = f"access_token={secrets['library']}"
    _write(block_path, blocks)
    _refresh_stage_fingerprint(root, ProjectStage.LIBRARY)

    page_path = root / "build/global-page-manifest.json"
    pages = json.loads(page_path.read_text(encoding="utf-8"))
    pages["pages"][0]["title"] = f"client_secret={secrets['page']}"
    _write(page_path, pages)

    global_path = root / "build/global-block-manifest.json"
    globals_ = json.loads(global_path.read_text(encoding="utf-8"))
    globals_["blocks"][0]["name"] = f"Authorization: Bearer {secrets['global']}"
    _write(global_path, globals_)
    _refresh_stage_fingerprint(root, ProjectStage.GLOBAL_BLOCKS)

    generate_project_handoff(root)
    combined = (root / SCORECARD_PATH).read_text(encoding="utf-8") + (
        root / HANDOFF_PATH
    ).read_text(encoding="utf-8")

    assert "[REDACTED]" in combined
    for secret in secrets.values():
        assert secret not in combined


@pytest.mark.parametrize("failure", ["incomplete", "missing", "malformed", "stale"])
def test_invalid_or_stale_evidence_fails_without_partial_outputs(
    tmp_path: Path, failure: str
) -> None:
    root = _workspace(tmp_path)
    if failure == "incomplete":
        payload = json.loads((root / "project.json").read_text(encoding="utf-8"))
        payload["stages"]["verify"] = {
            "stage": "verify",
            "status": "pending",
            "attempt": 0,
            "input_fingerprint": None,
            "output_fingerprint": None,
            "started_at": None,
            "completed_at": None,
            "artifacts": [],
            "message": None,
        }
        _write(root / "project.json", payload)
    elif failure == "missing":
        (root / "plans/validation.json").unlink()
    elif failure == "malformed":
        (root / "build/block-manifest.json").write_text("[]\n", encoding="utf-8")
        _refresh_stage_fingerprint(root, ProjectStage.LIBRARY)
    else:
        report = json.loads((root / "verify/draft-verification.json").read_text())
        report["warning_count"] = 1
        _write(root / "verify/draft-verification.json", report)

    with pytest.raises(ProjectHandoffError):
        generate_project_handoff(root)

    assert not (root / SCORECARD_PATH).exists()
    assert not (root / HANDOFF_PATH).exists()


@pytest.mark.parametrize(
    ("relative", "stage"),
    [
        ("plans/validation.json", ProjectStage.PLAN),
        ("build/asset-manifest.json", ProjectStage.ASSETS),
        ("build/block-manifest.json", ProjectStage.LIBRARY),
        ("build/global-page-manifest.json", ProjectStage.GLOBAL_BLOCKS),
        ("build/global-block-manifest.json", ProjectStage.GLOBAL_BLOCKS),
    ],
)
def test_tampered_non_verify_evidence_fails_closed(
    tmp_path: Path, relative: str, stage: ProjectStage
) -> None:
    root = _workspace(tmp_path)
    evidence_path = root / relative
    evidence_path.write_bytes(evidence_path.read_bytes() + b" \n")

    with pytest.raises(ProjectHandoffError) as raised:
        generate_project_handoff(root)

    assert raised.value.code == "evidence_stale"
    assert stage.value in raised.value.message
    assert not (root / SCORECARD_PATH).exists()
    assert not (root / HANDOFF_PATH).exists()


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_metrics_are_rejected(
    tmp_path: Path, constant: str
) -> None:
    root = _workspace(tmp_path)
    validation_path = root / "plans/validation.json"
    text = validation_path.read_text(encoding="utf-8")
    validation_path.write_text(
        text.replace('"editable_content_coverage": 0.94', f'"editable_content_coverage": {constant}'),
        encoding="utf-8",
        newline="\n",
    )
    _refresh_stage_fingerprint(root, ProjectStage.PLAN)

    with pytest.raises(ProjectHandoffError) as raised:
        generate_project_handoff(root)

    assert raised.value.code == "evidence_invalid"
    assert not (root / SCORECARD_PATH).exists()
    assert not (root / HANDOFF_PATH).exists()


@pytest.mark.parametrize(
    ("relative", "stage", "key", "value", "check_id"),
    [
        ("plans/validation.json", ProjectStage.PLAN, "editable_content_coverage", 1.1, "editable_coverage"),
        ("plans/validation.json", ProjectStage.PLAN, "native_component_ratio", -0.1, "native_components"),
        ("plans/validation.json", ProjectStage.PLAN, "content_loss_count", -1, "content_loss"),
        ("verify/draft-verification.json", ProjectStage.VERIFY, "blocker_count", -1, "verification"),
    ],
)
def test_out_of_domain_metrics_fail_closed_as_unavailable(
    tmp_path: Path,
    relative: str,
    stage: ProjectStage,
    key: str,
    value: object,
    check_id: str,
) -> None:
    root = _workspace(tmp_path)
    evidence_path = root / relative
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload[key] = value
    _write(evidence_path, payload)
    _refresh_stage_fingerprint(root, stage)

    result = generate_project_handoff(root)
    scorecard = json.loads((root / SCORECARD_PATH).read_text(encoding="utf-8"))
    check = next(item for item in scorecard["checks"] if item["id"] == check_id)

    assert result.status == "review_required"
    assert check["status"] == "unavailable"
    assert "NaN" not in (root / SCORECARD_PATH).read_text(encoding="utf-8")
    assert "Infinity" not in (root / SCORECARD_PATH).read_text(encoding="utf-8")


def test_pair_write_failure_restores_prior_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    generate_project_handoff(root)
    scorecard_before = (root / SCORECARD_PATH).read_bytes()
    handoff_before = (root / HANDOFF_PATH).read_bytes()
    original_replace = Path.replace
    injected = False

    def fail_second_install(source: Path, target: Path):
        nonlocal injected
        if (
            not injected
            and source.name == ".agency-handoff.md.handoff-tmp"
            and Path(target).name == "agency-handoff.md"
        ):
            injected = True
            raise OSError("injected second output failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second_install)
    with pytest.raises(ProjectHandoffError) as raised:
        generate_project_handoff(root)

    assert raised.value.code == "handoff_write_failed"
    assert (root / SCORECARD_PATH).read_bytes() == scorecard_before
    assert (root / HANDOFF_PATH).read_bytes() == handoff_before
    assert not list((root / "qa").glob(".*.handoff-*"))


@pytest.mark.parametrize(
    "backup_name",
    [
        ".maintenance-scorecard.json.handoff-backup",
        ".agency-handoff.md.handoff-backup",
    ],
)
def test_backup_cleanup_failure_keeps_the_complete_new_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backup_name: str
) -> None:
    root = _workspace(tmp_path)
    generate_project_handoff(root)
    report_path = root / "verify/draft-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["warnings"] = ["New reviewed warning."]
    _write(report_path, report)
    _refresh_stage_fingerprint(root, ProjectStage.VERIFY)
    original_unlink = Path.unlink
    injected = False

    def fail_backup_cleanup(path: Path, *args, **kwargs):
        nonlocal injected
        if not injected and path.name == backup_name:
            injected = True
            raise OSError("injected backup cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_backup_cleanup)
    with pytest.raises(ProjectHandoffError) as raised:
        generate_project_handoff(root)

    scorecard = json.loads((root / SCORECARD_PATH).read_text(encoding="utf-8"))
    markdown = (root / HANDOFF_PATH).read_text(encoding="utf-8")
    assert raised.value.code == "handoff_cleanup_required"
    assert scorecard["evidence"][2]["sha256"] == hashlib.sha256(
        report_path.read_bytes()
    ).hexdigest()
    assert "New reviewed warning." in markdown
    assert (root / "qa" / backup_name).exists()


def test_handoff_cli_reports_json_and_review_required_human_output(
    tmp_path: Path, runner
) -> None:
    ready = _workspace(tmp_path, ready=True)
    result = runner.invoke(project, ["handoff", str(ready), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "publish_ready"
    assert payload["score"] == 100
    assert payload["fingerprint"]
    assert payload["scorecard_path"].endswith("maintenance-scorecard.json")
    assert payload["handoff_path"].endswith("agency-handoff.md")

    review = _workspace(tmp_path, ready=False)
    result = runner.invoke(project, ["handoff", str(review)])
    assert result.exit_code == 0, result.output
    assert "Agency handoff: review_required" in result.output
    assert "not publish-ready" in result.output
