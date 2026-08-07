"""End-to-end project analysis and planning workflow tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vanjaro_cli.cli import cli
from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport
from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.sources import HtmlSourceRequest, analyze_source
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.orchestration.project_analysis import (
    ProjectAnalysisError,
    merge_design_documents,
    source_input_files,
)
from vanjaro_cli.orchestration.project_planning import run_project_planning
from vanjaro_cli.project import (
    ProjectSource,
    ProjectStage,
    StageContext,
    load_manifest,
)


HTML = """<!doctype html>
<html>
  <head><title>Agency Home</title></head>
  <body>
    <main>
      <section class="hero">
        <h1>Build a clearer future</h1>
        <p>Strategy and implementation for growing organizations.</p>
        <a href="/contact">Start a project</a>
      </section>
    </main>
  </body>
</html>
"""


def _init_local_html_project(runner, root: Path):
    result = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Local Workflow",
            "--target-profile",
            "local-workflow",
            "--source",
            "html=sources/index.html",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    (root / "sources" / "index.html").write_text(HTML, encoding="utf-8")


def test_project_analyze_and_plan_local_html_are_resumable(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "workflow"
    _init_local_html_project(runner, root)

    analyzed = runner.invoke(cli, ["project", "analyze", str(root), "--json"])
    assert analyzed.exit_code == 0, analyzed.output
    analysis_payload = json.loads(analyzed.output)
    assert analysis_payload["execution"]["status"] == "completed"
    assert analysis_payload["report"]["source_count"] == 1
    assert analysis_payload["report"]["pages"] == 1
    assert (root / "analysis" / "design-document.json").is_file()
    assert (root / "analysis" / "sources" / "live-html-1.design-document.json").is_file()

    resumed = runner.invoke(cli, ["project", "analyze", str(root), "--json"])
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.output)["execution"]["status"] == "resumed"

    planned = runner.invoke(cli, ["project", "plan", str(root), "--json"])
    assert planned.exit_code == 0, planned.output
    plan_payload = json.loads(planned.output)
    assert plan_payload["execution"]["status"] == "completed"
    assert plan_payload["validation"]["section_count"] >= 1
    assert isinstance(plan_payload["validation"]["issues"], list)
    assert (root / "plans" / "composition-plan.json").is_file()
    assert (root / "plans" / "library-plan.json").is_file()
    global_plan = json.loads(
        (root / "plans" / "global-block-plan.json").read_text(encoding="utf-8")
    )
    assert global_plan["header_composer_contract_version"] == "1.1"

    resumed_plan = runner.invoke(cli, ["project", "plan", str(root), "--json"])
    assert resumed_plan.exit_code == 0, resumed_plan.output
    assert json.loads(resumed_plan.output)["execution"]["status"] == "resumed"

    document = json.loads(
        (root / "analysis" / "design-document.json").read_text(encoding="utf-8")
    )
    heading_id = document["pages"][0]["sections"][0]["content"][0]["id"]
    corrected = runner.invoke(
        cli,
        [
            "project",
            "overlay",
            "set-value",
            str(root),
            "--id",
            "approved-heading",
            "--target-element",
            heading_id,
            "--value",
            "Build an approved future",
            "--by",
            "content-editor",
            "--reason",
            "Approved client copy",
            "--json",
        ],
    )
    assert corrected.exit_code == 0, corrected.output
    assert json.loads(corrected.output)["next_stage"] == "plan"
    assert load_manifest(root).stages["plan"].status.value == "pending"

    replanned = runner.invoke(cli, ["project", "plan", str(root), "--json"])
    assert replanned.exit_code == 0, replanned.output
    replanned_payload = json.loads(replanned.output)
    assert replanned_payload["validation"]["applied_overlay_count"] == 1
    resolved = json.loads(
        (root / "plans" / "resolved-design-document.json").read_text(
            encoding="utf-8"
        )
    )
    assert resolved["pages"][0]["sections"][0]["content"][0]["value"] == (
        "Build an approved future"
    )


def test_project_planning_uses_explicit_catalog_and_records_request(
    runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "explicit-catalog"
    _init_local_html_project(runner, root)
    analyzed = runner.invoke(cli, ["project", "analyze", str(root), "--json"])
    assert analyzed.exit_code == 0, analyzed.output

    catalog = load_template_catalog()
    monkeypatch.setattr(
        "vanjaro_cli.orchestration.project_planning.load_template_catalog",
        lambda: pytest.fail("ambient catalog must not be loaded"),
    )
    result = run_project_planning(
        StageContext(
            root=root,
            stage=ProjectStage.PLAN,
            manifest=load_manifest(root),
            input_fingerprint="a" * 64,
            attempt=1,
        ),
        catalog=catalog,
        planning_request={
            "agency_pack": {"name": "clicks-and-mortars", "version": "1.1.0"},
            "reviewed_by": "operator",
        },
    )

    assert "plans/planning-request.json" in result.artifacts
    request = json.loads(
        (root / "plans" / "planning-request.json").read_text(encoding="utf-8")
    )
    assert request["agency_pack"]["version"] == "1.1.0"
    assert request["reviewed_by"] == "operator"


def test_project_analyze_dry_run_never_reads_or_writes_source(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "dry-run"
    initialized = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Dry Run",
            "--target-profile",
            "dry-run",
            "--source",
            "html=https://unreachable.invalid/",
        ],
    )
    assert initialized.exit_code == 0, initialized.output

    result = runner.invoke(
        cli, ["project", "analyze", str(root), "--dry-run", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["execution"]["status"] == "dry_run"
    assert not (root / "analysis" / "design-document.json").exists()
    assert load_manifest(root).stages["analyze"].status.value == "pending"


def test_image_source_without_sidecar_fails_with_structured_recovery(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "image"
    initialized = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Image",
            "--target-profile",
            "image",
            "--source",
            "image=sources/mobile.png",
            "--image-viewport",
            "390x844",
            "--image-breakpoint",
            "image-1=mobile",
            "--source-page",
            "image-1=home",
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    (root / "sources" / "mobile.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (390).to_bytes(4, "big") + (844).to_bytes(4, "big")
    )

    result = runner.invoke(cli, ["project", "analyze", str(root), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["category"] == "image_evidence_missing"
    assert payload["error"]["source_id"] == "image-1"
    assert load_manifest(root).stages["analyze"].status.value == "failed"


def test_composite_merge_only_overlays_explicit_page_references() -> None:
    first = ProjectSource(
        id="html-desktop",
        kind=SourceKind.LIVE_HTML,
        reference="https://first.example/",
        page_reference="home",
    )
    second = ProjectSource(
        id="html-mobile",
        kind=SourceKind.LIVE_HTML,
        reference="https://second.example/",
        page_reference="home",
    )
    first_document = analyze_source(
        HtmlSourceRequest(html=HTML, source_url=first.reference, slug="home")
    )
    second_document = analyze_source(
        HtmlSourceRequest(html=HTML, source_url=second.reference, slug="home")
    )

    combined = merge_design_documents(
        "combined", [(first, first_document), (second, second_document)]
    )

    assert combined.source.kind == SourceKind.COMPOSITE
    assert combined.source.identifier == "project:combined"
    assert len(combined.source.metadata["sources"]) == 2
    assert len(combined.pages) == 1

    independent = merge_design_documents(
        "independent",
        [
            (first.model_copy(update={"page_reference": None}), first_document),
            (second.model_copy(update={"page_reference": None}), second_document),
        ],
    )
    assert len(independent.pages) == 2
    assert any(
        warning.code == "independent_project_sources"
        for warning in independent.warnings
    )


def test_source_input_files_rejects_external_local_evidence(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    external = tmp_path / "outside.html"
    external.write_text(HTML, encoding="utf-8")
    source = ProjectSource(
        id="external",
        kind=SourceKind.LIVE_HTML,
        reference=str(external),
    )
    manifest = type("Manifest", (), {"sources": [source]})()

    with pytest.raises(ProjectAnalysisError, match="inside the project workspace"):
        source_input_files(root, manifest)


def test_source_input_files_fingerprints_image_and_evidence_sidecar(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    sources = root / "sources"
    sources.mkdir(parents=True)
    (sources / "home.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (1440).to_bytes(4, "big")
        + (900).to_bytes(4, "big")
    )
    (sources / "home.evidence.json").write_text("{}", encoding="utf-8")
    source = ProjectSource(
        id="image-1",
        kind=SourceKind.IMAGE,
        reference="sources/home.png",
        evidence_reference="sources/home.evidence.json",
        page_reference="home",
        breakpoint=BreakpointName.DESKTOP,
        viewport=Viewport(width=1440, height=900),
    )
    manifest = type("Manifest", (), {"sources": [source]})()

    assert source_input_files(root, manifest) == (
        Path("sources/home.png"),
        Path("sources/home.evidence.json"),
    )


def test_global_sections_are_removed_from_body_plan_without_guessing_templates() -> None:
    document = analyze_source(
        HtmlSourceRequest(html=HTML, source_url="https://example.test/")
    )
    body = document.pages[0].sections[0]
    header = body.model_copy(
        update={
            "id": "site-header",
            "semantic_role": "navigation",
            "content": [],
            "regions": [],
            "groups": [],
            "decorative_layers": [],
            "interactions": [],
        }
    )
    footer = header.model_copy(
        update={"id": "site-footer", "semantic_role": "footer", "order": 2}
    )
    page = document.pages[0].model_copy(
        update={"sections": [header, body.model_copy(update={"order": 1}), footer]}
    )
    document = document.model_copy(update={"pages": [page]})

    body_document, global_plan, issues = split_global_sections(document)

    assert [section.id for section in body_document.pages[0].sections] == [body.id]
    assert [entry["kind"] for entry in global_plan["entries"]] == [
        "header",
        "footer",
    ]
    assert global_plan["section_count"] == 2
    assert global_plan["ready"] is True
    assert issues == ()


def test_render_is_part_of_the_analyze_fingerprint(runner, tmp_path: Path) -> None:
    """Switching to rendered analysis must re-run, not resume.

    Rendered evidence changes what the Design Document contains, so resuming a
    static analysis under --render would report success while leaving the
    fidelity metrics with nothing to compare against.
    """

    root = tmp_path / "render-fingerprint"
    _init_local_html_project(runner, root)

    analyzed = runner.invoke(cli, ["project", "analyze", str(root), "--json"])
    assert analyzed.exit_code == 0, analyzed.output
    static_fingerprint = json.loads(analyzed.output)["execution"]["input_fingerprint"]

    resumed = runner.invoke(cli, ["project", "analyze", str(root), "--json"])
    assert json.loads(resumed.output)["execution"]["status"] == "resumed"

    rendered = runner.invoke(
        cli, ["project", "analyze", str(root), "--render", "--dry-run", "--json"]
    )
    assert rendered.exit_code == 0, rendered.output
    rendered_execution = json.loads(rendered.output)["execution"]
    assert rendered_execution["status"] == "dry_run"
    assert rendered_execution["action"] == "execute"
    assert rendered_execution["input_fingerprint"] != static_fingerprint


def test_content_losses_name_the_fields_a_build_will_drop() -> None:
    """A plan reported valid with zero issues while three card sections lost
    their heading and two rich-text sections their image and button."""

    from vanjaro_cli.orchestration.project_planning import _content_losses

    plan = SimpleNamespace(
        entries=[
            SimpleNamespace(
                source_section_id="page.section.5",
                warnings=(
                    "source field 'section_title' is not editable by template",
                    "source field 'body' is not editable by template",
                ),
            ),
            SimpleNamespace(
                source_section_id="page.section.6",
                warnings=("selected template does not declare a native representation",),
            ),
        ]
    )

    assert _content_losses(plan) == {"page.section.5": ["body", "section_title"]}


def test_a_plan_that_loses_nothing_reports_no_losses() -> None:
    from vanjaro_cli.orchestration.project_planning import _content_losses

    plan = SimpleNamespace(
        entries=[SimpleNamespace(source_section_id="page.section.1", warnings=())]
    )

    assert _content_losses(plan) == {}


def test_plan_refresh_re_runs_a_resumable_plan(tmp_path: Path) -> None:
    """The plan fingerprint covers the analysis and the policy, not the planner,
    so a change to planning itself reproduced the cached result."""

    from click.testing import CliRunner

    from vanjaro_cli.cli import cli

    runner = CliRunner()
    workspace = tmp_path / "project"
    created = runner.invoke(
        cli,
        [
            "project", "init", str(workspace),
            "--name", "Refresh",
            "--target-profile", "pilot",
            "--source", "live_html=sources/page.html",
            "--json",
        ],
    )
    assert created.exit_code == 0, created.output
    source = workspace / "sources" / "page.html"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "<body><section id='a'><h2>Heading</h2><p>Copy here.</p></section></body>",
        encoding="utf-8",
    )
    analyzed = runner.invoke(cli, ["project", "analyze", str(workspace), "--json"])
    assert analyzed.exit_code == 0, analyzed.output

    first = runner.invoke(cli, ["project", "plan", str(workspace), "--json"])
    assert first.exit_code == 0, first.output
    resumed = runner.invoke(cli, ["project", "plan", str(workspace), "--json"])
    refreshed = runner.invoke(cli, ["project", "plan", str(workspace), "--refresh", "--json"])

    assert json.loads(resumed.output)["execution"]["action"] == "resume"
    assert json.loads(refreshed.output)["execution"]["action"] == "execute"
