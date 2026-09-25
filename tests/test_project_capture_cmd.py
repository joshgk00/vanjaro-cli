"""CliRunner coverage for `vanjaro project capture`.

Every non-dry-run test injects a fake collector by patching
`vanjaro_cli.commands.project_capture_cmd._collect_page_capture` -- the real
`project_capture_collect.py` is owned by a concurrent workstream. These are
mock-collector tests, not a live capture run; the fake collector's results
are shaped to match the real collector's explicit status contract
(`captured`/`partial`/`failed`/`target_mismatch`/`page_not_found`, plus the
legacy `ok` status some tests still use), documented in the
operator-capture-command scratch notes and exercised end-to-end (real
collector, real planner) by the independent capture-collection checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import vanjaro_cli.commands.project_capture_cmd as project_capture_cmd
from vanjaro_cli.cli import cli
from vanjaro_cli.commands.project_cmd import project
from vanjaro_cli.design.capture_references import (
    CanvasInterpretation,
    StaticReference,
    StaticSourceKind,
)
from vanjaro_cli.design.capture_session import PlaywrightCaptureSession
from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.models import (
    BoundingBox,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    BreakpointName,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    SourceKind,
)
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.sources import ImageSourceAdapter, ImageSourceRequest, ReferenceImage
from vanjaro_cli.orchestration.project_capture_cli_plan import (
    CapturePlanError,
    decode_capture_references,
)
from vanjaro_cli.project import ProjectSource, create_manifest, initialize_workspace

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
CAPTURED_AT = NOW
BASE_URL = "http://portal.example/client"
PORTAL_ID = 3


# ---------------------------------------------------------------------------
# Fixture builders: a project workspace plus a resolved design document and a
# managed page manifest, written directly to disk without running the full
# analyze/plan pipeline (matching the pattern already used for other command
# tests such as test_project_quality_cmd.py).


def _page(
    page_id: str,
    *,
    source_reference: str,
    breakpoints: tuple[BreakpointName, ...] = (),
    metadata: dict | None = None,
    provenance: tuple[Provenance, ...] = (),
) -> Page:
    return Page(
        id=page_id,
        source_reference=source_reference,
        title=page_id.title(),
        slug=page_id,
        sections=[],
        breakpoints=list(breakpoints),
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=list(provenance),
        metadata=metadata or {},
    )


def _document(
    source_kind: SourceKind, pages: tuple[Page, ...], *, source_metadata: dict | None = None
) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=source_kind,
            identifier="fixture",
            captured_at=CAPTURED_AT,
            adapter_version="1.0.0",
            metadata=source_metadata or {},
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=list(pages),
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def _png_bytes(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes(5)
    )


def _workspace(
    tmp_path: Path,
    *,
    project_id: str,
    document: DesignDocument,
    managed_pages: list[dict[str, Any]],
    expected_base_url: str | None = BASE_URL,
    expected_portal_id: int | None = PORTAL_ID,
) -> Path:
    root = tmp_path / project_id
    manifest = create_manifest(
        name="Capture Command",
        project_id=project_id,
        target_profile="capture-profile",
        expected_portal_id=expected_portal_id,
        expected_base_url=expected_base_url,
        sources=[
            ProjectSource(
                id="live-home", kind=SourceKind.LIVE_HTML, reference="https://source.example/"
            )
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="1.0.0",
        clock=lambda: NOW,
    )
    initialize_workspace(root, manifest)

    design_path = root / "plans" / "resolved-design-document.json"
    design_path.parent.mkdir(parents=True, exist_ok=True)
    design_path.write_text(serialize_design_document(document), encoding="utf-8")

    manifest_path = root / "build" / "page-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"schema_version": "1.0", "pages": managed_pages}), encoding="utf-8"
    )
    return root


def _managed_page(key: str, *, page_id: int, path: str | None) -> dict[str, Any]:
    return {
        "key": key,
        "name": key,
        "title": key.title(),
        "page_id": page_id,
        "path": path,
        "parent_id": None,
        "desired_hash": "d" * 64,
        "observed_version": 1,
        "status": "created",
        "published": False,
        "visible": False,
    }


def _live_workspace(tmp_path: Path, *, project_id: str = "capture-cmd") -> Path:
    pages = (
        _page(
            "home",
            source_reference="https://source.example/",
            breakpoints=(BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE),
        ),
        _page(
            "about",
            source_reference="https://source.example/about",
            breakpoints=(BreakpointName.DESKTOP,),
        ),
    )
    document = _document(SourceKind.LIVE_HTML, pages)
    managed_pages = [
        _managed_page("home", page_id=101, path="/agency-home"),
        _managed_page("about", page_id=102, path="/agency-about"),
    ]
    return _workspace(
        tmp_path, project_id=project_id, document=document, managed_pages=managed_pages
    )


class _FakeCollector:
    def __init__(self, results: dict[str, Any] | None = None, *, raise_for: set[str] = frozenset()):
        self.calls: list[dict[str, Any]] = []
        self._results = results or {}
        self._raise_for = raise_for

    def __call__(self, root, document, manifest, **kwargs) -> dict[str, Any]:
        self.calls.append({"root": root, "document": document, "manifest": manifest, **kwargs})
        page_id = kwargs["page_id"]
        if page_id in self._raise_for:
            raise RuntimeError(f"collector exploded for {page_id}")
        return self._results.get(page_id, {"status": "ok", "page_id": page_id})


# ---------------------------------------------------------------------------
# Registration: the command is reachable from the top-level CLI at least once.


def test_capture_help_registers_on_top_level_cli() -> None:
    result = CliRunner().invoke(cli, ["project", "capture", "--help"])

    assert result.exit_code == 0, result.output
    assert "PAGE_ID=URL" in result.output
    assert "--dry-run" in result.output


# ---------------------------------------------------------------------------
# Dry-run preview: local-only, across live and image sources; page selection.


def test_dry_run_previews_live_source_pages_and_routes(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["target"] == {"base_url": BASE_URL, "portal_id": PORTAL_ID}
    pages = {entry["page_id"]: entry for entry in payload["pages"]}
    assert set(pages) == {"home", "about"}
    home = pages["home"]
    assert home["dnn_page_id"] == 101
    assert home["built_url"] == f"{BASE_URL}/agency-home"
    assert home["built_url_source"] == "managed_path"
    desktop = next(b for b in home["breakpoints"] if b["breakpoint"] == "desktop")
    assert desktop["status"] == "reference_valid"
    assert desktop["reference"] == {"kind": "live", "url": "https://source.example/"}
    assert desktop["is_canonical_viewport"] is True
    about = pages["about"]
    tablet = next(b for b in about["breakpoints"] if b["breakpoint"] == "tablet")
    assert tablet["status"] == "reference_not_declared"


def test_dry_run_previews_real_image_adapter_document(tmp_path: Path) -> None:
    """Uses the real `ImageSourceAdapter`, not a hand-built metadata shape."""

    relative_path = "sources/home-desktop.png"
    payload_bytes = _png_bytes(1440, 900)
    evidence = ImageEvidenceSet.model_validate(
        {
            "schema_version": "1.0",
            "producer": {"name": "capture-cmd-fixture", "version": "1.0"},
            "observations": [
                {
                    "source_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                    "captured_at": CAPTURED_AT.isoformat(),
                    "page_slug": "home",
                    "page_title": "Home",
                    "breakpoint": "desktop",
                    "viewport": {"width": 1440, "height": 900},
                    "image_width": 1440,
                    "image_height": 900,
                    "sections": [
                        {
                            "id": "hero",
                            "order": 0,
                            "semantic_role": "hero",
                            "role_confidence": 0.9,
                            "bounds": {"x": 0, "y": 0, "width": 1440, "height": 900},
                            "layout": {"kind": "stack", "contained": True},
                        }
                    ],
                }
            ],
        }
    )
    request = ImageSourceRequest(
        images=(
            ReferenceImage(
                path=Path(relative_path),
                page_slug="home",
                breakpoint=BreakpointName.DESKTOP,
                viewport_width=1440,
                viewport_height=900,
                sha256=hashlib.sha256(payload_bytes).hexdigest(),
            ),
        ),
        project_id="capture-cmd-image",
        evidence=evidence,
        captured_at=CAPTURED_AT,
    )
    document = ImageSourceAdapter().analyze(request)
    page_id = document.pages[0].id
    managed_pages = [_managed_page(page_id, page_id=201, path="/home")]
    root = _workspace(
        tmp_path,
        project_id="capture-cmd-image",
        document=document,
        managed_pages=managed_pages,
    )
    (root / relative_path).parent.mkdir(parents=True, exist_ok=True)
    (root / relative_path).write_bytes(payload_bytes)

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    page = payload["pages"][0]
    desktop = next(b for b in page["breakpoints"] if b["breakpoint"] == "desktop")
    assert desktop["status"] == "reference_valid"
    assert desktop["reference"]["kind"] == "static"
    assert desktop["reference"]["source_kind"] == "image"
    assert desktop["reference"]["local_path"] == relative_path
    assert desktop["reference"]["sha256"] == hashlib.sha256(payload_bytes).hexdigest()
    assert desktop["viewport"] == {"width": 1440, "height": 900}


def test_page_selection_filters_to_requested_ids(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)

    result = CliRunner().invoke(
        project, ["capture", str(root), "--page", "about", "--dry-run", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [entry["page_id"] for entry in payload["pages"]] == ["about"]


def test_unknown_page_selection_is_a_diagnostic_failure(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)

    result = CliRunner().invoke(
        project, ["capture", str(root), "--page", "does-not-exist", "--dry-run", "--json"]
    )

    assert result.exit_code != 0
    assert "unknown page id" in result.output


# ---------------------------------------------------------------------------
# --references decoding: strict, offline, and integrated into the preview.


def test_references_file_static_image_reference_shown_in_preview(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    payload_bytes = _png_bytes(1280, 800)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "about-desktop.png").write_bytes(payload_bytes)
    references_doc = {
        "schema_version": "capture-references-v1",
        "references": [
            {
                "kind": "static",
                "page_id": "about",
                "breakpoint": "desktop",
                "source_kind": "image",
                "local_path": "sources/about-desktop.png",
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "canvas_width": 1280,
                "canvas_height": 800,
                "viewport_width": 1280,
                "viewport_height": 800,
                "interpretation": "viewport",
            }
        ],
    }
    references_path = root / "references.json"
    references_path.write_text(json.dumps(references_doc), encoding="utf-8")

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--references", str(references_path), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    about = next(entry for entry in payload["pages"] if entry["page_id"] == "about")
    desktop = next(b for b in about["breakpoints"] if b["breakpoint"] == "desktop")
    assert desktop["status"] == "reference_valid"
    assert desktop["reference"]["source_kind"] == "image"
    assert desktop["reference"]["local_path"] == "sources/about-desktop.png"
    assert desktop["is_canonical_viewport"] is False


@pytest.mark.parametrize(
    "mutate,expected_snippet",
    [
        (lambda doc: doc.update(schema_version="capture-references-v2"), "schema_version"),
        (lambda doc: doc["references"][0].update(extra="nope"), "unknown fields"),
        (lambda doc: doc["references"][0].update(kind="video"), "unknown kind"),
        (lambda doc: doc["references"][0].update(breakpoint="ultrawide"), "unknown breakpoint"),
    ],
)
def test_references_file_decoding_is_strict(mutate, expected_snippet, tmp_path: Path) -> None:
    doc = {
        "schema_version": "capture-references-v1",
        "references": [
            {
                "kind": "live",
                "page_id": "home",
                "breakpoint": "desktop",
                "url": "https://source.example/",
                "viewport_width": 1440,
                "viewport_height": 900,
            }
        ],
    }
    mutate(doc)

    with pytest.raises(Exception) as excinfo:
        decode_capture_references(doc)
    assert expected_snippet in str(excinfo.value)


def test_static_reference_missing_figma_ownership_fails_safely() -> None:
    doc = {
        "schema_version": "capture-references-v1",
        "references": [
            {
                "kind": "static",
                "page_id": "home",
                "breakpoint": "desktop",
                "source_kind": "figma",
                "local_path": "sources/home.png",
                "sha256": "a" * 64,
                "canvas_width": 1440,
                "canvas_height": 900,
                "viewport_width": 1440,
                "viewport_height": 900,
                "interpretation": "viewport",
                # file_key/frame_node_id intentionally omitted.
            }
        ],
    }

    with pytest.raises(Exception) as excinfo:
        decode_capture_references(doc)
    assert "file_key" in str(excinfo.value)


def test_malformed_references_file_is_reported_without_a_traceback(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    references_path = root / "references.json"
    references_path.write_text("not json", encoding="utf-8")

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--references", str(references_path), "--dry-run", "--json"],
    )

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


# ---------------------------------------------------------------------------
# --references workspace containment: resolved against the project root,
# never the process cwd, and checked before the file is ever opened.


def test_references_absolute_path_outside_workspace_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    outside = tmp_path / "outside-references.json"
    outside.write_text(
        json.dumps({"schema_version": "capture-references-v1", "references": []}),
        encoding="utf-8",
    )
    reads: list[Path] = []

    def _unexpected_read(path: Any) -> Any:
        reads.append(Path(path))
        raise AssertionError("references file was opened before containment validation")

    monkeypatch.setattr(project_capture_cmd, "load_strict_json", _unexpected_read)

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--references", str(outside), "--dry-run", "--json"],
    )

    assert result.exit_code != 0, result.output
    assert reads == []


def test_references_relative_path_escaping_workspace_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    outside = tmp_path / "outside-references.json"
    outside.write_text(
        json.dumps({"schema_version": "capture-references-v1", "references": []}),
        encoding="utf-8",
    )
    reads: list[Path] = []

    def _unexpected_read(path: Any) -> Any:
        reads.append(Path(path))
        raise AssertionError("references file was opened before containment validation")

    monkeypatch.setattr(project_capture_cmd, "load_strict_json", _unexpected_read)
    monkeypatch.chdir(root)

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--references", "../outside-references.json", "--dry-run", "--json"],
    )

    assert result.exit_code != 0, result.output
    assert reads == []


def test_references_relative_path_resolves_against_project_root_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    payload_bytes = _png_bytes(1280, 800)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "about-desktop.png").write_bytes(payload_bytes)
    references_doc = {
        "schema_version": "capture-references-v1",
        "references": [
            {
                "kind": "static",
                "page_id": "about",
                "breakpoint": "desktop",
                "source_kind": "image",
                "local_path": "sources/about-desktop.png",
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "canvas_width": 1280,
                "canvas_height": 800,
                "viewport_width": 1280,
                "viewport_height": 800,
                "interpretation": "viewport",
            }
        ],
    }
    (root / "references.json").write_text(json.dumps(references_doc), encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--references", "references.json", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    about = next(entry for entry in payload["pages"] if entry["page_id"] == "about")
    desktop = next(b for b in about["breakpoints"] if b["breakpoint"] == "desktop")
    assert desktop["status"] == "reference_valid"


@pytest.mark.skipif(os.name == "nt", reason="symlink escape uses a POSIX symlink")
def test_references_symlink_escaping_workspace_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    secret = tmp_path / "secret-references.json"
    secret.write_text(
        json.dumps({"schema_version": "capture-references-v1", "references": []}),
        encoding="utf-8",
    )
    link = root / "references-link.json"
    link.symlink_to(secret)
    reads: list[Path] = []

    def _unexpected_read(path: Any) -> Any:
        reads.append(Path(path))
        raise AssertionError("references file was opened before containment validation")

    monkeypatch.setattr(project_capture_cmd, "load_strict_json", _unexpected_read)

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--references", str(link), "--dry-run", "--json"],
    )

    assert result.exit_code != 0, result.output
    assert reads == []


def test_references_in_workspace_absolute_path_is_allowed(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    payload_bytes = _png_bytes(1280, 800)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "about-desktop.png").write_bytes(payload_bytes)
    references_doc = {
        "schema_version": "capture-references-v1",
        "references": [
            {
                "kind": "static",
                "page_id": "about",
                "breakpoint": "desktop",
                "source_kind": "image",
                "local_path": "sources/about-desktop.png",
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "canvas_width": 1280,
                "canvas_height": 800,
                "viewport_width": 1280,
                "viewport_height": 800,
                "interpretation": "viewport",
            }
        ],
    }
    references_path = root / "references.json"
    references_path.write_text(json.dumps(references_doc), encoding="utf-8")

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--references", str(references_path), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Route mapping: managed-path child routes, ambiguity, and explicit overrides.


def test_built_url_override_replaces_an_ambiguous_managed_path(tmp_path: Path) -> None:
    pages = (_page("home", source_reference="https://source.example/"),)
    document = _document(SourceKind.LIVE_HTML, pages)
    # "home-page" has no leading slash and is not an absolute URL: ambiguous.
    managed_pages = [_managed_page("home", page_id=101, path="home-page")]
    root = _workspace(
        tmp_path, project_id="ambiguous-route", document=document, managed_pages=managed_pages
    )

    ambiguous = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])
    assert ambiguous.exit_code != 0
    assert "ambiguous" in ambiguous.output
    assert "--built-url" in ambiguous.output

    overridden = CliRunner().invoke(
        project,
        [
            "capture",
            str(root),
            "--built-url",
            f"home={BASE_URL}/explicit-home",
            "--dry-run",
            "--json",
        ],
    )
    assert overridden.exit_code == 0, overridden.output
    payload = json.loads(overridden.output)
    home = payload["pages"][0]
    assert home["built_url"] == f"{BASE_URL}/explicit-home"
    assert home["built_url_source"] == "explicit_override"


@pytest.mark.parametrize(
    "override_url",
    [
        "http://evil.example/client/home",  # cross-origin
        "http://user:pass@portal.example/client/home",  # embedded credentials
        "http://portal.example:not-a-port/client/home",  # malformed port
        f"{BASE_URL}/%2e%2e/admin",  # encoded traversal
        f"{BASE_URL}\\evil",  # backslash
        f"{BASE_URL}2/home",  # path-segment escape past the child boundary
    ],
)
def test_unsafe_built_url_overrides_are_rejected(override_url: str, tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)

    result = CliRunner().invoke(
        project,
        ["capture", str(root), "--built-url", f"home={override_url}", "--dry-run", "--json"],
    )

    assert result.exit_code != 0


def test_duplicate_built_url_override_is_rejected(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)

    result = CliRunner().invoke(
        project,
        [
            "capture",
            str(root),
            "--built-url",
            f"home={BASE_URL}/a",
            "--built-url",
            f"home={BASE_URL}/b",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "more than once" in result.output


def test_built_url_override_for_unselected_page_is_rejected(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)

    result = CliRunner().invoke(
        project,
        [
            "capture",
            str(root),
            "--page",
            "home",
            "--built-url",
            f"about={BASE_URL}/x",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "not selected" in result.output


# ---------------------------------------------------------------------------
# Target/mapping mismatch prevents the collector from ever being invoked.


def test_unpinned_target_prevents_capture_before_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    project_json = root / "project.json"
    payload = json.loads(project_json.read_text(encoding="utf-8"))
    payload["target"]["expected_base_url"] = None
    payload["target"]["expected_portal_id"] = None
    project_json.write_text(json.dumps(payload), encoding="utf-8")

    fake = _FakeCollector()
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code != 0
    assert "expected_base_url" in result.output
    assert fake.calls == []


def test_missing_managed_page_mapping_prevents_capture_before_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = (_page("home", source_reference="https://source.example/"),)
    document = _document(SourceKind.LIVE_HTML, pages)
    root = _workspace(tmp_path, project_id="no-mapping", document=document, managed_pages=[])

    fake = _FakeCollector()
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code != 0
    assert "no managed page mapping" in result.output
    assert fake.calls == []


def test_ambiguous_managed_page_manifest_prevents_capture_before_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = (_page("home", source_reference="https://source.example/"),)
    document = _document(SourceKind.LIVE_HTML, pages)
    managed_pages = [
        _managed_page("home", page_id=101, path="/agency-home"),
        _managed_page("home", page_id=102, path="/agency-home-2"),
    ]
    root = _workspace(
        tmp_path, project_id="ambiguous-mapping", document=document, managed_pages=managed_pages
    )

    fake = _FakeCollector()
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code != 0
    assert "ambiguous" in result.output
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Real capture path: correct kwargs, partial failure aggregation, redaction.


def test_real_capture_passes_expected_kwargs_to_the_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vanjaro_cli.orchestration.portal_identity import verify_project_portal

    root = _live_workspace(tmp_path)
    fake = _FakeCollector()
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(
        project, ["capture", str(root), "--page", "home", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["root"] == root
    assert isinstance(call["document"], DesignDocument)
    assert call["manifest"].project.id == "capture-cmd"
    assert call["page_id"] == "home"
    assert call["built_url"] == f"{BASE_URL}/agency-home"
    assert isinstance(call["capture_session"], PlaywrightCaptureSession)
    assert call["references"] == ()
    assert call["target_verifier"] is verify_project_portal


def test_partial_failure_aggregates_per_page_with_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    fake = _FakeCollector(
        results={"home": {"status": "ok", "page_id": "home"}},
        raise_for={"about"},
    )
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["captured"] == 1
    assert payload["total"] == 2
    by_page = {entry["page_id"]: entry for entry in payload["pages"]}
    assert by_page["home"]["result"]["status"] == "ok"
    assert by_page["about"]["result"]["status"] == "error"
    assert len(fake.calls) == 2


# ---------------------------------------------------------------------------
# The real collector's explicit status contract: `captured` for complete
# success, `partial`/`failed` for missing breakpoints, `target_mismatch`/
# `page_not_found` for preflight errors before any capture, and a malformed
# result reported honestly rather than guessed at. None of these may be
# translated into success except the real `captured` status and the legacy
# `ok` status some existing test doubles/collectors still return.


def test_real_captured_status_counts_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    fake = _FakeCollector(
        results={
            "home": {"status": "captured", "page_id": "home"},
            "about": {"status": "captured", "page_id": "about"},
        }
    )
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["captured"] == payload["total"] == 2


def test_partial_status_is_not_success_and_is_shown_in_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    fake = _FakeCollector(
        results={
            "home": {
                "status": "partial",
                "page_id": "home",
                "missing_evidence": ["mobile"],
            },
            "about": {"status": "captured", "page_id": "about"},
        }
    )
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root)])

    assert result.exit_code != 0
    assert "- home (DNN page 101): partial" in result.output
    assert "- about (DNN page 102): captured" in result.output


def test_failed_status_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    fake = _FakeCollector(
        results={
            "home": {"status": "failed", "page_id": "home"},
            "about": {"status": "captured", "page_id": "about"},
        }
    )
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["captured"] == 1
    assert payload["total"] == 2


def test_target_mismatch_and_page_not_found_statuses_are_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    fake = _FakeCollector(
        results={
            "home": {"status": "target_mismatch", "page_id": "home"},
            "about": {"status": "page_not_found", "page_id": "about"},
        }
    )
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["captured"] == 0
    by_page = {entry["page_id"]: entry for entry in payload["pages"]}
    assert by_page["home"]["result"]["status"] == "target_mismatch"
    assert by_page["about"]["result"]["status"] == "page_not_found"


def test_malformed_collector_result_is_reported_honestly_not_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    fake = _FakeCollector(
        results={"home": {"unexpected": "shape"}, "about": "not-a-mapping"}
    )
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root)])

    assert result.exit_code != 0
    assert "- home (DNN page 101): malformed" in result.output
    assert "- about (DNN page 102): malformed" in result.output


def test_legacy_ok_status_is_still_supported_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    fake = _FakeCollector()  # default per-page result is the legacy {"status": "ok"}.
    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", fake)

    result = CliRunner().invoke(project, ["capture", str(root), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["captured"] == payload["total"] == 2


def test_collector_exception_message_is_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)

    def _explode(*_args, **_kwargs):
        raise RuntimeError(f"navigation failed at {BASE_URL}/agency-home?token=SUPERSECRET")

    monkeypatch.setattr(project_capture_cmd, "_collect_page_capture", _explode)

    result = CliRunner().invoke(project, ["capture", str(root), "--page", "home", "--json"])

    assert result.exit_code != 0
    assert "SUPERSECRET" not in result.output


def test_built_url_query_secret_is_redacted_in_dry_run_preview(tmp_path: Path) -> None:
    pages = (_page("home", source_reference="https://source.example/"),)
    document = _document(SourceKind.LIVE_HTML, pages)
    managed_pages = [_managed_page("home", page_id=101, path="/agency-home")]
    root = _workspace(
        tmp_path, project_id="redact-query", document=document, managed_pages=managed_pages
    )

    result = CliRunner().invoke(
        project,
        [
            "capture",
            str(root),
            "--built-url",
            f"home={BASE_URL}/agency-home?token=SUPERSECRET",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "SUPERSECRET" not in result.output


# ---------------------------------------------------------------------------
# Dry-run isolation: no writes, no config lookup, no network, no collector import.


def test_dry_run_performs_no_writes(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    after_paths = {path for path in root.rglob("*") if path.is_file()}
    after = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    assert after_paths == set(before)
    assert after == before


def test_dry_run_never_loads_config_or_a_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("dry-run must never load portal credentials")

    monkeypatch.setattr(
        "vanjaro_cli.orchestration.portal_identity.load_config", _forbidden
    )
    monkeypatch.setattr(
        "vanjaro_cli.orchestration.portal_identity.VanjaroClient", _forbidden
    )

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output


def test_dry_run_never_opens_a_network_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)

    def _forbidden_connect(*_args, **_kwargs):
        raise AssertionError("dry-run must never open a network connection")

    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output


def test_dry_run_never_imports_the_collector_module(tmp_path: Path) -> None:
    import sys

    root = _live_workspace(tmp_path)
    sys.modules.pop("vanjaro_cli.orchestration.project_capture_collect", None)

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    assert "vanjaro_cli.orchestration.project_capture_collect" not in sys.modules
    assert "playwright" not in sys.modules


# ---------------------------------------------------------------------------
# Malformed manifests fail as diagnostics, never as a raw traceback.


def test_malformed_page_manifest_is_a_reported_diagnostic(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    (root / "build" / "page-manifest.json").write_text(
        json.dumps({"schema_version": "1.0", "pages": [{"key": "home"}]}), encoding="utf-8"
    )

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "malformed DNN page ID" in result.output


def test_malformed_resolved_design_document_is_a_reported_diagnostic(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    (root / "plans" / "resolved-design-document.json").write_text("not json", encoding="utf-8")

    result = CliRunner().invoke(project, ["capture", str(root), "--dry-run", "--json"])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_project_capture_error_is_a_valueerror_subclass() -> None:
    assert issubclass(CapturePlanError, ValueError)
