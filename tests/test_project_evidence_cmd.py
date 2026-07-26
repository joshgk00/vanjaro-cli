"""CLI safety and recovery contracts for image evidence generation."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.cli import cli
from vanjaro_cli.evidence import (
    DetectedEvidenceBundle,
    ImageEvidenceGenerationResult,
    normalize_detected_evidence,
)
from vanjaro_cli.orchestration import generate_project_image_evidence


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def _project(runner, tmp_path: Path) -> Path:
    root = tmp_path / "evidence-cli"
    result = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Evidence CLI",
            "--target-profile",
            "evidence-cli",
            "--source",
            "image=sources/home.png",
            "--image-viewport",
            "1440x900",
            "--image-breakpoint",
            "image-1=desktop",
            "--source-page",
            "image-1=home",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    (root / "sources" / "home.png").write_bytes(_png(640, 480))
    return root


def test_project_evidence_dry_run_needs_no_api_key_and_writes_nothing(
    runner, tmp_path: Path, monkeypatch
) -> None:
    root = _project(runner, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = (root / "project.json").read_bytes()

    result = runner.invoke(
        cli,
        ["project", "evidence", "generate", str(root), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["generate_count"] == 1
    assert payload["items"][0]["action"] == "generate"
    assert (root / "project.json").read_bytes() == before
    assert not (root / "sources" / "image-1.evidence.json").exists()


def test_project_evidence_missing_key_has_structured_recovery(
    runner, tmp_path: Path, monkeypatch
) -> None:
    root = _project(runner, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        cli,
        ["project", "evidence", "generate", str(root), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["category"] == "openai_api_key_missing"
    assert "local .env" in payload["error"]["recommended_action"]
    assert not (root / "sources" / "image-1.evidence.json").exists()


def test_project_evidence_rejects_non_image_selection_before_credentials(
    runner, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "html-project"
    initialized = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "HTML Project",
            "--target-profile",
            "html-project",
            "--source",
            "html=https://example.test",
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        cli,
        [
            "project",
            "evidence",
            "generate",
            str(root),
            "--source",
            "live-html-1",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["category"] == "image_source_missing"


def test_all_valid_sidecars_skip_without_loading_provider_credentials(
    runner,
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(runner, tmp_path)

    class LocalProvider:
        def generate(self, request):
            detected = DetectedEvidenceBundle.model_validate(
                {
                    "observations": [
                        {
                            "source_id": "image-1",
                            "page_title": "Home",
                            "sections": [
                                {
                                    "id": "hero",
                                    "order": 0,
                                    "semantic_role": "hero",
                                    "role_confidence": 0.9,
                                    "bounds": {
                                        "x": 0,
                                        "y": 0,
                                        "width": 640,
                                        "height": 480,
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
                    ]
                }
            )
            evidence = normalize_detected_evidence(
                request,
                detected,
                producer_name="local-test",
                producer_version="1",
                model="local-test",
                prompt_version="local-test",
            )
            return ImageEvidenceGenerationResult(
                evidence=evidence,
                provider="local-test",
                model="local-test",
                response_id=None,
                request_fingerprint="a" * 64,
            )

    generate_project_image_evidence(
        root,
        LocalProvider(),
        generated_by="test",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def credentials_must_not_load(**kwargs):
        raise AssertionError("provider credentials were loaded for an all-skip plan")

    monkeypatch.setattr(
        "vanjaro_cli.commands.project_evidence_cmd.OpenAIImageEvidenceConfig.from_environment",
        credentials_must_not_load,
    )

    result = runner.invoke(
        cli,
        ["project", "evidence", "generate", str(root), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["generated_sources"] == []
    assert payload["skipped_sources"] == ["image-1"]
    assert payload["provider"] is None
