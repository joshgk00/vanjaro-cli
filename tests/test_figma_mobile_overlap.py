"""Acceptance tests for mobile-overlap inference on geometry-inferred splits.

`figma_adapter._infer_mobile` only ever emitted an `overlap` layout change for
`LayoutKind.FREEFORM` sections, reading the `overlap` key that the row-based
freeform fallback writes into `layout.metadata`. `figma_layout_geometry`'s
side-media inference classifies a modestly overlapping side-media hero as
`LayoutKind.SPLIT` instead, storing its own bounded overlap evidence under
`text_overlaps_media` in the same metadata dict. Because the mobile inference
branch checked `kind == FREEFORM` only, that evidence was silently dropped:
a hero whose headline visibly overlaps its photo on desktop reported no
overlap removal when the section stacked to one column on mobile.

Every test here goes through the real `analyze_figma_document` entry point
(never a hand-built `Section`), matching the side-media geometry suite this
scope shares fixtures and helpers with.
"""

from __future__ import annotations

from copy import deepcopy

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.models import BreakpointName, EvidenceStatus, LayoutKind


def _document(children: list[dict], *, name: str = "Home Desktop",
              width: int = 1200, height: int = 2400) -> dict:
    return {
        "name": "Mobile Overlap Fixture",
        "document": {
            "id": "0:0", "type": "DOCUMENT",
            "children": [{
                "id": "1:0", "type": "CANVAS", "name": "Page",
                "children": [{
                    "id": "1:1", "type": "FRAME", "name": name,
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": width, "height": height},
                    "children": children,
                }],
            }],
        },
    }


def _analyze(children: list[dict], *, width: int = 1200, height: int = 2400):
    payload = _document(children, width=width, height=height)
    return analyze_figma_document(payload, file_key="mobile-overlap-fixture")


def _section(document, role: str):
    return next(s for s in document.pages[0].sections if s.semantic_role == role)


def _mobile_observation(section):
    return next(o for o in section.responsive if o.breakpoint == BreakpointName.MOBILE)


def _image(node_id: str, name: str, box: dict | None, ref: str) -> dict:
    node = {"id": node_id, "type": "RECTANGLE", "name": name, "fills": [{"type": "IMAGE", "imageRef": ref}]}
    if box is not None:
        node["absoluteBoundingBox"] = box
    return node


def _text(node_id: str, name: str, characters: str, box: dict | None) -> dict:
    node = {"id": node_id, "type": "TEXT", "name": name, "characters": characters}
    if box is not None:
        node["absoluteBoundingBox"] = box
    return node


def _hero_group(*, image_box: dict | None, headline_box: dict | None, body_box: dict | None,
                 action_box: dict | None, group_box: dict, group_id: str = "300:1") -> dict:
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


# Same base shape as the side-media geometry suite: a tall, dominant image on
# the right beside three text boxes stacked at distinct y-positions, clear of
# the image's horizontal span.
_NONOVERLAPPING_HERO = _hero_group(
    group_box={"x": 0, "y": 0, "width": 1200, "height": 760},
    image_box={"x": 620, "y": 60, "width": 520, "height": 560},
    headline_box={"x": 100, "y": 180, "width": 460, "height": 140},
    body_box={"x": 100, "y": 360, "width": 420, "height": 70},
    action_box={"x": 100, "y": 460, "width": 160, "height": 48},
)


def _with_headline_overlap(hero: dict) -> dict:
    # The headline's right edge pokes ~10% of its own width into the photo —
    # a modest, real-world nudge, not a centered/overlapping composition.
    overlap_amount = 46
    media_left = hero["children"][0]["absoluteBoundingBox"]["x"]
    headline_box = hero["children"][1]["absoluteBoundingBox"]
    headline_width = headline_box["width"]
    headline_box["x"] = media_left + overlap_amount - headline_width
    return hero


def test_right_side_media_overlap_flattens_on_mobile():
    overlapping = _with_headline_overlap(deepcopy(_NONOVERLAPPING_HERO))

    document = _analyze([overlapping])
    section = _section(document, "hero")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.metadata["text_overlaps_media"] is True

    observation = _mobile_observation(section)
    assert observation.status == EvidenceStatus.INFERRED
    assert observation.layout_changes["overlap"] == {"from": True, "to": False}


