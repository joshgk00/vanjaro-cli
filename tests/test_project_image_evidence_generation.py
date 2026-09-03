"""Audited project orchestration for automatic image evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport
from vanjaro_cli.evidence import (
    DetectedEvidenceBundle,
    ImageEvidenceGenerationResult,
    normalize_detected_evidence,
)
from vanjaro_cli.orchestration.project_image_evidence import (
    ProjectImageEvidenceError,
    generate_project_image_evidence,
    plan_project_image_evidence,
)
from vanjaro_cli.project import (
    ProjectSource,
    ProjectStage,
    StageEngine,
    StageInputs,
    StageResult,
    create_manifest,
    initialize_workspace,
    load_manifest,
    write_manifest,
)


NOW = datetime(2026, 7, 17, 15, 0, tzinfo=UTC)


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "image-project"
    sources = [
        ProjectSource(
            id="image-desktop",
            kind=SourceKind.IMAGE,
            reference="sources/desktop.png",
            page_reference="home",
            breakpoint=BreakpointName.DESKTOP,
            viewport=Viewport(width=1440, height=900),
        ),
        ProjectSource(
            id="image-mobile",
            kind=SourceKind.IMAGE,
            reference="sources/mobile.png",
            page_reference="home",
            breakpoint=BreakpointName.MOBILE,
            viewport=Viewport(width=390, height=844),
        ),
    ]
    manifest = create_manifest(
        name="Image Project",
        project_id="image-project",
        target_profile="image-project",
        sources=sources,
        agency_pack_name="agency",
        agency_pack_version="1.0.0",
        clock=lambda: NOW,
    )
    initialize_workspace(root, manifest)
    (root / "sources" / "desktop.png").write_bytes(_png(640, 480))
    (root / "sources" / "mobile.png").write_bytes(_png(390, 700))
    return root


def _detection(source_ids: tuple[str, ...]) -> DetectedEvidenceBundle:
    return DetectedEvidenceBundle.model_validate(
        {
            "observations": [
                {
                    "source_id": source_id,
                    "page_title": "Generated Home",
                    "sections": [
                        {
                            "id": "hero",
                            "order": 0,
                            "semantic_role": "hero",
                            "role_confidence": 0.9,
                            "bounds": {
                                "x": 0,
                                "y": 0,
                                "width": 640 if "desktop" in source_id else 390,
                                "height": 480 if "desktop" in source_id else 700,
                            },
                            "layout": {
                                "kind": "stack",
                                "contained": True,
                                "columns": 1,
                                "media_position": None,
                                "alignment": "center",
                                "full_bleed": False,
                                "direction": "vertical",
                                "wrap": False,
                            },
                            "styles": [],
                            "hidden": False,
                        }
                    ],
                    "elements": [],
                    "groups": [],
                    "assets": [],
                    "colors": [],
                    "spacing": [],
                    "typography": [],
                    "warnings": [],
                }
                for source_id in source_ids
            ]
        }
    )


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        evidence = normalize_detected_evidence(
            request,
            _detection(tuple(item.source_id for item in request.images)),
            producer_name="fake-vision",
            producer_version="1.0",
            model="fake-model",
            prompt_version="fake-prompt",
            metadata={"provider": "fake"},
        )
        return ImageEvidenceGenerationResult(
            evidence=evidence,
            provider="fake-vision",
            model="fake-model",
            response_id=f"response-{len(self.calls)}",
            request_fingerprint=str(len(self.calls)) * 64,
        )


def test_plan_is_local_read_only_and_generation_groups_breakpoints(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    plan = plan_project_image_evidence(root)

    assert [item.action for item in plan.items] == ["generate", "generate"]
    assert not list((root / "sources").glob("*.evidence.json"))
    provider = FakeProvider()
    result = generate_project_image_evidence(
        root,
        provider,
        generated_by="Josh",
        clock=lambda: NOW,
    )

    assert len(provider.calls) == 1
    assert {item.source_id for item in provider.calls[0].images} == {
        "image-desktop",
        "image-mobile",
    }
    assert result.generated_sources == ("image-desktop", "image-mobile")
    manifest = load_manifest(root)
    assert [source.evidence_reference for source in manifest.sources] == [
        "sources/image-desktop.evidence.json",
        "sources/image-mobile.evidence.json",
    ]
    for source in manifest.sources:
        sidecar = root / source.evidence_reference
        assert sidecar.is_file()
        payload = sidecar.read_text(encoding="utf-8")
        assert payload.count('"source_sha256"') == 1
        assert "fake-model" in payload
    assert manifest.audit[-1].kind == "image_evidence_generated"
    assert "OPENAI" not in manifest.model_dump_json()
    assert not (root / ".image-evidence.lock").exists()


def test_existing_valid_sidecars_skip_without_provider_or_manifest_write(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    first = FakeProvider()
    generate_project_image_evidence(
        root, first, generated_by="Josh", clock=lambda: NOW
    )
    before = (root / "project.json").read_bytes()
    provider = FakeProvider()

    result = generate_project_image_evidence(
        root, provider, generated_by="Josh", clock=lambda: NOW
    )

    assert provider.calls == []
    assert result.generated_sources == ()
    assert result.skipped_sources == ("image-desktop", "image-mobile")
    assert (root / "project.json").read_bytes() == before


def test_overwrite_snapshots_sidecars_and_invalidates_analysis(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    generate_project_image_evidence(
        root, FakeProvider(), generated_by="Josh", clock=lambda: NOW
    )

    def analysis(context):
        artifact = context.root / "analysis" / "design-document.json"
        artifact.write_text("analysis", encoding="utf-8")
        return StageResult(artifacts=("analysis/design-document.json",), message="analyzed")

    StageEngine(root, clock=lambda: NOW).execute(
        ProjectStage.ANALYZE,
        StageInputs(
            files=(
                Path("sources/desktop.png"),
                Path("sources/mobile.png"),
                Path("sources/image-desktop.evidence.json"),
                Path("sources/image-mobile.evidence.json"),
            )
        ),
        analysis,
    )
    assert load_manifest(root).stages[ProjectStage.ANALYZE].status.value == "completed"

    result = generate_project_image_evidence(
        root,
        FakeProvider(),
        overwrite=True,
        generated_by="Josh",
        clock=lambda: NOW,
    )

    assert len(list((root / "history" / "evidence").glob("*.json"))) == 2
    assert load_manifest(root).stages[ProjectStage.ANALYZE].status.value == "pending"
    assert "analyze" in result.invalidated_stages


def test_provider_failure_leaves_sidecars_and_manifest_untouched(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before = (root / "project.json").read_bytes()

    class FailedProvider:
        def generate(self, request):
            raise ValueError("synthetic provider failure")

    with pytest.raises(ProjectImageEvidenceError) as caught:
        generate_project_image_evidence(
            root,
            FailedProvider(),
            generated_by="Josh",
            clock=lambda: NOW,
        )

    assert caught.value.code == "image_evidence_provider_failed"
    assert (root / "project.json").read_bytes() == before
    assert not list((root / "sources").glob("*.evidence.json"))


def test_page_breakpoint_selection_and_output_paths_fail_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(ProjectImageEvidenceError) as partial:
        plan_project_image_evidence(root, source_ids=("image-desktop",))
    assert partial.value.code == "image_evidence_incomplete_page_selection"

    manifest = load_manifest(root).model_copy(deep=True)
    manifest.sources = [
        source.model_copy(update={"evidence_reference": "sources/shared.evidence.json"})
        for source in manifest.sources
    ]
    write_manifest(root, manifest)
    with pytest.raises(ProjectImageEvidenceError) as collision:
        plan_project_image_evidence(root)
    assert collision.value.code == "image_evidence_output_collision"


def test_manifest_write_failure_restores_sidecars_and_removes_temporary_history(
    tmp_path: Path, monkeypatch
) -> None:
    root = _workspace(tmp_path)
    generate_project_image_evidence(
        root, FakeProvider(), generated_by="Josh", clock=lambda: NOW
    )
    before = {
        path.name: path.read_bytes()
        for path in (root / "sources").glob("*.evidence.json")
    }

    def fail_write(*args, **kwargs):
        raise OSError("synthetic manifest failure")

    monkeypatch.setattr(
        "vanjaro_cli.orchestration.project_image_evidence.write_manifest",
        fail_write,
    )
    with pytest.raises(OSError, match="synthetic manifest failure"):
        generate_project_image_evidence(
            root,
            FakeProvider(),
            overwrite=True,
            generated_by="Josh",
            clock=lambda: NOW,
        )

    after = {
        path.name: path.read_bytes()
        for path in (root / "sources").glob("*.evidence.json")
    }
    assert after == before
    assert not list((root / "history" / "evidence").glob("*.json"))


def test_source_change_during_provider_call_prevents_adoption(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    class SourceChangingProvider(FakeProvider):
        def generate(self, request):
            result = super().generate(request)
            (root / "sources" / "mobile.png").write_bytes(_png(391, 700))
            return result

    with pytest.raises(ProjectImageEvidenceError) as caught:
        generate_project_image_evidence(
            root,
            SourceChangingProvider(),
            generated_by="Josh",
            clock=lambda: NOW,
        )

    assert caught.value.code == "image_evidence_source_changed"
    assert not list((root / "sources").glob("*.evidence.json"))


def test_manifest_change_during_provider_call_prevents_adoption(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    class ManifestChangingProvider(FakeProvider):
        def generate(self, request):
            result = super().generate(request)
            manifest = load_manifest(root).model_copy(deep=True)
            manifest.project = manifest.project.model_copy(
                update={"name": "Concurrent Edit"}
            )
            write_manifest(root, manifest)
            return result

    with pytest.raises(ProjectImageEvidenceError) as caught:
        generate_project_image_evidence(
            root,
            ManifestChangingProvider(),
            generated_by="Josh",
            clock=lambda: NOW,
        )

    assert caught.value.code == "image_evidence_project_changed"
    assert load_manifest(root).project.name == "Concurrent Edit"
    assert not list((root / "sources").glob("*.evidence.json"))


@pytest.mark.parametrize("mutation", ["duplicate", "unexpected", "identity"])
def test_provider_result_ownership_and_identity_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    root = _workspace(tmp_path)

    class InvalidProvider(FakeProvider):
        def generate(self, request):
            result = super().generate(request)
            observation = result.evidence.observations[0]
            if mutation == "duplicate":
                result.evidence.observations.append(observation.model_copy(deep=True))
            elif mutation == "unexpected":
                result.evidence.observations[0] = observation.model_copy(
                    update={
                        "metadata": {
                            **observation.metadata,
                            "provider_source_id": "not-requested",
                        }
                    }
                )
            else:
                result.evidence.observations[0] = observation.model_copy(
                    update={"source_sha256": "f" * 64}
                )
            return result

    with pytest.raises(ProjectImageEvidenceError) as caught:
        generate_project_image_evidence(
            root,
            InvalidProvider(),
            generated_by="Josh",
            clock=lambda: NOW,
        )

    expected = (
        "image_evidence_provider_identity"
        if mutation == "identity"
        else "image_evidence_provider_ownership"
    )
    assert caught.value.code == expected
    assert not list((root / "sources").glob("*.evidence.json"))


def test_request_size_limit_fails_before_provider_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr(
        "vanjaro_cli.orchestration.image_evidence_validation.MAX_EVIDENCE_IMAGE_BYTES",
        16,
    )

    with pytest.raises(ProjectImageEvidenceError) as caught:
        plan_project_image_evidence(root)

    assert caught.value.code == "image_evidence_image_too_large"


def test_concurrent_adoption_lock_fails_without_writes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    lock = root / ".image-evidence.lock"
    lock.write_text("pid=other\n", encoding="ascii")

    with pytest.raises(ProjectImageEvidenceError) as caught:
        generate_project_image_evidence(
            root,
            FakeProvider(),
            generated_by="Josh",
            clock=lambda: NOW,
        )

    assert caught.value.code == "image_evidence_project_locked"
    assert lock.read_text(encoding="ascii") == "pid=other\n"
    assert not list((root / "sources").glob("*.evidence.json"))
