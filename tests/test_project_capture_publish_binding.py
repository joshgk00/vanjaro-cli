"""Capture records bind the completed publish they measured (RT-10).

Each test drives the real recorder or collector and reads the result back
through the real fidelity evaluator, so the binding launch enforces is the one
capture actually wrote.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_project_capture_collect import (
    TARGET_BASE_URL,
    _document,
    _FakeSession,
    _ok_verifier,
    _page,
    _prepare,
)
from tests.test_project_fidelity_recording import _manifest, _record
from vanjaro_cli.orchestration.project_capture_collect import collect_page_capture
from vanjaro_cli.orchestration.project_capture_evidence import CAPTURE_EVIDENCE_DIRECTORY
from vanjaro_cli.orchestration.project_fidelity import evaluate_project_fidelity
from vanjaro_cli.project.models import ProjectManifest, ProjectStage, StageStatus
from vanjaro_cli.project.publish_receipt import (
    PUBLISH_RESULT_PATH,
    completed_publish_receipt_fingerprint,
)
from vanjaro_cli.reliability.artifacts import atomic_write_json

PUBLISH_FINGERPRINT = "a" * 64
OLDER_PUBLISH_FINGERPRINT = "b" * 64


def _mark_published(
    root: Path, manifest: ProjectManifest, fingerprint: str = PUBLISH_FINGERPRINT
) -> None:
    manifest.stages[ProjectStage.PUBLISH].status = StageStatus.COMPLETED
    manifest.metadata["publish_review"] = {"fingerprint": fingerprint}
    atomic_write_json(root / PUBLISH_RESULT_PATH, {"receipt_fingerprint": fingerprint})


def _collect_home(root: Path, manifest: ProjectManifest, document) -> None:
    result = collect_page_capture(
        root,
        document,
        manifest,
        page_id="home",
        built_url=f"{TARGET_BASE_URL}/home",
        capture_session=_FakeSession(),
        target_verifier=_ok_verifier,
    )
    assert result["status"] == "captured"


def _v2_workspace(root: Path):
    document = _document((_page("home", source_reference="https://agency.example/home"),))
    return document, _prepare(root, document)


def _persisted_record_path(root: Path) -> Path:
    (path,) = (root / CAPTURE_EVIDENCE_DIRECTORY).glob("*.json")
    return path


def _persisted_record(root: Path) -> dict:
    return json.loads(_persisted_record_path(root).read_text(encoding="utf-8"))


def test_v1_capture_after_publish_binds_the_publish_fingerprint(tmp_path: Path) -> None:
    manifest = _manifest()
    _mark_published(tmp_path, manifest)

    _record(tmp_path, manifest=manifest)

    assert _persisted_record(tmp_path)["publish_receipt_fingerprint"] == PUBLISH_FINGERPRINT
    report, _ = evaluate_project_fidelity(tmp_path, manifest)
    assert report["pages"]["home"]["publish_receipt_fingerprint"] == PUBLISH_FINGERPRINT


def test_v1_capture_before_publish_records_no_binding(tmp_path: Path) -> None:
    manifest = _manifest()

    _record(tmp_path, manifest=manifest)

    assert _persisted_record(tmp_path)["publish_receipt_fingerprint"] is None
    report, _ = evaluate_project_fidelity(tmp_path, manifest)
    assert report["pages"]["home"]["publish_receipt_fingerprint"] is None


def test_v2_capture_after_publish_binds_the_publish_fingerprint(tmp_path: Path) -> None:
    document, manifest = _v2_workspace(tmp_path)
    _mark_published(tmp_path, manifest)

    _collect_home(tmp_path, manifest, document)

    assert _persisted_record(tmp_path)["publish_receipt_fingerprint"] == PUBLISH_FINGERPRINT
    report, _ = evaluate_project_fidelity(tmp_path, manifest)
    assert report["pages"]["home"]["publish_receipt_fingerprint"] == PUBLISH_FINGERPRINT


def test_v2_capture_before_publish_records_no_binding(tmp_path: Path) -> None:
    document, manifest = _v2_workspace(tmp_path)

    _collect_home(tmp_path, manifest, document)

    assert _persisted_record(tmp_path)["publish_receipt_fingerprint"] is None
    report, _ = evaluate_project_fidelity(tmp_path, manifest)
    assert report["pages"]["home"]["publish_receipt_fingerprint"] is None


def test_recapture_after_a_newer_publish_replaces_the_older_binding(tmp_path: Path) -> None:
    document, manifest = _v2_workspace(tmp_path)
    _mark_published(tmp_path, manifest, OLDER_PUBLISH_FINGERPRINT)
    _collect_home(tmp_path, manifest, document)

    _mark_published(tmp_path, manifest, PUBLISH_FINGERPRINT)
    _collect_home(tmp_path, manifest, document)

    assert _persisted_record(tmp_path)["publish_receipt_fingerprint"] == PUBLISH_FINGERPRINT


def test_a_record_written_before_this_field_existed_reads_as_unbound(tmp_path: Path) -> None:
    document, manifest = _v2_workspace(tmp_path)
    _mark_published(tmp_path, manifest)
    _collect_home(tmp_path, manifest, document)
    legacy = _persisted_record(tmp_path)
    del legacy["publish_receipt_fingerprint"]
    atomic_write_json(_persisted_record_path(tmp_path), legacy)

    report, blockers = evaluate_project_fidelity(tmp_path, manifest)

    assert blockers == []
    assert report["pages"]["home"]["publish_receipt_fingerprint"] is None


def test_completed_publish_fingerprint_needs_a_matching_result_and_completed_stage(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    assert completed_publish_receipt_fingerprint(tmp_path, manifest) is None

    _mark_published(tmp_path, manifest)
    assert completed_publish_receipt_fingerprint(tmp_path, manifest) == PUBLISH_FINGERPRINT

    atomic_write_json(
        tmp_path / PUBLISH_RESULT_PATH, {"receipt_fingerprint": OLDER_PUBLISH_FINGERPRINT}
    )
    assert completed_publish_receipt_fingerprint(tmp_path, manifest) is None

    _mark_published(tmp_path, manifest)
    manifest.stages[ProjectStage.PUBLISH].status = StageStatus.PENDING
    assert completed_publish_receipt_fingerprint(tmp_path, manifest) is None
