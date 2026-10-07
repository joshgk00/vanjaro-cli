"""Band colours and photo crop shapes read from Figma node fields.

A flat Figma page paints a section's colour as a full-width rectangle behind
its text, and crops an avatar with an ellipse that carries an image fill. The
adapter used to drop both, so a dark footer built cream and circular photos
built as rectangles at their own proportions.
"""

from __future__ import annotations

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.figma_shapes import (
    background_bands,
    image_shape_style,
    parent_index,
)
from vanjaro_cli.design.models import BoundingBox, StyleProperty

TEAL = {"r": 16 / 255, "g": 48 / 255, "b": 48 / 255, "a": 1}
YELLOW = {"r": 253 / 255, "g": 187 / 255, "b": 44 / 255, "a": 1}


def _box(x: float, y: float, width: float, height: float) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


def _rect(node_id: str, bounds: dict, color: dict | None = TEAL, **extra: object) -> dict:
    node: dict = {
        "id": node_id, "type": "RECTANGLE", "name": f"Rectangle {node_id}",
        "absoluteBoundingBox": bounds,
        "fills": [{"type": "SOLID", "color": color}] if color else [],
    }
    node.update(extra)
    return node


def _photo(node_id: str, bounds: dict, node_type: str = "RECTANGLE", **extra: object) -> dict:
    node: dict = {
        "id": node_id, "type": node_type, "name": f"photo {node_id}",
        "absoluteBoundingBox": bounds,
        "fills": [{"type": "IMAGE", "imageRef": f"ref-{node_id}", "scaleMode": "FILL"}],
    }
    node.update(extra)
    return node


def _shape(node: dict, parent: dict | None = None) -> dict[StyleProperty, str]:
    root = parent or {"id": "root", "type": "FRAME", "children": [node]}
    return dict(image_shape_style(node, node["fills"][0], parent_index(root)))


# -- photo shapes --


def test_a_photo_in_a_square_ellipse_is_a_circular_crop_with_equal_sides():
    assert _shape(_photo("1:1", _box(0, 0, 281, 281), "ELLIPSE")) == {
        StyleProperty.BORDER_RADIUS: "50%",
        StyleProperty.OBJECT_FIT: "cover",
        StyleProperty.WIDTH: "281px",
        StyleProperty.HEIGHT: "281px",
    }


def test_a_photo_in_a_wide_ellipse_is_rounded_but_not_forced_square():
    style = _shape(_photo("1:1", _box(0, 0, 300, 180), "ELLIPSE"))

    assert style[StyleProperty.BORDER_RADIUS] == "50%"
    assert StyleProperty.WIDTH not in style
    assert StyleProperty.HEIGHT not in style


def test_a_rounded_rectangle_keeps_its_corner_radius_in_pixels():
    style = _shape(_photo("1:1", _box(0, 0, 400, 240), cornerRadius=12))

    assert style == {
        StyleProperty.BORDER_RADIUS: "12px",
        StyleProperty.OBJECT_FIT: "cover",
    }


def test_unequal_corner_radii_are_listed_top_left_clockwise():
    style = _shape(_photo("1:1", _box(0, 0, 400, 240), rectangleCornerRadii=[20, 20, 0, 0]))

    assert style[StyleProperty.BORDER_RADIUS] == "20px 20px 0px 0px"


def test_a_radius_of_half_the_side_is_a_circle_however_the_file_spells_it():
    style = _shape(_photo("1:1", _box(0, 0, 100, 100), cornerRadius=50))

    assert style[StyleProperty.BORDER_RADIUS] == "50%"
    assert style[StyleProperty.WIDTH] == style[StyleProperty.HEIGHT] == "100px"


def test_a_plain_rectangle_photo_gets_no_shape_style():
    assert _shape(_photo("1:1", _box(0, 0, 400, 240))) == {}


def test_fit_scaling_contains_the_photo_and_other_modes_say_nothing():
    node = _photo("1:1", _box(0, 0, 400, 240), cornerRadius=8)

    node["fills"][0]["scaleMode"] = "FIT"
    assert _shape(node)[StyleProperty.OBJECT_FIT] == "contain"

    node["fills"][0]["scaleMode"] = "CROP"
    assert StyleProperty.OBJECT_FIT not in _shape(node)


