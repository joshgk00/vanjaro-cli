"""Layout-evidence fairness: spatial structure vs. presentation labels.

Regression coverage for the diagnosed bias where `_layout_kind_score`
demoted a multi-column "band"-labeled template purely for its presentation
name, and where unmeasured (FREEFORM) source geometry gave an unsupported
positive score to "grid"-labeled targets over equally plausible "band"
ones. All sections here are built directly from the shared typed
`Section`/`RepeatGroup` models against the real template catalog -- no
Figma/HTML adapter, no source-kind branching, no fixture files.
"""

from __future__ import annotations

from pathlib import Path

from vanjaro_cli.design.matcher import ConfidenceLevel, match_section, score_template
from vanjaro_cli.design.models import (
    ContentElement,
    ContentKind,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    Section,
    StyleSet,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogEntry, load_template_catalog

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(PROJECT_ROOT / "artifacts" / "block-templates")


def _entry(filename: str) -> TemplateCatalogEntry:
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


BAND_3UP = _entry("stats-band-3up.json")
GRID_4UP = _entry("stats-grid-4up.json")
PHOTO_BAND = _entry("photo-band.json")


def _stat_item(index: int) -> tuple[list[ContentElement], RepeatGroupItem]:
    value = ContentElement(
        id=f"stat-{index}-value",
        kind=ContentKind.STAT,
        role="value",
        value=str(index * 10),
        group_id="stats-group",
        order=index * 2,
        provenance=[],
        confidence=1.0,
    )
    label = ContentElement(
        id=f"stat-{index}-label",
        kind=ContentKind.TEXT,
        role="label",
        value=f"metric {index}",
        group_id="stats-group",
        order=index * 2 + 1,
        provenance=[],
        confidence=1.0,
    )
    item = RepeatGroupItem(id=f"item-{index}", fields={"value": value.id, "label": label.id})
    return [value, label], item


def _stats_section(
    *,
    item_count: int,
    layout_kind: LayoutKind,
    columns: int | None = None,
    media_position: MediaPosition | None = MediaPosition.NONE,
) -> Section:
    """A source-neutral stats section: only real, typed evidence -- no fixture, no adapter."""

    content: list[ContentElement] = []
    items: list[RepeatGroupItem] = []
    for index in range(1, item_count + 1):
        elements, item = _stat_item(index)
        content.extend(elements)
        items.append(item)
    return Section(
        id=f"stats-evidence-{item_count}",
        order=1,
        semantic_role="stats",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=layout_kind,
            contained=True,
            columns=columns,
            media_position=media_position,
            alignment=None,
        ),
        content=content,
        groups=[RepeatGroup(id="stats-group", kind=RepeatGroupKind.STAT, items=items)],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def test_missing_geometry_is_neutral_between_grid_and_band_not_a_grid_preference() -> None:
    """FREEFORM with no column evidence must not structurally favor 'grid' over 'band'."""

    section = _stats_section(item_count=3, layout_kind=LayoutKind.FREEFORM, columns=None)
    assert section.layout.columns is None  # never fabricated from repeat count

    band = score_template(section, BAND_3UP)
    grid = score_template(section, GRID_4UP)

    # Real, measured geometry is genuinely absent here -- the kind-compatibility
    # component of layout must be identical for both candidates, and clearly
    # below 1.0 (unmeasured geometry is not treated as an observed fact).
    assert band.subscores.layout == grid.subscores.layout
    assert band.subscores.layout < 0.7
    assert band.reasons[3] == grid.reasons[3]


def test_known_repeat_cardinality_causally_prefers_the_matching_template() -> None:
    """With layout evidence neutralized, real observed item count decides the winner."""

    three = _stats_section(item_count=3, layout_kind=LayoutKind.FREEFORM, columns=None)
    four = _stats_section(item_count=4, layout_kind=LayoutKind.FREEFORM, columns=None)

    band_for_three = score_template(three, BAND_3UP)
    grid_for_three = score_template(three, GRID_4UP)
    band_for_four = score_template(four, BAND_3UP)
    grid_for_four = score_template(four, GRID_4UP)

    # Layout ties in both cases (no geometry supplied); only repeat_group differs,
    # and it differs in the direction that matches the true observed count.
    assert band_for_three.subscores.layout == grid_for_three.subscores.layout
    assert band_for_four.subscores.layout == grid_for_four.subscores.layout
    assert band_for_three.subscores.repeat_group > grid_for_three.subscores.repeat_group
    assert grid_for_four.subscores.repeat_group > band_for_four.subscores.repeat_group

    result_three = match_section(three, CATALOG)
    result_four = match_section(four, CATALOG)
    assert result_three.selected_candidate.template_id == "Content/stats-band-3up"
    assert result_four.selected_candidate.template_id == "Content/stats-grid-4up"
    assert result_three.selected_candidate.confidence == ConfidenceLevel.HIGH
    assert result_four.selected_candidate.confidence == ConfidenceLevel.HIGH
    # Both templates remain visible alternatives -- the fix changes ranking, not pruning.
    assert "Content/stats-grid-4up" in [c.template_id for c in result_three.candidates]
    assert "Content/stats-band-3up" in [c.template_id for c in result_four.candidates]


def test_measured_grid_columns_reward_spatial_match_and_penalize_column_mismatch() -> None:
    """A multi-column 'band' is a repeated grid with band styling, not a naming mismatch --
    but each template's own column count must still be checked against what was observed."""

    three = _stats_section(item_count=3, layout_kind=LayoutKind.GRID, columns=3)
    four = _stats_section(item_count=4, layout_kind=LayoutKind.GRID, columns=4)

    band_for_three = score_template(three, BAND_3UP)  # band's own columns=[3]: exact match
    grid_for_three = score_template(three, GRID_4UP)  # grid's own columns=[4]: mismatched
    band_for_four = score_template(four, BAND_3UP)  # band's own columns=[3]: mismatched
    grid_for_four = score_template(four, GRID_4UP)  # grid's own columns=[4]: exact match

    # Multi-column band gets full spatial-kind credit against a measured GRID source --
    # it is not demoted just because its presentation label is "band".
    assert band_for_three.subscores.layout == 1.0
    assert grid_for_four.subscores.layout == 1.0

    # But a real column-count mismatch against the *observed* geometry still costs points,
    # for either template -- the fix does not erase genuine measured distinctions.
    assert grid_for_three.subscores.layout < 1.0
    assert band_for_four.subscores.layout < 1.0

    result_three = match_section(three, CATALOG)
    result_four = match_section(four, CATALOG)
    assert result_three.selected_candidate.template_id == "Content/stats-band-3up"
    assert result_four.selected_candidate.template_id == "Content/stats-grid-4up"


def test_five_items_expand_gracefully_and_ties_break_deterministically() -> None:
    """Item counts beyond either template's default must not crash or bias scoring,
    and an honest full tie must resolve the same way regardless of catalog order."""

    five = _stats_section(item_count=5, layout_kind=LayoutKind.FREEFORM, columns=None)
    band = score_template(five, BAND_3UP)
    grid = score_template(five, GRID_4UP)

    # Neither template's default (3 or 4) matches 5 -- expandable capacity absorbs the
    # overflow identically for both, so the two candidates land in an honest exact tie.
    assert band.subscores.repeat_group == grid.subscores.repeat_group
    assert band.score == grid.score

    forward = match_section(five, CATALOG)
    reversed_catalog = match_section(five, reversed(CATALOG))
    assert forward == reversed_catalog
    assert forward.selected_candidate.template_id == "Content/stats-band-3up"

    # With real measured geometry, the tie breaks on which template's own column count
    # is the closer fit to what was actually observed -- not on the label again.
    five_measured = _stats_section(item_count=5, layout_kind=LayoutKind.GRID, columns=5)
    band_measured = score_template(five_measured, BAND_3UP)
    grid_measured = score_template(five_measured, GRID_4UP)
    assert band_measured.subscores.layout < grid_measured.subscores.layout
    result = match_section(five_measured, CATALOG)
    assert result.selected_candidate.template_id == "Content/stats-grid-4up"


def test_single_column_band_stays_a_poor_match_for_a_measured_grid() -> None:
    """A single-column band (a CTA/photo band) must not inherit the grid-compatible
    score that a genuinely multi-column band earns -- it has no columns to hold one."""

    section = _stats_section(item_count=3, layout_kind=LayoutKind.GRID, columns=3)
    single_column_band = score_template(section, PHOTO_BAND)
    multi_column_band = score_template(section, BAND_3UP)

    assert single_column_band.subscores.layout < multi_column_band.subscores.layout
    assert single_column_band.subscores.layout < 0.6
