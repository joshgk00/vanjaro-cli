"""Contract tests for versioned agency project manifests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport
from vanjaro_cli.project import (
    AgencyPack,
    ApprovalGate,
    ApprovalRecord,
    ApprovalStatus,
    ProjectSource,
    ProjectStage,
    StageStatus,
    create_manifest,
)


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _source(source_id: str = "live-html-1") -> ProjectSource:
    return ProjectSource(
        id=source_id,
        kind=SourceKind.LIVE_HTML,
        reference="https://agency.example/",
    )


def test_agency_pack_digest_is_optional_and_validated() -> None:
    legacy = AgencyPack.model_validate({"name": "agency", "version": "1.0.0"})
    locked = AgencyPack(
        name="agency",
        version="1.1.0",
        digest="a" * 64,
    )

    assert legacy.digest is None
    assert locked.digest == "a" * 64

    with pytest.raises(ValidationError, match="digest"):
        AgencyPack(name="agency", version="1.1.0", digest="not-a-digest")


def test_manifest_initializes_complete_stage_graph_and_audited_intake() -> None:
    manifest = create_manifest(
        name="Agency Example",
        target_profile="agency-example",
        expected_portal_id=4,
        sources=[
            _source(),
            ProjectSource(
                id="figma-1",
                kind=SourceKind.FIGMA,
                reference="https://figma.com/design/example?node-id=1-2",
            ),
            ProjectSource(
                id="image-1",
                kind=SourceKind.IMAGE,
                reference="references/mobile.png",
                evidence_reference="references/mobile.evidence.json",
                page_reference="home",
                breakpoint=BreakpointName.MOBILE,
                viewport=Viewport(width=390, height=844),
            ),
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="1.0.0",
        clock=lambda: NOW,
    )

    assert manifest.project.id == "agency-example"
    assert manifest.target.profile == "agency-example"
    assert manifest.target.expected_portal_id == 4
    assert set(manifest.stages) == set(ProjectStage)
    intake = manifest.stages[ProjectStage.INTAKE]
    assert intake.status == StageStatus.COMPLETED
    assert intake.started_at == intake.completed_at == NOW
    assert len(intake.input_fingerprint or "") == 64
    assert intake.output_fingerprint == intake.input_fingerprint
    assert manifest.stages[ProjectStage.ANALYZE].status == StageStatus.PENDING
    assert manifest.audit[0].fingerprint == intake.output_fingerprint


@pytest.mark.parametrize(
    "metadata",
    [
        {"api_key": "sensitive"},
        {"credential": "sensitive"},
        {"nested": {"access-token": "sensitive"}},
        {"credentials": [{"password": "sensitive"}]},
        {"request_headers": {"value": "Bearer sensitive"}},
        {"source": "https://example.test/?api_key=sensitive"},
    ],
)
def test_source_metadata_rejects_secret_bearing_keys(metadata: dict) -> None:
    with pytest.raises(
        ValidationError,
        match="secret-bearing metadata key|authorization value|secret query parameter",
    ):
        ProjectSource(
            id="live-html-1",
            kind=SourceKind.LIVE_HTML,
            reference="https://agency.example/",
            metadata=metadata,
        )


def test_source_reference_rejects_secret_query_parameters() -> None:
    with pytest.raises(ValidationError, match="secret query parameter"):
        ProjectSource(
            id="figma-1",
            kind=SourceKind.FIGMA,
            reference="https://figma.example/file?access_token=do-not-store",
        )


def test_image_source_requires_explicit_viewport() -> None:
    with pytest.raises(ValidationError, match="explicit viewport"):
        ProjectSource(
            id="image-1",
            kind=SourceKind.IMAGE,
            reference="desktop.png",
            page_reference="home",
            breakpoint=BreakpointName.DESKTOP,
        )


def test_image_source_requires_explicit_page_and_breakpoint() -> None:
    with pytest.raises(ValidationError, match="page_reference, breakpoint"):
        ProjectSource(
            id="image-1",
            kind=SourceKind.IMAGE,
            reference="desktop.png",
            viewport=Viewport(width=1440, height=900),
        )


def test_non_image_source_rejects_image_evidence_reference() -> None:
    with pytest.raises(ValidationError, match="only valid for image"):
        ProjectSource(
            id="live-html-1",
            kind=SourceKind.LIVE_HTML,
            reference="https://agency.example/",
            evidence_reference="sources/evidence.json",
        )


def test_manifest_rejects_duplicate_source_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate source id"):
        create_manifest(
            name="Duplicate",
            target_profile="target",
            sources=[_source(), _source()],
            agency_pack_name="agency",
            agency_pack_version="1.0.0",
            clock=lambda: NOW,
        )


def test_approved_gate_is_bound_to_artifact_fingerprint() -> None:
    with pytest.raises(ValidationError, match="fingerprint"):
        ApprovalRecord(
            id="plan-approval-1",
            gate=ApprovalGate.PLAN,
            status=ApprovalStatus.APPROVED,
            requested_by="operator",
            requested_at=NOW,
            resolved_at=NOW,
            resolved_by="operator",
        )
