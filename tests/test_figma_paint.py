"""RT-37 — text colours, card fills, and photo darkening read from Figma paint fields.

A flat Figma page states a heading's colour on the text node, paints a card as a
rectangle behind its text, and darkens a hero photo with a translucent rectangle
above it. The adapter recorded none of the three, so the scorer could not tell a
white heading on a dark photo from a dark one on a light page.
"""

from __future__ import annotations

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.figma_shapes import (
    background_overlay,
    surface_fills,
    text_fill_color,
)
from vanjaro_cli.design.models import BoundingBox

WHITE = {"r": 1, "g": 1, "b": 1, "a": 1}
BLACK = {"r": 0, "g": 0, "b": 0, "a": 1}
PINK = {"r": 240 / 255, "g": 112 / 255, "b": 157 / 255, "a": 1}
YELLOW = {"r": 253 / 255, "g": 187 / 255, "b": 44 / 255, "a": 1}
TEAL = {"r": 16 / 255, "g": 48 / 255, "b": 48 / 255, "a": 1}
SECTION = BoundingBox(x=0, y=0, width=1440, height=600)


def _box(x: float, y: float, width: float, height: float) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


def _solid(color: dict, **extra: object) -> dict:
    return {"type": "SOLID", "color": color, **extra}


def _text(node_id: str, characters: str, bounds: dict, fill: dict | None = WHITE, **extra: object) -> dict:
    node: dict = {
        "id": node_id, "type": "TEXT", "name": "Text", "characters": characters,
        "absoluteBoundingBox": bounds, "style": {"fontFamily": "Genova", "fontSize": 20},
        "fills": [_solid(fill)] if fill else [],
    }
    node.update(extra)
    return node


def _rect(node_id: str, bounds: dict, color: dict | None = PINK, **extra: object) -> dict:
    node: dict = {
        "id": node_id, "type": "RECTANGLE", "name": f"Rectangle {node_id}",
        "absoluteBoundingBox": bounds,
        "fills": [_solid(color)] if color else [],
    }
    node.update(extra)
    return node


def _photo(node_id: str, bounds: dict, **extra: object) -> dict:
    node: dict = {
        "id": node_id, "type": "RECTANGLE", "name": f"photo {node_id}",
        "absoluteBoundingBox": bounds,
        "fills": [{"type": "IMAGE", "imageRef": f"ref-{node_id}", "scaleMode": "FILL"}],
    }
    node.update(extra)
    return node


def _section(children: list[dict]) -> dict:
    return {"id": "s", "type": "GROUP", "children": children}


# -- text fill colour --


def test_a_text_node_with_one_opaque_solid_fill_states_its_colour():
    assert text_fill_color(_text("1:1", "Hello", _box(0, 0, 100, 20), PINK)) == "#f0709d"


def test_text_with_no_fill_or_a_see_through_fill_states_no_colour():
    no_fill = _text("1:1", "Hello", _box(0, 0, 100, 20), None)
    see_through = _text("1:2", "Hello", _box(0, 0, 100, 20))
    see_through["fills"][0]["opacity"] = 0.5
    faded = _text("1:3", "Hello", _box(0, 0, 100, 20), opacity=0.4)
    hidden = _text("1:4", "Hello", _box(0, 0, 100, 20), visible=False)

    for node in (no_fill, see_through, faded, hidden):
        assert text_fill_color(node) is None, node["id"]


def test_a_gradient_or_a_stack_of_paints_is_not_one_colour():
    gradient = _text("1:1", "Hello", _box(0, 0, 100, 20))
    gradient["fills"] = [{"type": "GRADIENT_LINEAR", "gradientStops": []}]
    stacked = _text("1:2", "Hello", _box(0, 0, 100, 20))
    stacked["fills"].append(_solid(PINK))

    assert text_fill_color(gradient) is None
    assert text_fill_color(stacked) is None


def test_characters_filled_differently_from_the_rest_leave_the_colour_unstated():
    mixed = _text(
        "1:1", "Hello world", _box(0, 0, 100, 20),
        characterStyleOverrides=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
        styleOverrideTable={"1": {"fills": [_solid(PINK)]}},
    )
    bold_only = _text(
        "1:2", "Hello world", _box(0, 0, 100, 20),
        characterStyleOverrides=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
        styleOverrideTable={"1": {"fontWeight": 700}},
    )

    assert text_fill_color(mixed) is None
    assert text_fill_color(bold_only) == "#ffffff"


def test_only_a_text_node_has_a_text_colour():
    assert text_fill_color(_rect("1:1", _box(0, 0, 100, 20))) is None


# -- cards and panels --


