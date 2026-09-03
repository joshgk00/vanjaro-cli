"""Tests for explicit, provenance-preserving design corrections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from vanjaro_cli.design.models import (
    ContentKind,
    ObservationMethod,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    SourceKind,
)
from vanjaro_cli.design.overlays import (
    DesignOverlay,
    DesignOverlaySet,
    OverlayOperation,
    apply_design_overlays,
)
from vanjaro_cli.design.sources import HtmlSourceRequest, analyze_source
from vanjaro_cli.project import (
    ProjectSource,
    ProjectStage,
    StageEngine,
    StageInputs,
    StageResult,
    add_project_overlay,
    create_manifest,
    initialize_workspace,
    load_manifest,
)


HTML = """<html><body><main><section><h1>Results</h1></section></main></body></html>"""


def _repeat_document():
    document = analyze_source(
        HtmlSourceRequest(html=HTML, source_url="https://example.test/")
    )
    page = document.pages[0]
    section = page.sections[0]
    title = section.content[0]
    group_id = "stats-group"
    item_id = "stats-item-1"
    group = RepeatGroup(
        id=group_id,
        kind=RepeatGroupKind.STAT,
        items=[
            RepeatGroupItem(
                id=item_id,
                fields={"label": title.id},
                provenance=title.provenance,
            )
        ],
        provenance=section.provenance,
    )
    section = section.model_copy(
        update={
            "content": [title.model_copy(update={"group_id": group_id})],
            "groups": [group],
        }
    )
    page = page.model_copy(update={"sections": [section]})
    return document.model_copy(update={"pages": [page]}), item_id


def test_add_repeat_field_overlay_retains_manual_provenance() -> None:
    document, item_id = _repeat_document()
    overlay = DesignOverlay(
        id="missing-stat-value",
        operation=OverlayOperation.ADD_REPEAT_FIELD,
        target_id=item_id,
        field="value",
        content_kind=ContentKind.STAT,
        value="∞",
        author="curator",
        reason="Confirmed in the approved content reference.",
        created_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )

    resolved = apply_design_overlays(
        document, DesignOverlaySet(overlays=[overlay])
    )

    section = resolved.pages[0].sections[0]
    item = section.groups[0].items[0]
    element_id = item.fields["value"]
    element = next(value for value in section.content if value.id == element_id)
    assert element.value == "∞"
    assert element.kind == ContentKind.STAT
    assert element.provenance[0].method == ObservationMethod.MANUAL
    assert element.provenance[0].metadata["author"] == "curator"


def test_project_overlay_invalidates_completed_plan_and_records_decision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    created = datetime(2026, 7, 16, tzinfo=timezone.utc)
    manifest = create_manifest(
        name="Overlay",
        target_profile="overlay",
        sources=[
            ProjectSource(
                id="html-1",
                kind=SourceKind.LIVE_HTML,
                reference="https://example.test/",
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1.0.0",
        clock=lambda: created,
    )
    initialize_workspace(root, manifest)

    def write(relative: str, value: str):
        def operation(context):
            path = context.root / relative
            path.write_text(value, encoding="utf-8")
            return StageResult(artifacts=(relative,), message="complete")

        return operation

    engine = StageEngine(root, clock=lambda: created + timedelta(minutes=1))
    engine.execute(
        ProjectStage.ANALYZE,
        StageInputs(),
        write("analysis/design-document.json", "analysis"),
    )
    engine.execute(
        ProjectStage.PLAN,
        StageInputs(files=(Path("analysis/design-document.json"),)),
        write("plans/composition-plan.json", "plan"),
    )

    overlay = DesignOverlay(
        id="approved-copy",
        operation=OverlayOperation.SET_ELEMENT_VALUE,
        target_id="heading-1",
        value="Approved",
        author="editor",
        reason="Approved client copy.",
        created_at=created + timedelta(minutes=2),
    )
    add_project_overlay(root, overlay)

    updated = load_manifest(root)
    assert updated.stages[ProjectStage.ANALYZE].status.value == "completed"
    assert updated.stages[ProjectStage.PLAN].status.value == "pending"
    assert updated.decisions[-1].metadata["overlay_id"] == "approved-copy"
    assert updated.audit[-1].kind == "design_overlay_added"
    assert (root / "analysis" / "design-overlays.json").is_file()
