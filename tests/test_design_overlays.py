"""Tests for explicit, provenance-preserving design corrections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from vanjaro_cli.design.models import (
    ContentKind,
    ObservationMethod,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    SourceKind,
)
from vanjaro_cli.commands.project_overlay_cmd import overlay as overlay_cli
from vanjaro_cli.design.overlays import (
    DesignOverlay,
    DesignOverlayError,
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


def _action_document(kind: ContentKind = ContentKind.BUTTON):
    document = analyze_source(
        HtmlSourceRequest(html=HTML, source_url="https://example.test/")
    )
    page = document.pages[0]
    section = page.sections[0]
    title = section.content[0]
    action = title.model_copy(
        update={"id": "join-action", "kind": kind, "value": "Join now", "order": title.order + 1}
    )
    section = section.model_copy(update={"content": [title, action]})
    page = page.model_copy(update={"sections": [section]})
    return document.model_copy(update={"pages": [page]}), action.id, title.id


def _action_url_overlay(target_id: str, url: str = "/register") -> DesignOverlay:
    return DesignOverlay(
        id="join-destination",
        operation=OverlayOperation.SET_ACTION_URL,
        target_id=target_id,
        value=url,
        author="curator",
        reason="The site map sends every sign-up action to registration.",
        created_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )


def test_set_action_url_overlay_gives_a_button_its_destination() -> None:
    document, action_id, _ = _action_document()

    resolved = apply_design_overlays(
        document, DesignOverlaySet(overlays=[_action_url_overlay(action_id)])
    )

    action = next(
        element
        for element in resolved.pages[0].sections[0].content
        if element.id == action_id
    )
    assert action.attributes["href"] == "/register"
    assert action.value == "Join now"
    assert action.metadata["design_overlay_id"] == "join-destination"
    assert action.provenance[-1].method == ObservationMethod.MANUAL
    assert action.provenance[-1].metadata["author"] == "curator"


def test_set_action_url_overlay_accepts_a_link() -> None:
    document, action_id, _ = _action_document(ContentKind.LINK)

    resolved = apply_design_overlays(
        document,
        DesignOverlaySet(overlays=[_action_url_overlay(action_id, "tel:+15555550100")]),
    )

    action = next(
        element
        for element in resolved.pages[0].sections[0].content
        if element.id == action_id
    )
    assert action.attributes["href"] == "tel:+15555550100"


def test_set_action_url_overlay_refuses_a_non_action_target() -> None:
    document, _, heading_id = _action_document()

    with pytest.raises(DesignOverlayError, match="not a button or link"):
        apply_design_overlays(
            document, DesignOverlaySet(overlays=[_action_url_overlay(heading_id)])
        )


@pytest.mark.parametrize("url", ["javascript:alert(1)", "\tjavascript:alert(1)", "ftp://x", ""])
def test_set_action_url_overlay_rejects_unsafe_or_empty_destinations(url: str) -> None:
    with pytest.raises(ValueError, match="set_action_url requires"):
        _action_url_overlay("join-action", url)


def test_set_action_url_cli_refuses_an_unsafe_destination(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        overlay_cli,
        [
            "set-action-url",
            str(tmp_path),
            "--id",
            "join-destination",
            "--target-element",
            "join-action",
            "--url",
            "javascript:alert(1)",
            "--by",
            "curator",
            "--reason",
            "Unsafe input",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "set_action_url requires" in result.output


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
