"""Repeated Figma items follow on-screen reading order, not Figma layer order.

Trial 4 (KTS team grid) read "Rachel Stoner" first because her photo sat 42px
higher than the other photos in the same row, while the design reads Julia,
Ben, Shuntaro Sugie, Jahnvi Patel, Rachel Stoner left to right.
"""

from __future__ import annotations

import pytest

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.models import ContentKind, Section

CARD_HEIGHT = 350


def _text(node_id: str, value: str, x: float, y: float, *, width: float = 400, height: float = 50) -> dict:
    return {
        "id": node_id, "type": "TEXT", "name": value, "characters": value,
        "absoluteBoundingBox": {"x": x, "y": y, "width": width, "height": height},
    }


def _photo(node_id: str, x: float, y: float) -> dict:
    return {
        "id": f"photo-{node_id}", "type": "RECTANGLE", "name": f"Portrait {node_id}",
        "absoluteBoundingBox": {"x": x, "y": y, "width": 281, "height": 281},
        "fills": [{"type": "IMAGE", "imageRef": f"ref-{node_id}", "visible": True}],
    }


def _file(children: list[dict], *, layout_mode: str | None = None) -> dict:
    frame: dict = {
        "id": "1:1", "type": "FRAME", "name": "Home Desktop",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1600, "height": 960},
        "children": children,
    }
    if layout_mode is not None:
        frame["layoutMode"] = layout_mode
    return {
        "name": "Reading Order Fixture",
        "document": {
            "id": "0:0", "type": "DOCUMENT", "children": [{
                "id": "1:0", "type": "CANVAS", "name": "Pages", "children": [frame],
            }],
        },
    }


def _item_titles(section: Section) -> list[str]:
    elements = {element.id: element for element in section.content}
    titles: list[str] = []
    for group in section.groups:
        for item in group.items:
            headings = [
                elements[reference] for reference in item.fields.values()
                if isinstance(reference, str) and elements[reference].kind == ContentKind.HEADING
            ]
            titles.append(headings[0].value)
    return titles


def _named_card(name: str, x: float, y: float, *, height: float = CARD_HEIGHT) -> dict:
    return {
        "id": f"card-{name}", "type": "FRAME", "name": name,
        "absoluteBoundingBox": {"x": x, "y": y, "width": 400, "height": height},
        "children": [
            _photo(name, x, y),
            _text(f"title-{name}", name, x, y + 300, width=280),
        ],
    }


def _team_section_titles(cards: list[dict]) -> list[str]:
    grid = {
        "id": "team", "type": "FRAME", "name": "Team grid",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 800},
        "children": cards,
    }
    document = analyze_figma_document(_file([grid], layout_mode="VERTICAL"), file_key="grid-order")
    team = next(section for section in document.pages[0].sections if section.semantic_role == "team_grid")
    return _item_titles(team)


def test_repeated_cards_in_one_row_follow_left_to_right_not_layer_order() -> None:
    cards = [
        _named_card("Dee", 660, 40),
        _named_card("Ana", 40, 40),
        _named_card("Cy", 360, 40),
        _named_card("Ben", 880, 40),
    ]

    assert _team_section_titles(cards) == ["Ana", "Cy", "Dee", "Ben"]


def test_repeated_cards_in_two_rows_follow_top_to_bottom_then_left_to_right() -> None:
    cards = [
        _named_card("Dee", 520, 420),
        _named_card("Ana", 40, 40),
        _named_card("Cy", 40, 420),
        _named_card("Ben", 520, 40),
    ]

    assert _team_section_titles(cards) == ["Ana", "Ben", "Cy", "Dee"]


@pytest.mark.parametrize(
    ("left_card_y", "expected"),
    [
        (CARD_HEIGHT / 2 - 1, ["Left", "Top"]),
        (CARD_HEIGHT / 2 + 1, ["Top", "Left"]),
    ],
)
def test_cards_share_a_row_only_when_tops_differ_by_less_than_half_a_card(
    left_card_y: float, expected: list[str],
) -> None:
    cards = [
        _named_card("Top", 520, 0),
        _named_card("Left", 40, left_card_y),
    ]

    assert _team_section_titles(cards) == expected


def test_cards_at_identical_positions_keep_their_layer_order() -> None:
    cards = [
        _named_card("Second", 40, 40),
        _named_card("First", 40, 40),
    ]

    assert _team_section_titles(cards) == ["Second", "First"]


def test_cards_without_a_bounding_box_follow_positioned_cards_in_original_order() -> None:
    unplaced = _named_card("Unplaced", 0, 0)
    del unplaced["absoluteBoundingBox"]
    cards = [
        unplaced,
        _named_card("Right", 520, 40),
        _named_card("Left", 40, 40),
    ]

    assert _team_section_titles(cards) == ["Left", "Right", "Unplaced"]


def test_cards_already_in_reading_order_are_unchanged() -> None:
    cards = [
        _named_card("Ana", 40, 40),
        _named_card("Ben", 520, 40),
        _named_card("Cy", 40, 420),
        _named_card("Dee", 520, 420),
    ]

    assert _team_section_titles(cards) == ["Ana", "Ben", "Cy", "Dee"]


def _instructor_card(name: str, x: float, photo_y: float) -> dict:
    return {
        "id": f"card-{name}", "type": "GROUP", "name": name,
        "absoluteBoundingBox": {"x": x - 40, "y": photo_y, "width": 360, "height": 407},
        "children": [
            _photo(name, x, photo_y),
            _text(f"title-{name}", name, x - 40, photo_y + 321, width=280),
            _text(f"role-{name}", "Instructor", x - 40, photo_y + 366, width=135, height=41),
        ],
    }


def test_flat_frame_team_grid_follows_reading_order_when_one_photo_sits_higher() -> None:
    cards = [
        _instructor_card("Rachel Stoner", 1260, 258),
        _instructor_card("Julia", 60, 300),
        _instructor_card("Ben", 360, 300),
        _instructor_card("Shuntaro Sugie", 660, 300),
        _instructor_card("Jahnvi Patel", 960, 300),
    ]
    children = [
        _text("heading", "Meet the instructors", 100, 100, width=500),
        _text("body", "Get to know our best instructors ready to teach you", 100, 160, width=766, height=36),
        *cards,
        _text("footer", "All rights reserved", 100, 900, width=400, height=30),
    ]

    document = analyze_figma_document(_file(children), file_key="kts-order")
    team = next(section for section in document.pages[0].sections if section.semantic_role == "team_grid")

    assert _item_titles(team) == ["Julia", "Ben", "Shuntaro Sugie", "Jahnvi Patel", "Rachel Stoner"]
