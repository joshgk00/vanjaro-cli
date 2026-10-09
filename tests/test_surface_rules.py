"""RT-37 — which painted boxes count as a section's cards and panels."""

from __future__ import annotations

from vanjaro_cli.design.surface_rules import SURFACE_LIMIT, SurfaceCandidate, select_surfaces

WIDTH = 1440.0
HEIGHT = 600.0


def _candidate(
    x: float = 100,
    y: float = 100,
    width: float = 300,
    height: float = 400,
    color: str = "#f0709d",
    has_text: bool = True,
) -> SurfaceCandidate:
    return SurfaceCandidate(color=color, x=x, y=y, width=width, height=height, has_text=has_text)


def _select(*candidates: SurfaceCandidate) -> list[SurfaceCandidate]:
    return select_surfaces(candidates, WIDTH, HEIGHT)


def test_a_card_sized_box_holding_text_is_a_surface() -> None:
    card = _candidate()

    assert _select(card) == [card]


def test_surfaces_come_back_in_reading_order() -> None:
    right = _candidate(x=700, color="#fdbb2c")
    left = _candidate(x=100)
    below = _candidate(x=100, y=520)

    assert _select(right, below, left) == [left, right, below]


def test_a_box_spanning_most_of_the_section_is_a_band_not_a_card() -> None:
    assert _select(_candidate(x=0, width=1200)) == []
    assert _select(_candidate(x=0, width=WIDTH * 0.8 - 1)) != []


def test_boxes_too_small_or_empty_of_text_are_not_cards() -> None:
    assert _select(_candidate(width=100)) == []  # under 12% of the width
    assert _select(_candidate(height=48, width=300)) == []  # a button's height
    assert _select(_candidate(width=173, height=70)) == []  # under 2% of the area
    assert _select(_candidate(has_text=False)) == []


def test_the_same_colour_drawn_twice_over_one_box_is_one_card() -> None:
    frame = _candidate()
    inner = _candidate(x=110, y=110, width=290, height=390)

    assert _select(frame, inner) == [frame]


def test_a_different_colour_over_the_same_area_is_kept_as_its_own_panel() -> None:
    outer = _candidate()
    inner = _candidate(x=110, y=110, width=280, height=380, color="#ffffff")

    assert _select(outer, inner) == [outer, inner]


def test_two_cards_of_one_colour_side_by_side_are_two_cards() -> None:
    first = _candidate(x=100)
    second = _candidate(x=500)

    assert _select(first, second) == [first, second]


def test_the_list_is_capped() -> None:
    cards = [
        _candidate(x=20 + 700 * (index % 5), y=20 + 700 * (index // 5), width=600, height=600)
        for index in range(40)
    ]

    assert len(select_surfaces(cards, 4000, 4000)) == SURFACE_LIMIT


def test_a_section_with_no_size_selects_nothing() -> None:
    assert select_surfaces([_candidate()], 0, HEIGHT) == []
    assert select_surfaces([_candidate()], WIDTH, 0) == []