def test_left_side_media_overlap_flattens_on_mobile():
    def mirror_x(box: dict, section_width: float) -> dict:
        mirrored = dict(box)
        mirrored["x"] = section_width - box["x"] - box["width"]
        return mirrored

    section_width = _NONOVERLAPPING_HERO["absoluteBoundingBox"]["width"]
    mirrored = deepcopy(_NONOVERLAPPING_HERO)
    for child in mirrored["children"]:
        child["absoluteBoundingBox"] = mirror_x(child["absoluteBoundingBox"], section_width)
    overlapping = _with_headline_overlap(mirrored)

    document = _analyze([overlapping])
    section = _section(document, "hero")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.metadata["text_overlaps_media"] is True

    observation = _mobile_observation(section)
    assert observation.status == EvidenceStatus.INFERRED
    assert observation.layout_changes["overlap"] == {"from": True, "to": False}


def test_nonoverlapping_split_does_not_claim_desktop_overlap():
    document = _analyze([deepcopy(_NONOVERLAPPING_HERO)])
    section = _section(document, "hero")

    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.metadata["text_overlaps_media"] is False

    observation = _mobile_observation(section)
    assert observation.layout_changes["overlap"] == {"from": False, "to": False}


def test_missing_geometry_makes_no_overlap_claim():
    # `_image` and `_text` omit the bounding box entirely when given `None`,
    # modeling a source with no usable geometry — side-media inference stays
    # silent, and the generic freeform fallback also has no boxes to reason
    # about, so unknown geometry must not be read as observed overlap.
    no_boxes = _hero_group(
        group_box={"x": 0, "y": 0, "width": 1200, "height": 760},
        image_box=None, headline_box=None, body_box=None, action_box=None,
    )

    document = _analyze([deepcopy(no_boxes)])
    section = _section(document, "hero")

    assert section.layout.kind != LayoutKind.SPLIT
    assert "text_overlaps_media" not in section.layout.metadata

    observation = _mobile_observation(section)
    assert observation.layout_changes.get("overlap", {"from": False}).get("from") is not True


def test_observed_mobile_frame_takes_precedence_over_inference():
    desktop_hero = _with_headline_overlap(deepcopy(_NONOVERLAPPING_HERO))
    mobile_hero = deepcopy(_NONOVERLAPPING_HERO)
    mobile_hero["absoluteBoundingBox"] = {"x": 0, "y": 0, "width": 390, "height": 900}
    mobile_hero["children"][0]["absoluteBoundingBox"] = {"x": 20, "y": 260, "width": 350, "height": 300}
    mobile_hero["children"][1]["absoluteBoundingBox"] = {"x": 20, "y": 40, "width": 350, "height": 100}
    mobile_hero["children"][2]["absoluteBoundingBox"] = {"x": 20, "y": 150, "width": 350, "height": 80}
    mobile_hero["children"][3]["absoluteBoundingBox"] = {"x": 20, "y": 580, "width": 160, "height": 48}

    payload = {
        "name": "Mobile Overlap Fixture",
        "document": {
            "id": "0:0", "type": "DOCUMENT",
            "children": [{
                "id": "1:0", "type": "CANVAS", "name": "Page",
                "children": [
                    {
                        "id": "1:1", "type": "FRAME", "name": "Home Desktop",
                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 2400},
                        "children": [desktop_hero],
                    },
                    {
                        "id": "1:2", "type": "FRAME", "name": "Home Mobile",
                        "absoluteBoundingBox": {"x": 1400, "y": 0, "width": 390, "height": 1600},
                        "children": [mobile_hero],
                    },
                ],
            }],
        },
    }

    document = analyze_figma_document(payload, file_key="mobile-overlap-fixture")
    section = _section(document, "hero")

    observation = _mobile_observation(section)
    assert observation.status == EvidenceStatus.OBSERVED
    assert "overlap" not in observation.layout_changes
