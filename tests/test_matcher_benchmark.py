"""Matcher-only accuracy gate over the committed offline benchmark annotations."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.design.matcher import ConfidenceLevel, match_section
from vanjaro_cli.design.models import (
    Alignment,
    BreakpointName,
    ContentElement,
    ContentKind,
    EvidenceStatus,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    ResponsiveObservation,
    Section,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.template_catalog import load_template_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "design-benchmarks"
CATALOG = load_template_catalog(PROJECT_ROOT / "artifacts" / "block-templates")
CATALOG_SLUGS = {Path(entry.relative_path).stem for entry in CATALOG}


def _repeat_kind(value: str) -> RepeatGroupKind:
    mapping = {
        "card": RepeatGroupKind.CARD,
        "testimonial": RepeatGroupKind.TESTIMONIAL,
        "stat": RepeatGroupKind.STAT,
        "pricing_plan": RepeatGroupKind.PRICING_PLAN,
        "team_member": RepeatGroupKind.TEAM_MEMBER,
        "faq_item": RepeatGroupKind.FAQ_ITEM,
        "gallery_item": RepeatGroupKind.GALLERY_ITEM,
        "navigation_item": RepeatGroupKind.NAVIGATION_ITEM,
        "blog_post": RepeatGroupKind.BLOG_POST,
    }
    return mapping.get(value, RepeatGroupKind.OTHER)


def _layout(annotation: dict) -> LayoutObservation:
    role = annotation["semantic_role"]
    content_roles = [item["role"] for item in annotation["content"]]
    group_count = max((len(group["items"]) for group in annotation["groups"]), default=1)
    if role == "hero":
        media_roles = {"hero_media", "section_media", "background_media"}.intersection(content_roles)
        if "background_media" in media_roles or not media_roles:
            return LayoutObservation(
                kind=LayoutKind.STACK,
                contained=False,
                columns=1,
                media_position=MediaPosition.BACKGROUND if media_roles else MediaPosition.NONE,
                alignment=Alignment.CENTER,
                full_bleed=True,
            )
        media_index = next(index for index, value in enumerate(content_roles) if value in media_roles)
        title_index = content_roles.index("section_title")
        return LayoutObservation(
            kind=LayoutKind.SPLIT,
            contained=True,
            columns=2,
            media_position=MediaPosition.LEFT if media_index < title_index else MediaPosition.RIGHT,
            alignment=Alignment.LEFT,
        )
    if role in {"split_feature", "testimonial_feature", "contact"}:
        media_index = next(
            (index for index, value in enumerate(content_roles) if "media" in value),
            None,
        )
        title_index = next(
            (
                index
                for index, value in enumerate(content_roles)
                if value in {"section_title", "author"}
            ),
            0,
        )
        media_position = MediaPosition.NONE
        if media_index is not None:
            media_position = MediaPosition.LEFT if media_index < title_index else MediaPosition.RIGHT
        return LayoutObservation(
            kind=LayoutKind.SPLIT,
            contained=True,
            columns=2,
            media_position=media_position,
            alignment=Alignment.LEFT,
        )
    if role in {"feature_cards", "project_gallery", "testimonials", "logo_cloud"}:
        return LayoutObservation(
            kind=LayoutKind.GRID,
            contained=True,
            columns=group_count,
            media_position=MediaPosition.TOP if any("media" in value or "logo" in value for value in content_roles) else MediaPosition.NONE,
            alignment=Alignment.LEFT,
        )
    if role in {"stats", "process_steps"}:
        return LayoutObservation(
            kind=LayoutKind.STACK,
            contained=False,
            columns=group_count,
            media_position=MediaPosition.NONE,
            alignment=Alignment.CENTER,
            full_bleed=True,
        )
    if role == "navigation":
        return LayoutObservation(
            kind=LayoutKind.FLEX,
            contained=True,
            columns=1,
            media_position=MediaPosition.NONE,
            alignment=Alignment.LEFT,
        )
    return LayoutObservation(
        kind=LayoutKind.STACK,
        contained=True,
        columns=1,
        media_position=MediaPosition.NONE,
        alignment=Alignment.CENTER if role == "call_to_action" else Alignment.LEFT,
    )


def _section_from_annotation(annotation: dict) -> Section:
    content = [
        ContentElement(
            id=item["id"],
            kind=ContentKind(item["kind"]),
            role=item["role"],
            value=item["value"],
            attributes=item.get("attributes", {}),
            group_id=item["group_id"],
            order=item["order"],
            provenance=[],
            confidence=1.0,
        )
        for item in annotation["content"]
    ]
    groups = [
        RepeatGroup(
            id=group["id"],
            kind=_repeat_kind(group["kind"]),
            items=[
                RepeatGroupItem(id=item["id"], fields=item["fields"])
                for item in group["items"]
            ],
        )
        for group in annotation["groups"]
    ]
    viewports = {
        BreakpointName.DESKTOP: Viewport(width=1440, height=900),
        BreakpointName.TABLET: Viewport(width=768, height=1024),
        BreakpointName.MOBILE: Viewport(width=390, height=844),
    }
    responsive = [
        ResponsiveObservation(
            breakpoint=BreakpointName(item["breakpoint"]),
            viewport=viewports[BreakpointName(item["breakpoint"])],
            status=EvidenceStatus.OBSERVED,
            layout_changes=item["observations"],
        )
        for item in annotation["responsive"]
    ]
    return Section(
        id=annotation["id"],
        order=annotation["order"],
        semantic_role=annotation["semantic_role"],
        role_confidence=1.0,
        candidate_roles=[],
        layout=_layout(annotation),
        content=content,
        groups=groups,
        style=StyleSet(),
        responsive=responsive,
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _slug(template_id: str) -> str:
    return Path(template_id).name


def test_matcher_meets_offline_annotation_accuracy_gates() -> None:
    outcomes: list[dict] = []
    for path in sorted((CORPUS_ROOT / "cases").glob("*/annotations.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for annotation in document["expected"]["sections"]:
            acceptable = set(annotation["acceptable_templates"]).intersection(CATALOG_SLUGS)
            if not acceptable:
                continue  # The corpus explicitly requires a new template unavailable to the matcher.
            result = match_section(_section_from_annotation(annotation), CATALOG)
            selected = _slug(result.selected_candidate.template_id)
            top_three = [_slug(candidate.template_id) for candidate in result.candidates]
            outcomes.append(
                {
                    "case": document["case_id"],
                    "section": annotation["id"],
                    "acceptable": sorted(acceptable),
                    "selected": selected,
                    "top_three": top_three,
                    "confidence": result.selected_candidate.confidence.value,
                    "score": result.selected_candidate.score,
                    "reasons": result.selected_candidate.reasons,
                }
            )

    top_one = sum(item["selected"] in item["acceptable"] for item in outcomes) / len(outcomes)
    top_three = sum(bool(set(item["top_three"]).intersection(item["acceptable"])) for item in outcomes) / len(outcomes)
    high = [item for item in outcomes if item["confidence"] == ConfidenceLevel.HIGH.value]
    high_precision = sum(item["selected"] in item["acceptable"] for item in high) / len(high)
    failures = [item for item in outcomes if item["selected"] not in item["acceptable"]]

    assert len(outcomes) == 25
    assert high, "benchmark must exercise at least one high-confidence match"
    assert top_one >= 0.85, {"top_one": top_one, "failures": failures}
    assert top_three >= 0.95, {"top_three": top_three, "failures": failures}
    assert high_precision >= 0.90, {"high_precision": high_precision, "failures": failures}
