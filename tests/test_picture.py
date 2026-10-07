"""Tests for the responsive picture-box wrapper helper."""

from __future__ import annotations

from vanjaro_cli.migration.picture import build_picture_box, is_picture_box
from vanjaro_cli.utils.grapesjs import render_components


def _image(src: str = "/old.png", alt: str = "Hero photo") -> dict:
    return {"type": "image", "attributes": {"id": "x", "src": src, "alt": alt}}


def _variants() -> list[dict]:
    return [
        {"url": "/Portals/0/Images/.versions/x_360w.png?ver=1", "width": 360, "type": "image"},
        {"url": "/Portals/0/Images/.versions/x_360w.webp?ver=1", "width": 360, "type": "webp"},
        {"url": "/Portals/0/Images/.versions/x_720w.png?ver=1", "width": 720, "type": "image"},
        {"url": "/Portals/0/Images/.versions/x_720w.webp?ver=1", "width": 720, "type": "webp"},
    ]


def _find(component: dict, predicate) -> dict | None:
    if predicate(component):
        return component
    for child in component.get("components", []):
        found = _find(child, predicate)
        if found is not None:
            return found
    return None


# -- structure --


def test_build_picture_box_nests_image_box_frame_picture():
    box = build_picture_box(_image(), "/Portals/0/Images/x.png", _variants())
    assert box is not None
    assert box["type"] == "image-box"
    frame = box["components"][0]
    assert frame["type"] == "image-frame"
    picture = frame["components"][0]
    assert picture["type"] == "picture-box"
    assert picture["tagName"] == "picture"


def test_webp_source_is_first_with_type_attribute():
    box = build_picture_box(_image(), "/Portals/0/Images/x.png", _variants())
    picture = box["components"][0]["components"][0]
    sources = [c for c in picture["components"] if c["type"] == "source"]
    assert sources[0]["attributes"]["type"] == "image/webp"
    assert "type" not in sources[1]["attributes"]


def test_srcset_carries_width_descriptors_sorted_ascending():
    box = build_picture_box(_image(), "/Portals/0/Images/x.png", _variants())
    picture = box["components"][0]["components"][0]
    webp_source = picture["components"][0]
    assert webp_source["attributes"]["srcset"] == (
        "/Portals/0/Images/.versions/x_360w.webp?ver=1 360w, "
        "/Portals/0/Images/.versions/x_720w.webp?ver=1 720w"
    )
    assert webp_source["attributes"]["sizes"] == "100vw"


def test_inner_image_is_lazy_and_keeps_original_url_and_alt():
    box = build_picture_box(_image(alt="Team photo"), "/Portals/0/Images/x.png", _variants())
    inner = _find(box, lambda c: c.get("type") == "image")
    assert inner["attributes"]["loading"] == "lazy"
    assert inner["attributes"]["src"] == "/Portals/0/Images/x.png"
    assert inner["attributes"]["alt"] == "Team photo"


def test_inner_image_does_not_carry_image_box_class():
    box = build_picture_box(_image(), "/Portals/0/Images/x.png", _variants())
    inner = _find(box, lambda c: c.get("type") == "image")
    class_names = {c["name"] for c in inner["classes"]}
    assert class_names == {"vj-image", "img-fluid"}
    assert "image-box" not in class_names


# -- fallbacks --


def test_no_variants_returns_none():
    assert build_picture_box(_image(), "/x.png", []) is None


def test_variants_without_usable_url_or_width_return_none():
    bad = [
        {"url": "", "width": 360, "type": "webp"},
        {"url": "/x.png", "width": 0, "type": "image"},
        {"width": 360, "type": "webp"},
        "not-a-dict",
    ]
    assert build_picture_box(_image(), "/x.png", bad) is None


def test_only_webp_variants_still_builds_a_picture():
    webp_only = [
        {"url": "/x_360w.webp", "width": 360, "type": "webp"},
        {"url": "/x_720w.webp", "width": 720, "type": "webp"},
    ]
    box = build_picture_box(_image(), "/x.png", webp_only)
    assert box is not None
    picture = box["components"][0]["components"][0]
    sources = [c for c in picture["components"] if c["type"] == "source"]
    assert len(sources) == 1
    assert sources[0]["attributes"]["type"] == "image/webp"


