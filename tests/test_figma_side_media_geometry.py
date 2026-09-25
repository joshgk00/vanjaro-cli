"""Acceptance tests for generic side-media geometry inference.

`figma_adapter._layout`'s non-auto-layout fallback used to detect columns by
grouping children into rows of similar `y` — a rule with no representation
for "one tall image beside several text boxes stacked at different `y`
values", which is exactly the shape of a classic split hero or a
side-media call-to-action. `vanjaro_cli.design.figma_layout_geometry` adds a
generic, evidence-bounded reader for that pattern (dominant non-decorative,
non-full-bleed media beside a text cluster, tolerant of a modest overlap),
shared by every freeform section instead of being a call-to-action-only
special case.

Every test here goes through the real `analyze_figma_document` entry point
(never the private geometry helper directly) and, where a template
selection is asserted, the real `match_section` — so these check the
adapter's actual output and its actual effect on template matching, not a
hand-built `Section`.
"""

from __future__ import annotations

from copy import deepcopy

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.matcher import match_section
from vanjaro_cli.design.models import LayoutKind, MediaPosition
from vanjaro_cli.design.template_catalog import load_template_catalog


def _document(children: list[dict], *, width: int = 1200, height: int = 2400) -> dict:
    return {
        "name": "Side Media Geometry Fixture",
        "document": {
            "id": "0:0", "type": "DOCUMENT",
            "children": [{
                "id": "1:0", "type": "CANVAS", "name": "Page",
                "children": [{
                    "id": "1:1", "type": "FRAME", "name": "Home Desktop",
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": width, "height": height},
                    "children": children,
                }],
            }],
        },
    }


def _analyze(children: list[dict], *, width: int = 1200, height: int = 2400):
    payload = _document(children, width=width, height=height)
    return analyze_figma_document(payload, file_key="side-media-geometry-fixture")


def _section(document, role: str):
    return next(s for s in document.pages[0].sections if s.semantic_role == role)


def _image(node_id: str, name: str, box: dict, ref: str) -> dict:
    return {
        "id": node_id, "type": "RECTANGLE", "name": name,
        "absoluteBoundingBox": box,
        "fills": [{"type": "IMAGE", "imageRef": ref}],
    }


def _text(node_id: str, name: str, characters: str, box: dict | None) -> dict:
    node = {"id": node_id, "type": "TEXT", "name": name, "characters": characters}
    if box is not None:
        node["absoluteBoundingBox"] = box
    return node


def _hero_group(*, image_box: dict, headline_box: dict, body_box: dict, action_box: dict,
                 group_box: dict, group_id: str = "300:1") -> dict:
    return {
        "id": group_id, "type": "GROUP", "name": "Product Hero",
        "absoluteBoundingBox": group_box,
        "children": [
            _image(f"{group_id[:-2]}:2", "Studio photo", image_box, "studio-ref"),
            _text(f"{group_id[:-2]}:3", "Headline", "Build faster with confidence", headline_box),
            _text(f"{group_id[:-2]}:4", "Body", "A platform built for iteration speed.", body_box),
            _text(f"{group_id[:-2]}:5", "Action", "Start building", action_box),
        ],
    }


# A tall, dominant image on the right beside three text boxes stacked at
# distinct y-positions (a row-clustering column count would put each in its
# own row of one, never recognizing this as two sides).
_ORIGINAL_LIKE_HERO = _hero_group(
    group_box={"x": 0, "y": 0, "width": 1200, "height": 760},
    image_box={"x": 620, "y": 60, "width": 520, "height": 560},
    headline_box={"x": 100, "y": 180, "width": 460, "height": 140},
    body_box={"x": 100, "y": 360, "width": 420, "height": 70},
    action_box={"x": 100, "y": 460, "width": 160, "height": 48},
)


def _acceptable_split_hero_templates() -> set[str]:
    return {"Heroes/split-hero", "Content/split-media", "Content/split-media-reverse"}