def test_a_ring_shaped_ellipse_is_not_a_photo_crop():
    node = _photo("1:1", _box(0, 0, 200, 200), "ELLIPSE", arcData={"innerRadius": 0.5})

    assert _shape(node) == {}


def test_an_ellipse_mask_before_the_photo_crops_it():
    photo = _photo("1:2", _box(10, 10, 200, 200))
    mask = {
        "id": "1:1", "type": "ELLIPSE", "name": "mask", "isMask": True,
        "absoluteBoundingBox": _box(10, 10, 200, 200),
    }
    group = {"id": "1:0", "type": "GROUP", "children": [mask, photo]}

    style = _shape(photo, group)

    assert style[StyleProperty.BORDER_RADIUS] == "50%"
    assert style[StyleProperty.WIDTH] == "200px"


def test_a_mask_elsewhere_on_the_canvas_does_not_crop_the_photo():
    photo = _photo("1:2", _box(10, 10, 200, 200))
    mask = {
        "id": "1:1", "type": "ELLIPSE", "name": "mask", "isMask": True,
        "absoluteBoundingBox": _box(900, 900, 200, 200),
    }
    group = {"id": "1:0", "type": "GROUP", "children": [mask, photo]}

    assert _shape(photo, group) == {}


def test_a_clipping_frame_with_a_radius_crops_the_photo_it_holds():
    photo = _photo("1:2", _box(0, 0, 120, 120))
    frame = {
        "id": "1:1", "type": "FRAME", "name": "Avatar", "clipsContent": True,
        "cornerRadius": 60, "absoluteBoundingBox": _box(0, 0, 120, 120),
        "children": [photo],
    }

    style = _shape(photo, frame)

    assert style[StyleProperty.BORDER_RADIUS] == "50%"


def test_a_frame_that_does_not_clip_does_not_crop_the_photo():
    photo = _photo("1:2", _box(0, 0, 120, 120))
    frame = {
        "id": "1:1", "type": "FRAME", "name": "Card", "clipsContent": False,
        "cornerRadius": 60, "absoluteBoundingBox": _box(0, 0, 120, 120),
        "children": [photo],
    }

    assert _shape(photo, frame) == {}


# -- background bands --


def _bands(children: list[dict], section: dict | None = None) -> list[dict]:
    node = section or {"id": "s", "type": "GROUP", "children": children}
    return background_bands(node, BoundingBox(x=0, y=0, width=1440, height=600))


def test_a_full_width_solid_rectangle_is_the_base_band():
    bands = _bands([_rect("1:1", _box(0, 0, 1440, 540))])

    assert [(band["role"], band["color"], band["node_id"]) for band in bands] == [
        ("base", "#103030", "1:1")
    ]


def test_a_thin_strip_of_another_colour_under_the_base_is_the_bottom_bar():
    bands = _bands([
        _rect("1:1", _box(0, 0, 1440, 540)),
        _rect("1:2", _box(0, 540, 1440, 60), YELLOW),
    ])

    assert [(band["role"], band["color"]) for band in bands] == [
        ("base", "#103030"), ("bottom_bar", "#fdbb2c"),
    ]
    assert bands[1]["bounds"] == {"x": 0.0, "y": 540.0, "width": 1440.0, "height": 60.0}


def test_a_strip_of_the_same_colour_or_overlapping_the_base_is_not_a_bar():
    same_colour = _bands([
        _rect("1:1", _box(0, 0, 1440, 540)),
        _rect("1:2", _box(0, 540, 1440, 60)),
    ])
    overlapping = _bands([
        _rect("1:1", _box(0, 0, 1440, 540)),
        _rect("1:2", _box(0, 300, 1440, 60), YELLOW),
    ])

    assert [band["role"] for band in same_colour] == ["base"]
    assert [band["role"] for band in overlapping] == ["base"]


def test_paint_that_is_not_one_opaque_solid_is_not_a_band():
    image = _rect("1:1", _box(0, 0, 1440, 540), None)
    image["fills"] = [{"type": "IMAGE", "imageRef": "r"}]
    layered = _rect("1:2", _box(0, 0, 1440, 540))
    layered["fills"].append({"type": "SOLID", "color": YELLOW})
    see_through = _rect("1:3", _box(0, 0, 1440, 540))
    see_through["fills"][0]["opacity"] = 0.5
    faded = _rect("1:4", _box(0, 0, 1440, 540), opacity=0.4)
    hidden = _rect("1:5", _box(0, 0, 1440, 540), visible=False)

    for node in (image, layered, see_through, faded, hidden):
        assert _bands([node]) == [], node["id"]