def _card(node_id: str, x: float, color: dict, title: str, top: float = 100) -> list[dict]:
    return [
        _rect(node_id, _box(x, top, 300, 400), color),
        _text(f"{node_id}-t", title, _box(x + 20, top + 20, 200, 30)),
    ]


def _surfaces(children: list[dict], box: BoundingBox | None = SECTION) -> list[dict]:
    return surface_fills(_section(children), box)


def test_each_solid_card_holding_text_is_a_surface_in_reading_order():
    cards = [
        *_card("1:3", 700, YELLOW, "Opening Notes"),
        *_card("1:1", 100, PINK, "Prelude"),
    ]

    found = _surfaces(cards)

    assert [(record["color"], record["node_id"]) for record in found] == [
        ("#f0709d", "1:1"), ("#fdbb2c", "1:3"),
    ]
    assert found[0]["bounds"] == {"x": 100.0, "y": 100.0, "width": 300.0, "height": 400.0}


def test_the_full_width_band_behind_the_cards_is_not_a_card():
    band = _rect("1:0", _box(0, 0, 1440, 600), TEAL)

    found = _surfaces([band, *_card("1:1", 100, PINK, "Prelude")])

    assert [record["node_id"] for record in found] == ["1:1"]


def test_a_rectangle_with_no_text_on_it_is_not_a_card():
    empty = _rect("1:1", _box(100, 100, 300, 400), PINK)

    assert _surfaces([empty, _text("1:2", "Elsewhere", _box(800, 120, 200, 30))]) == []


def test_a_small_chip_or_button_is_not_a_card():
    button = _rect("1:1", _box(100, 100, 160, 48), PINK)

    assert _surfaces([button, _text("1:2", "Learn More", _box(110, 110, 100, 20))]) == []


def test_a_frame_and_the_same_sized_rectangle_inside_it_are_one_card():
    frame = {
        "id": "1:1", "type": "FRAME", "name": "Card", "absoluteBoundingBox": _box(100, 100, 300, 400),
        "fills": [_solid(PINK)],
        "children": [_rect("1:2", _box(100, 100, 300, 400), PINK), _text("1:3", "Prelude", _box(120, 120, 200, 30))],
    }

    assert [record["node_id"] for record in _surfaces([frame])] == ["1:1"]


def test_a_card_painted_by_a_nested_frame_is_found_at_any_depth():
    inner = {
        "id": "1:2", "type": "FRAME", "name": "Card", "absoluteBoundingBox": _box(100, 100, 300, 400),
        "fills": [_solid(YELLOW)], "children": [_text("1:3", "Prelude", _box(120, 120, 200, 30))],
    }
    row = {"id": "1:1", "type": "FRAME", "name": "Row", "absoluteBoundingBox": _box(100, 100, 1200, 400), "children": [inner]}

    assert [record["color"] for record in _surfaces([row])] == ["#fdbb2c"]


def test_hidden_cards_masks_and_non_solid_paint_are_ignored():
    hidden = _rect("1:1", _box(100, 100, 300, 400), PINK, visible=False)
    masked = _rect("1:2", _box(500, 100, 300, 400), PINK, isMask=True)
    faded = _rect("1:3", _box(900, 100, 300, 400), PINK, opacity=0.4)
    text = [_text(f"1:{index}", "Title", _box(x, 120, 100, 20)) for index, x in ((4, 120), (5, 520), (6, 920))]

    assert _surfaces([hidden, masked, faded, *text]) == []


def test_a_section_with_no_box_has_no_surfaces():
    assert _surfaces([*_card("1:1", 100, PINK, "Prelude")], box=None) == []


# -- darkening over the background photo --


def _overlay(children: list[dict]) -> dict | None:
    return background_overlay(_section(children), SECTION)


def test_a_translucent_rectangle_above_the_photo_is_its_darkening():
    photo = _photo("1:1", _box(0, 0, 1440, 600))
    scrim = _rect("1:2", _box(0, 0, 1440, 600), BLACK)
    scrim["fills"][0]["opacity"] = 0.4

    assert _overlay([photo, scrim]) == {
        "color": "#000000", "opacity": 0.4, "node_id": "1:2", "image_node_id": "1:1",
    }


def test_the_alpha_of_the_colour_and_the_nodes_own_opacity_both_count():
    photo = _photo("1:1", _box(0, 0, 1440, 600))
    scrim = _rect("1:2", _box(0, 0, 1440, 600), {**TEAL, "a": 0.5}, opacity=0.5)

    found = _overlay([photo, scrim])

    assert found is not None
    assert (found["color"], found["opacity"]) == ("#103030", 0.25)


def test_a_second_paint_stacked_above_the_image_on_the_same_node_is_its_darkening():
    photo = _photo("1:1", _box(0, 0, 1440, 600))
    photo["fills"].append(_solid(BLACK, opacity=0.3))

    assert _overlay([photo]) == {
        "color": "#000000", "opacity": 0.3, "node_id": "1:1", "image_node_id": "1:1",
    }