def test_tall_image_beside_stacked_text_is_split_hero():
    document = _analyze([deepcopy(_ORIGINAL_LIKE_HERO)])
    section = _section(document, "hero")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.columns == 2
    assert section.layout.media_position == MediaPosition.RIGHT
    assert section.layout.metadata["evidence"] == "inferred_from_geometry"
    assert section.metadata["layout_evidence_status"] == "inferred"

    result = match_section(section, load_template_catalog())
    assert result.selected_candidate.template_id in _acceptable_split_hero_templates()
    top3_ids = {candidate.template_id for candidate in result.candidates[:3]}
    assert top3_ids & _acceptable_split_hero_templates()


def test_same_shape_survives_scale_and_translation():
    def transform(box: dict) -> dict:
        scale, tx, ty = 1.35, 300.0, 150.0
        return {
            "x": box["x"] * scale + tx, "y": box["y"] * scale + ty,
            "width": box["width"] * scale, "height": box["height"] * scale,
        }

    scaled = deepcopy(_ORIGINAL_LIKE_HERO)
    scaled["absoluteBoundingBox"] = transform(scaled["absoluteBoundingBox"])
    for child in scaled["children"]:
        child["absoluteBoundingBox"] = transform(child["absoluteBoundingBox"])

    document = _analyze([scaled], width=2400, height=3200)
    section = _section(document, "hero")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.columns == 2
    assert section.layout.media_position == MediaPosition.RIGHT


def test_mirrored_side_is_read_correctly():
    def mirror_x(box: dict, section_width: float) -> dict:
        mirrored = dict(box)
        mirrored["x"] = section_width - box["x"] - box["width"]
        return mirrored

    section_width = _ORIGINAL_LIKE_HERO["absoluteBoundingBox"]["width"]
    mirrored = deepcopy(_ORIGINAL_LIKE_HERO)
    for child in mirrored["children"]:
        child["absoluteBoundingBox"] = mirror_x(child["absoluteBoundingBox"], section_width)

    document = _analyze([mirrored])
    section = _section(document, "hero")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.columns == 2
    assert section.layout.media_position == MediaPosition.LEFT


def test_modest_headline_overlap_still_reads_as_split():
    # The headline's right edge pokes ~10% of its own width into the photo —
    # analogous to a real design where a headline visually nudges over the
    # edge of a hero photo. Body and action stay clear of the image.
    overlap_amount = 46  # ~10% of the 460-wide headline
    media_left = _ORIGINAL_LIKE_HERO["children"][0]["absoluteBoundingBox"]["x"]
    headline_width = _ORIGINAL_LIKE_HERO["children"][1]["absoluteBoundingBox"]["width"]

    overlapping = deepcopy(_ORIGINAL_LIKE_HERO)
    headline_box = overlapping["children"][1]["absoluteBoundingBox"]
    headline_box["x"] = media_left + overlap_amount - headline_width

    document = _analyze([overlapping])
    section = _section(document, "hero")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.media_position == MediaPosition.RIGHT
    assert section.layout.metadata["text_overlaps_media"] is True


def test_real_cta_side_media_is_a_split_cta():
    cta_group = {
        "id": "310:1", "type": "GROUP", "name": "Newsletter CTA",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 460},
        "children": [
            _image("310:2", "Reader photo", {"x": 620, "y": 40, "width": 340, "height": 380}, "reader-ref"),
            _text("310:3", "Heading", "Never miss an update", {"x": 80, "y": 120, "width": 480, "height": 80}),
            _text("310:4", "Body", "Join thousands of readers getting our weekly digest.",
                  {"x": 80, "y": 220, "width": 460, "height": 60}),
            _text("310:5", "Action", "Subscribe now", {"x": 80, "y": 320, "width": 200, "height": 48}),
        ],
    }

    document = _analyze([cta_group])
    section = _section(document, "call_to_action")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.columns == 2
    assert section.layout.media_position == MediaPosition.RIGHT

    result = match_section(section, load_template_catalog())
    assert result.selected_candidate.template_id.startswith("CTAs/")