def test_a_rectangle_narrower_than_the_section_is_not_a_band():
    assert _bands([_rect("1:1", _box(100, 0, 600, 540))]) == []


def test_a_real_frame_with_its_own_solid_fill_is_its_own_base_band():
    frame = _rect("1:1", _box(0, 0, 1440, 600))
    frame["type"] = "FRAME"
    frame["children"] = []

    assert [(band["role"], band["node_id"]) for band in _bands([], section=frame)] == [
        ("base", "1:1")
    ]


def test_no_section_bounds_means_no_bands():
    assert background_bands({"id": "s", "children": [_rect("1:1", _box(0, 0, 1440, 540))]}, None) == []


# -- through the adapter --


def _text(node_id: str, characters: str, bounds: dict) -> dict:
    return {
        "id": node_id, "type": "TEXT", "name": "Text", "characters": characters,
        "absoluteBoundingBox": bounds, "style": {"fontFamily": "Genova", "fontSize": 14},
    }


def _flat_page() -> dict:
    children = [
        _text("2:1", "Our Team", _box(560, 60, 320, 50)),
        _text("2:2", "Meet the people", _box(500, 120, 440, 30)),
        _photo("2:3", _box(200, 200, 240, 240), "ELLIPSE"),
        _text("2:4", "Ana", _box(270, 460, 100, 30)),
        _photo("2:5", _box(600, 200, 240, 240), "ELLIPSE"),
        _text("2:6", "Ben", _box(670, 460, 100, 30)),
        _photo("2:7", _box(1000, 200, 240, 240), "ELLIPSE"),
        _text("2:8", "Cy", _box(1070, 460, 100, 30)),
        _rect("3:1", _box(0, 700, 1440, 360)),
        _rect("3:2", _box(0, 1060, 1440, 50), YELLOW),
        _text("3:3", "Quick Links", _box(100, 760, 130, 20)),
        _text("3:4", "Home", _box(100, 800, 40, 14)),
        _text("3:5", "Privacy Policy", _box(100, 828, 90, 14)),
        _text("3:6", "All rights reserved", _box(600, 1075, 160, 22)),
    ]
    return {
        "name": "Fixture",
        "document": {"id": "0:0", "type": "DOCUMENT", "children": [{
            "id": "1:0", "type": "CANVAS", "name": "Page", "children": [{
                "id": "1:1", "type": "FRAME", "name": "Home Desktop",
                "absoluteBoundingBox": _box(0, 0, 1440, 1200), "children": children,
            }],
        }]},
    }


def _analyzed():
    return analyze_figma_document(
        _flat_page(), file_key="fixture",
        image_fill_urls={"ref-2:3": "u", "ref-2:5": "u", "ref-2:7": "u"},
    )


def test_the_footer_section_records_its_base_band_and_bottom_bar():
    footer = next(s for s in _analyzed().pages[0].sections if s.semantic_role == "footer")

    bands = footer.metadata["background_bands"]

    assert [(band["role"], band["color"]) for band in bands] == [
        ("base", "#103030"), ("bottom_bar", "#fdbb2c"),
    ]


def test_circular_team_photos_carry_the_crop_as_element_style():
    team = next(s for s in _analyzed().pages[0].sections if s.semantic_role == "team_grid")

    photos = [element for element in team.content if element.kind.value == "image"]

    assert len(photos) == 3
    for photo in photos:
        assert {obs.property: obs.value for obs in photo.style.observations} == {
            StyleProperty.BORDER_RADIUS: "50%",
            StyleProperty.OBJECT_FIT: "cover",
            StyleProperty.WIDTH: "240px",
            StyleProperty.HEIGHT: "240px",
        }
        assert all(obs.provenance and obs.provenance[0].bounds for obs in photo.style.observations)


def test_a_section_with_no_painted_band_records_none():
    team = next(s for s in _analyzed().pages[0].sections if s.semantic_role == "team_grid")

    assert "background_bands" not in team.metadata