def test_a_layer_below_the_photo_or_an_opaque_one_darkens_nothing():
    photo = _photo("1:1", _box(0, 0, 1440, 600))
    below = _rect("1:0", _box(0, 0, 1440, 600), BLACK)
    below["fills"][0]["opacity"] = 0.4
    opaque = _rect("1:2", _box(0, 0, 1440, 600), BLACK)

    assert _overlay([below, photo]) is None
    assert _overlay([photo, opaque]) is None


def test_a_gradient_scrim_has_no_single_colour_so_it_is_not_reported():
    photo = _photo("1:1", _box(0, 0, 1440, 600))
    scrim = _rect("1:2", _box(0, 0, 1440, 600), None)
    scrim["fills"] = [{"type": "GRADIENT_LINEAR", "gradientStops": [], "opacity": 0.5}]

    assert _overlay([photo, scrim]) is None


def test_a_tint_over_only_a_corner_of_the_photo_is_not_its_darkening():
    photo = _photo("1:1", _box(0, 0, 1440, 600))
    corner = _rect("1:2", _box(0, 0, 300, 200), BLACK)
    corner["fills"][0]["opacity"] = 0.4

    assert _overlay([photo, corner]) is None


def test_with_no_background_photo_there_is_nothing_to_darken():
    scrim = _rect("1:2", _box(0, 0, 1440, 600), BLACK)
    scrim["fills"][0]["opacity"] = 0.4
    small_photo = _photo("1:1", _box(0, 0, 300, 200))

    assert _overlay([scrim]) is None
    assert _overlay([small_photo, scrim]) is None
    assert background_overlay(_section([small_photo]), None) is None


# -- through the adapter --


def _page() -> dict:
    children = [
        _photo("2:1", _box(0, 0, 1440, 600)),
        _rect("2:2", _box(0, 0, 1440, 600), BLACK),
        _text("2:3", "MUSIC FOR EVERYONE", _box(200, 200, 800, 100), WHITE),
        _text("2:4", "Lorem ipsum dolor sit amet", _box(200, 320, 600, 40), WHITE),
        _rect("3:1", _box(0, 900, 1440, 700), TEAL),
        _text("3:2", "Our Classes", _box(560, 920, 320, 50), PINK),
        *_card("3:10", 100, PINK, "Prelude", top=1000),
        *_card("3:20", 560, YELLOW, "Opening Notes", top=1000),
        *_card("3:30", 1020, WHITE, "Finale", top=1000),
    ]
    children[1]["fills"][0]["opacity"] = 0.4
    return {
        "name": "Fixture",
        "document": {"id": "0:0", "type": "DOCUMENT", "children": [{
            "id": "1:0", "type": "CANVAS", "name": "Page", "children": [{
                "id": "1:1", "type": "FRAME", "name": "Home Desktop",
                "absoluteBoundingBox": _box(0, 0, 1440, 2000), "children": children,
            }],
        }]},
    }


def _analyzed():
    return analyze_figma_document(_page(), file_key="fixture", image_fill_urls={"ref-2:1": "u"})


def test_text_elements_carry_their_fill_colour_as_an_attribute():
    sections = _analyzed().pages[0].sections
    elements = [element for section in sections for element in section.content if element.kind.value in {"heading", "text"}]
    colours = {str(element.value): element.attributes.get("text_color") for element in elements}

    assert colours["MUSIC FOR EVERYONE"] == "#ffffff"
    assert colours["Our Classes"] == "#f0709d"


def test_the_hero_records_the_darkening_over_its_photo():
    sections = _analyzed().pages[0].sections
    hero = next(section for section in sections if any(str(e.value) == "MUSIC FOR EVERYONE" for e in section.content))

    assert hero.metadata["background_overlay"]["color"] == "#000000"
    assert hero.metadata["background_overlay"]["opacity"] == 0.4


def test_the_class_cards_section_records_each_card_fill_though_the_cut_left_the_rectangles_out():
    sections = _analyzed().pages[0].sections
    classes = next(section for section in sections if section.semantic_role == "class_cards")

    assert [(record["color"], record["node_id"]) for record in classes.metadata["surface_fills"]] == [
        ("#f0709d", "3:10"), ("#fdbb2c", "3:20"), ("#ffffff", "3:30"),
    ]


def test_a_section_without_a_photo_or_cards_records_neither():
    sections = _analyzed().pages[0].sections
    hero = next(section for section in sections if any(str(e.value) == "MUSIC FOR EVERYONE" for e in section.content))

    assert "surface_fills" not in hero.metadata
    assert all("background_overlay" not in section.metadata for section in sections if section is not hero)