def test_centered_vertical_stack_is_not_side_media():
    # Media sits centered above the copy — a vertical stack, not a
    # side-by-side split. Both share nearly the same x-center.
    stacked = {
        "id": "320:1", "type": "GROUP", "name": "Details Panel",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 900},
        "children": [
            _image("320:2", "Centered photo", {"x": 300, "y": 40, "width": 400, "height": 380}, "story-ref"),
            _text("320:3", "Headline", "One community, many rivers", {"x": 260, "y": 460, "width": 480, "height": 80}),
            _text("320:4", "Body", "A shared story about the water we protect.",
                  {"x": 280, "y": 560, "width": 440, "height": 60}),
        ],
    }

    document = _analyze([stacked])
    section = _section(document, "content")

    assert section.layout.kind != LayoutKind.SPLIT
    assert section.layout.media_position == MediaPosition.NONE


def test_full_width_background_image_is_not_side_media():
    background = {
        "id": "330:1", "type": "GROUP", "name": "Landscape Panel",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 700},
        "children": [
            _image("330:2", "Panorama photo", {"x": 0, "y": 0, "width": 1200, "height": 700}, "panorama-ref"),
            _text("330:3", "Headline", "Wide open spaces", {"x": 100, "y": 200, "width": 460, "height": 120}),
            _text("330:4", "Body", "A landscape that speaks for itself.", {"x": 100, "y": 340, "width": 420, "height": 60}),
        ],
    }

    document = _analyze([background])
    section = _section(document, "content")

    assert section.layout.kind != LayoutKind.SPLIT
    assert section.layout.media_position == MediaPosition.NONE


def test_decorative_image_is_not_counted_as_main_media():
    decorative = deepcopy(_ORIGINAL_LIKE_HERO)
    decorative["children"][0]["name"] = "Decorative accent shape"

    document = _analyze([decorative])
    section = _section(document, "hero")

    assert section.layout.kind != LayoutKind.SPLIT
    assert section.layout.media_position == MediaPosition.NONE


def test_missing_bounding_boxes_stays_conservative():
    no_boxes = {
        "id": "340:1", "type": "GROUP", "name": "Product Hero",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 760},
        "children": [
            _image("340:2", "Studio photo", None, "studio-ref"),
            _text("340:3", "Headline", "Build faster with confidence", None),
            _text("340:4", "Body", "A platform built for iteration speed.", None),
        ],
    }
    # `_image` always sets a box; strip it to model a source with no usable
    # geometry, the same way the diagnosed stats section had none.
    del no_boxes["children"][0]["absoluteBoundingBox"]

    document = _analyze([no_boxes])
    section = _section(document, "hero")

    assert section.layout.kind != LayoutKind.SPLIT
    assert section.layout.columns is None
    assert section.layout.media_position == MediaPosition.NONE


def test_ambiguous_multiple_images_stays_inconclusive():
    # Two equally sized images (a collage, not a single dominant side media
    # region) plus the same stacked-text shape used elsewhere in this file.
    # Neither image is a confident enough anchor on its own, and — unlike a
    # deliberate two-column grid — nothing here shares a common row either,
    # so the older row-clustering fallback does not independently manufacture
    # a two-column reading.
    collage = {
        "id": "350:1", "type": "GROUP", "name": "Product Hero",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 760},
        "children": [
            _image("350:2", "Top photo", {"x": 620, "y": 60, "width": 520, "height": 270}, "top-ref"),
            _image("350:3", "Bottom photo", {"x": 620, "y": 400, "width": 520, "height": 270}, "bottom-ref"),
            _text("350:4", "Headline", "Build faster with confidence", {"x": 100, "y": 180, "width": 460, "height": 140}),
            _text("350:5", "Body", "A platform built for iteration speed.", {"x": 100, "y": 360, "width": 420, "height": 70}),
            _text("350:6", "Action", "Start building", {"x": 100, "y": 460, "width": 160, "height": 48}),
        ],
    }

    document = _analyze([collage])
    section = _section(document, "hero")

    assert section.layout.kind != LayoutKind.SPLIT
    assert section.layout.media_position == MediaPosition.NONE
