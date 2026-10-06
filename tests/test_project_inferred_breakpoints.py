"""Desktop-only Figma/image designs report tablet/mobile as inferred, not missing (RT-5)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from tests.test_project_verify import _Client, _context, _page_detail
from vanjaro_cli.cli import cli
from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.inferred_breakpoints import (
    INFERRED_BREAKPOINTS_NOTE,
    inferred_breakpoints_by_page,
)
from vanjaro_cli.design.models import WarningSeverity
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.sources import HtmlSourceRequest, analyze_source
from vanjaro_cli.orchestration import project_verify
from vanjaro_cli.orchestration.project_handoff_output import render_handoff

CORPUS = Path(__file__).parent / "fixtures" / "design-benchmarks" / "cases"
CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
LIVE_HTML = (
    "<html><body><main><section><h1>Welcome</h1><p>Body copy here.</p></section>"
    "</main></body></html>"
)


def _figma_source() -> dict:
    path = CORPUS / "figma-auto-layout-saas" / "source.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _desktop_only_figma():
    return analyze_figma_document(_figma_source(), file_key="desktop", captured_at=CAPTURED_AT)


def test_desktop_only_figma_lists_tablet_and_mobile_as_inferred() -> None:
    document = _desktop_only_figma()

    inferred = inferred_breakpoints_by_page(document)

    assert list(inferred.values()) == [["tablet", "mobile"]]


def test_inferred_mobile_frame_note_is_informational_not_a_warning() -> None:
    document = _desktop_only_figma()

    note = next(w for w in document.warnings if w.code == "FIGMA_MOBILE_FRAME_MISSING")

    assert note.severity == WarningSeverity.INFO
    assert "inferred" in note.message and "not designed" in note.message
    assert "FIGMA_MOBILE_FRAME_MISSING" not in document.analysis.unsupported_traits


def test_live_html_pages_are_never_listed_as_inferred() -> None:
    document = analyze_source(
        HtmlSourceRequest(html=LIVE_HTML, source_url="https://source.example/", slug="home")
    )

    assert inferred_breakpoints_by_page(document) == {}


def _init_figma_project(runner, root: Path) -> None:
    result = runner.invoke(
        cli,
        [
            "project", "init", str(root), "--name", "Figma Desktop Only",
            "--target-profile", "figma-desktop", "--source", "figma=sources/file.json",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    (root / "sources" / "file.json").write_text(
        json.dumps(_figma_source()), encoding="utf-8"
    )


def test_analyze_and_plan_say_tablet_mobile_are_inferred_for_desktop_only_figma(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "figma"
    _init_figma_project(runner, root)

    analyzed = runner.invoke(cli, ["project", "analyze", str(root), "--json"])
    assert analyzed.exit_code == 0, analyzed.output
    report = json.loads((root / "analysis" / "analysis-report.json").read_text("utf-8"))
    assert report["inferred_breakpoints_note"] == INFERRED_BREAKPOINTS_NOTE
    assert list(report["inferred_breakpoints"].values()) == [["tablet", "mobile"]]
    assert "FIGMA_MOBILE_FRAME_MISSING" not in report["unsupported_traits"]

    planned = runner.invoke(cli, ["project", "plan", str(root), "--json"])
    assert planned.exit_code == 0, planned.output
    validation = json.loads((root / "plans" / "validation.json").read_text("utf-8"))
    assert validation["inferred_breakpoints_note"] == INFERRED_BREAKPOINTS_NOTE
    assert list(validation["inferred_breakpoints"].values()) == [["tablet", "mobile"]]


def test_analyze_and_plan_for_live_html_carry_no_inferred_note(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "live"
    result = runner.invoke(
        cli,
        [
            "project", "init", str(root), "--name", "Live", "--target-profile", "live",
            "--source", "html=sources/index.html", "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    (root / "sources" / "index.html").write_text(LIVE_HTML, encoding="utf-8")

    assert runner.invoke(cli, ["project", "analyze", str(root), "--json"]).exit_code == 0
    assert runner.invoke(cli, ["project", "plan", str(root), "--json"]).exit_code == 0

    report = json.loads((root / "analysis" / "analysis-report.json").read_text("utf-8"))
    validation = json.loads((root / "plans" / "validation.json").read_text("utf-8"))
    assert "inferred_breakpoints" not in report
    assert validation["inferred_breakpoints"] == {}
    assert "inferred_breakpoints_note" not in validation


def test_verify_report_lists_inferred_breakpoints_without_warning_or_blocker(
    tmp_path: Path, monkeypatch
) -> None:
    client = _Client(page=_page_detail())
    context = _context(tmp_path, monkeypatch, client)
    (tmp_path / "build/design-document.json").write_text(
        serialize_design_document(_desktop_only_figma()), encoding="utf-8"
    )

    report = project_verify.preview_project_drafts(context.root, context.manifest)

    assert list(report["inferred_breakpoints"].values()) == [["tablet", "mobile"]]
    assert report["inferred_breakpoints_note"] == INFERRED_BREAKPOINTS_NOTE
    assert not any("inferred" in item for item in report["warnings"])
    assert not any("tablet" in item or "mobile" in item for item in report["blockers"])


def test_verify_report_for_live_html_has_no_inferred_note(
    tmp_path: Path, monkeypatch
) -> None:
    client = _Client(page=_page_detail())
    context = _context(tmp_path, monkeypatch, client)

    report = project_verify.preview_project_drafts(context.root, context.manifest)

    assert report["inferred_breakpoints"] == {}
    assert "inferred_breakpoints_note" not in report


def test_handoff_renders_inferred_layouts_section_only_when_present() -> None:
    scorecard = {
        "project": {"name": "Demo"},
        "checks": [],
        "open_items": [],
        "inventory": {},
        "inferred_breakpoints": {"home": ["tablet", "mobile"]},
    }

    with_note = render_handoff(scorecard)
    without_note = render_handoff({**scorecard, "inferred_breakpoints": {}})

    assert "## Inferred layouts" in with_note
    assert INFERRED_BREAKPOINTS_NOTE in with_note
    assert "- home: tablet, mobile" in with_note
    assert "Inferred layouts" not in without_note