def test_preserves_extra_image_attributes_but_drops_src_and_id():
    image = {
        "type": "image",
        "attributes": {"id": "x", "src": "/old.png", "alt": "Alt", "title": "Tip"},
    }
    box = build_picture_box(image, "/Portals/0/Images/x.png", _variants())
    inner = _find(box, lambda c: c.get("type") == "image")
    assert inner["attributes"]["title"] == "Tip"
    assert inner["attributes"]["src"] == "/Portals/0/Images/x.png"
    assert "id" not in inner["attributes"]


def _styled_image() -> dict:
    return {
        "type": "image",
        "classes": [
            {"name": "image-box", "active": False},
            {"name": "vj-image", "active": False},
            {"name": "img-fluid", "active": False},
            {"name": "rounded-circle", "active": False},
            {"name": "mb-3", "active": False},
        ],
        "attributes": {"id": "photo", "src": "/old.png", "alt": "Alt"},
    }


def test_keep_source_identity_carries_the_id_and_template_classes():
    box = build_picture_box(
        _styled_image(), "/Portals/0/Images/x.png", _variants(), keep_source_identity=True
    )
    inner = _find(box, lambda c: c.get("type") == "image")
    assert inner["attributes"]["id"] == "photo"
    assert [c["name"] for c in inner["classes"]] == [
        "vj-image", "img-fluid", "rounded-circle", "mb-3",
    ]


def test_keep_source_identity_leaves_the_wrapper_unclassed():
    box = build_picture_box(
        _styled_image(), "/Portals/0/Images/x.png", _variants(), keep_source_identity=True
    )
    picture = box["components"][0]["components"][0]
    assert "classes" not in box
    assert [c["name"] for c in box["components"][0]["classes"]] == ["image-frame"]
    assert [c["name"] for c in picture["classes"]] == ["picture-box"]


def test_default_still_drops_the_source_id_and_extra_classes():
    box = build_picture_box(_styled_image(), "/Portals/0/Images/x.png", _variants())
    inner = _find(box, lambda c: c.get("type") == "image")
    assert {c["name"] for c in inner["classes"]} == {"vj-image", "img-fluid"}
    assert "id" not in inner["attributes"]


def test_rewrite_tree_passes_keep_image_identity_to_the_wrapper():
    from vanjaro_cli.migration.url_rewrite import rewrite_tree

    variants = {"/x.png": _variants()}
    kept = {"components": [_styled_image() | {"attributes": {"id": "photo", "src": "/x.png"}}]}
    dropped = {"components": [_styled_image() | {"attributes": {"id": "photo", "src": "/x.png"}}]}

    rewrite_tree(kept, {}, {}, variants, keep_image_identity=True)
    rewrite_tree(dropped, {}, {}, variants)

    kept_inner = _find(kept["components"][0], lambda c: c.get("type") == "image")
    dropped_inner = _find(dropped["components"][0], lambda c: c.get("type") == "image")
    assert kept_inner["attributes"]["id"] == "photo"
    assert "rounded-circle" in {c["name"] for c in kept_inner["classes"]}
    assert "id" not in dropped_inner["attributes"]


# -- idempotence guard --


def test_is_picture_box_detects_wrapper_types():
    assert is_picture_box({"type": "image-box"})
    assert is_picture_box({"type": "image-frame"})
    assert is_picture_box({"type": "picture-box"})
    assert is_picture_box({"tagName": "picture"})
    assert not is_picture_box({"type": "image"})
    assert not is_picture_box({"type": "section"})


# -- rendering --


def test_picture_box_renders_to_picture_markup():
    box = build_picture_box(_image(), "/Portals/0/Images/x.png", _variants())
    html = render_components([box])
    assert "<picture class=\"picture-box\">" in html
    assert html.count("<source") == 2
    assert "type=\"image/webp\"" in html
    assert "srcset=" in html
    # void source tag — no closing tag emitted
    assert "</source>" not in html
    assert "<img loading=\"lazy\"" in html
    assert "img-fluid" in html
    # void source must not swallow the trailing img
    assert html.rstrip().endswith("</picture></span></div>")
