"""Convert Figma REST API node trees into Design Document v1.

The adapter is deliberately pure: callers fetch Figma JSON and signed asset
URLs, while this module performs deterministic structural analysis.  Original
image-fill URLs are accepted through a mapping or resolver hook and are always
preferred to rendered frame screenshots.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from vanjaro_cli.design.models import (
    Alignment,
    AssetKind,
    AssetRecord,
    AssetRole,
    BoundingBox,
    BreakpointName,
    CandidateRole,
    ContentElement,
    ContentKind,
    DecorativeLayer,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    DesignWarning,
    EvidenceStatus,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    ResponsiveObservation,
    Section,
    SourceKind,
    StyleSet,
    TokenValue,
    TypographyToken,
    Viewport,
    WarningSeverity,
)
from vanjaro_cli.design.figma_layout_geometry import infer_side_media as _infer_side_media
from vanjaro_cli.design.figma_text_roles import select_hero_title
from vanjaro_cli.design.figma_sections import segment_frame as _segment_frame
from vanjaro_cli.design.figma_tree import (
    CONTAINER_TYPES as _CONTAINER_TYPES,
    box as _box,
    children as _children,
    is_decorative as _is_decorative,
    visible as _visible,
    walk as _walk,
)

__all__ = [
    "FigmaAdapterError",
    "ImageFillResolver",
    "VectorResolver",
    "analyze_figma_document",
]

ImageFillResolver = Callable[[str], str | None]
VectorResolver = Callable[[Mapping[str, Any]], str | None]

_ADAPTER_VERSION = "1.0"
_BREAKPOINT_VIEWPORTS = {
    BreakpointName.DESKTOP: Viewport(width=1440, height=900),
    BreakpointName.TABLET: Viewport(width=768, height=1024),
    BreakpointName.MOBILE: Viewport(width=390, height=844),
}


class FigmaAdapterError(ValueError):
    """Raised when a payload cannot be interpreted as a Figma document tree."""


def _safe(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "node"


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _provenance(
    node: Mapping[str, Any], *, file_key: str, page_node_id: str | None,
    frame_node_id: str | None, method: ObservationMethod = ObservationMethod.API,
    viewport: BreakpointName | None = None, metadata: dict[str, Any] | None = None,
) -> Provenance:
    component_id = node.get("componentId")
    details = dict(metadata or {})
    if node.get("type") == "INSTANCE":
        if isinstance(node.get("componentProperties"), Mapping):
            details["component_properties"] = dict(node["componentProperties"])
        if isinstance(node.get("overrides"), list):
            details["overrides"] = list(node["overrides"])
    return Provenance(
        source_kind=SourceKind.FIGMA,
        method=method,
        viewport=viewport,
        file_key=file_key,
        page_node_id=page_node_id,
        frame_node_id=frame_node_id,
        element_node_id=str(node.get("id")) if node.get("id") is not None else None,
        component_id=str(component_id) if component_id else None,
        instance_id=str(node.get("id")) if node.get("type") == "INSTANCE" else None,
        bounds=_box(node),
        metadata=details,
    )


def _root_documents(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    document = payload.get("document")
    if isinstance(document, dict):
        return [document]
    nodes = payload.get("nodes")
    if isinstance(nodes, Mapping):
        documents = []
        for value in nodes.values():
            if isinstance(value, Mapping) and isinstance(value.get("document"), dict):
                documents.append(value["document"])
        if documents:
            return documents
    if payload.get("type") in {"DOCUMENT", "CANVAS", "FRAME", "SECTION"}:
        return [dict(payload)]
    raise FigmaAdapterError("Figma payload must contain a document or nodes tree")


def _page_frames(roots: list[dict[str, Any]], node_id: str | None) -> list[tuple[str | None, dict[str, Any]]]:
    found: list[tuple[str | None, dict[str, Any]]] = []
    for root in roots:
        if root.get("type") in {"FRAME", "SECTION"}:
            found.append((None, root))
            continue
        canvases = _children(root) if root.get("type") == "DOCUMENT" else [root]
        for canvas in canvases:
            canvas_id = str(canvas.get("id")) if canvas.get("id") is not None else None
            for child in _children(canvas):
                if child.get("type") in {"FRAME", "SECTION"}:
                    found.append((canvas_id, child))
    if node_id is not None:
        found = [item for item in found if str(item[1].get("id")) == node_id]
        if not found:
            raise FigmaAdapterError(f"Figma page frame {node_id!r} was not found")
    if not found:
        raise FigmaAdapterError("Figma document has no top-level page frames")
    return found


def _breakpoint(frame: Mapping[str, Any]) -> BreakpointName:
    name = str(frame.get("name", "")).lower()
    if "mobile" in name or "phone" in name:
        return BreakpointName.MOBILE
    if "tablet" in name:
        return BreakpointName.TABLET
    if "desktop" in name:
        return BreakpointName.DESKTOP
    box = _box(frame)
    if box and box.width <= 520:
        return BreakpointName.MOBILE
    if box and box.width <= 1024:
        return BreakpointName.TABLET
    return BreakpointName.DESKTOP


def _page_family(name: str) -> str:
    value = re.sub(r"\b(desktop|mobile|tablet|phone)\b", " ", name, flags=re.I)
    value = re.sub(r"\b(1440|1280|1024|768|390|375|360)\b", " ", value)
    value = re.sub(r"[\s/_-]+", " ", value).strip().lower()
    return value or "page"


def _section_role(node: Mapping[str, Any]) -> tuple[str, float, list[CandidateRole]]:
    role_hint = str(node.get("_vanjaro_role_hint") or "").strip()
    if role_hint:
        return role_hint, 0.90, [
            CandidateRole(
                role=role_hint,
                score=0.90,
                evidence=["flat-frame boundary descendant evidence"],
            )
        ]
    name = str(node.get("name", "")).lower()
    rules = [
        ("navigation", ("navigation", "navbar", "header", "menu")),
        ("hero", ("hero", "masthead")),
        ("marquee", ("marquee", "announcement band", "ribbon")),
        ("team_grid", ("team grid", "team", "instructors", "people cards")),
        ("blog_cards", ("blog cards", "blogs", "articles", "latest news")),
        ("class_cards", ("class cards", "classes", "course cards", "program cards")),
        ("split_media", ("split media", "image text")),
        ("video_feature", ("video feature", "media feature", "our media")),
        ("logo_cloud", ("logo", "clients", "partners")),
        ("stats", ("stats", "numbers", "impact", "metrics")),
        ("testimonials", ("testimonials", "quotes", "reviews")),
        ("testimonial_feature", ("story", "quote feature")),
        ("call_to_action", ("cta", "call to action", "volunteer", "final action")),
        ("feature_cards", ("feature", "program", "services", "cards")),
        ("faq", ("faq", "questions")),
        ("footer", ("footer",)),
    ]
    for role, words in rules:
        matched_word = next((word for word in words if word in name), None)
        if matched_word is not None:
            alternatives = [CandidateRole(role=role, score=0.94, evidence=[f"node name contains {matched_word!r}"])]
            if role == "feature_cards":
                alternatives.append(CandidateRole(role="gallery", score=0.45, evidence=["repeated visual items may be gallery-like"]))
            return role, 0.94, alternatives
    return "content", 0.62, [CandidateRole(role="content", score=0.62, evidence=["no strong semantic name evidence"])]


def _alignment(value: Any) -> Alignment | None:
    mapping = {
        "MIN": Alignment.START, "MAX": Alignment.END, "CENTER": Alignment.CENTER,
        "SPACE_BETWEEN": Alignment.SPACE_BETWEEN, "STRETCH": Alignment.STRETCH,
    }
    return mapping.get(str(value).upper())


def _overlap(boxes: list[BoundingBox]) -> bool:
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            if (
                first.x < second.x + second.width and first.x + first.width > second.x
                and first.y < second.y + second.height and first.y + first.height > second.y
            ):
                return True
    return False


def _layout(node: Mapping[str, Any], page_frame: Mapping[str, Any], role: str) -> tuple[LayoutObservation, float, ObservationMethod]:
    mode = node.get("layoutMode")
    node_box, page_box = _box(node), _box(page_frame)
    contained = bool(node_box and page_box and node_box.width < page_box.width * 0.95)
    if mode in {"HORIZONTAL", "VERTICAL"}:
        direction = "row" if mode == "HORIZONTAL" else "column"
        kind = LayoutKind.FLEX if mode == "HORIZONTAL" else LayoutKind.STACK
        columns = None
        visible_children = [child for child in _children(node) if _visible(child)]
        if mode == "HORIZONTAL" and len(visible_children) >= 2:
            columns = len(visible_children)
        for current in _walk(node):
            if current is node or current.get("layoutMode") != "HORIZONTAL":
                continue
            repeated = [child for child in _children(current) if child.get("type") in _CONTAINER_TYPES]
            if len(repeated) >= 2:
                kind, columns = LayoutKind.GRID, len(repeated)
                break
        return LayoutObservation(
            kind=kind, contained=contained, columns=columns,
            media_position=MediaPosition.NONE, alignment=_alignment(node.get("counterAxisAlignItems")),
            full_bleed=not contained, direction=direction,
            wrap=node.get("layoutWrap") == "WRAP",
            metadata={"evidence": "figma_auto_layout", "confidence": 1.0},
        ), 1.0, ObservationMethod.API

    if node_box is not None:
        side_media = _infer_side_media(node, node_box)
        if side_media is not None:
            return LayoutObservation(
                kind=LayoutKind.SPLIT, contained=contained, columns=2,
                media_position=MediaPosition(side_media.media_position),
                full_bleed=not contained,
                metadata={
                    "evidence": "inferred_from_geometry",
                    "confidence": side_media.confidence,
                    "layout_pattern": "side_media",
                    "observed_child_boxes": side_media.text_box_count + 1,
                    "text_overlaps_media": side_media.had_overlap,
                },
            ), side_media.confidence, ObservationMethod.INFERRED

    child_boxes = [_box(child) for child in _children(node) if _visible(child)]
    boxes = [box for box in child_boxes if box is not None]
    columns = None
    if boxes:
        rows: list[list[BoundingBox]] = []
        for box in sorted(boxes, key=lambda item: (item.y, item.x)):
            row = next((row for row in rows if abs(row[0].y - box.y) <= 32), None)
            if row is None:
                rows.append([box])
            else:
                row.append(box)
        columns = max(len(row) for row in rows)
    has_overlap = _overlap(boxes)
    kind = LayoutKind.FREEFORM
    if columns and columns >= 2 and role in {"feature_cards", "stats", "logo_cloud"}:
        kind = LayoutKind.GRID
    elif columns == 2 and not has_overlap:
        kind = LayoutKind.SPLIT
    confidence = 0.76 if len(boxes) >= 2 else 0.58
    return LayoutObservation(
        kind=kind, contained=contained, columns=columns,
        media_position=MediaPosition.NONE, full_bleed=not contained,
        metadata={
            "evidence": "inferred_from_geometry", "confidence": confidence,
            "overlap": has_overlap, "observed_child_boxes": len(boxes),
        },
    ), confidence, ObservationMethod.INFERRED


def _text_kind_role(
    node: Mapping[str, Any], section_role: str, first_text: bool,
    in_repeat_unit: bool = False,
) -> tuple[ContentKind, str]:
    name = str(node.get("name", "")).lower()
    value = str(node.get("characters", "")).strip()
    lexical_action = bool(
        len(value) <= 40
        and len(value.split()) <= 5
        and re.match(
            r"^(?:learn|read|load|join|register|schedule|book|buy|shop|watch|view|"
            r"discover|explore|apply|donate|support|subscribe|submit|contact|call|get|start)\b",
            value,
            flags=re.I,
        )
    )
    if "button" in name or "action" in name or name in {"cta", "link"} or lexical_action:
        return ContentKind.BUTTON, "primary_action"
    if "quote" in name:
        return ContentKind.QUOTE, "testimonial_quote"
    if "author" in name or "cite" in name:
        return ContentKind.TEXT, "author"
    if "logo" in name:
        return ContentKind.TEXT, "logo_wordmark"
    if section_role == "stats":
        if "value" in name or re.fullmatch(r"[\d,.+%kmbd]+", value.lower()):
            return ContentKind.STAT, "stat_value"
        return ContentKind.TEXT, "stat_label"
    if section_role == "call_to_action" and any(word in name for word in ("crew", "event type", "option")):
        return ContentKind.LIST_ITEM, "event_type"
    if "title" in name or "heading" in name or "headline" in name or first_text:
        if section_role == "feature_cards" and "heading" not in name and (in_repeat_unit or not first_text):
            return ContentKind.HEADING, "card_title"
        return ContentKind.HEADING, "section_title"
    if "body" in name or "description" in name:
        return ContentKind.TEXT, "card_body" if section_role == "feature_cards" else "body"
    if section_role in {"feature_cards", "class_cards", "blog_cards", "team_grid"}:
        return ContentKind.TEXT, "card_body"
    if section_role == "marquee":
        return ContentKind.LIST_ITEM, "body"
    return ContentKind.TEXT, "body"


def _field_name(role: str) -> str:
    return {
        "card_media": "media", "card_title": "title", "card_body": "body",
        "testimonial_quote": "quote", "author": "author", "stat_value": "value",
        "stat_label": "label", "logo_wordmark": "label", "event_type": "label",
        "primary_action": "action",
    }.get(role, role)


def _group_kind(section_role: str) -> RepeatGroupKind:
    return {
        "feature_cards": RepeatGroupKind.CARD,
        "class_cards": RepeatGroupKind.CARD,
        "team_grid": RepeatGroupKind.TEAM_MEMBER,
        "blog_cards": RepeatGroupKind.BLOG_POST,
        "testimonials": RepeatGroupKind.TESTIMONIAL,
        "testimonial_feature": RepeatGroupKind.TESTIMONIAL,
        "stats": RepeatGroupKind.STAT,
        "navigation": RepeatGroupKind.NAVIGATION_ITEM,
    }.get(section_role, RepeatGroupKind.OTHER)


class _AssetRegistry:
    def __init__(
        self, *, file_key: str, page_node_id: str | None,
        image_fill_urls: Mapping[str, str] | None, image_resolver: ImageFillResolver | None,
        vector_resolver: VectorResolver | None, warnings: list[DesignWarning],
    ) -> None:
        self.file_key = file_key
        self.page_node_id = page_node_id
        self.image_fill_urls = image_fill_urls or {}
        self.image_resolver = image_resolver
        self.vector_resolver = vector_resolver
        self.warnings = warnings
        self._drafts: dict[str, dict[str, Any]] = {}

    def image(self, ref: str, node: Mapping[str, Any], frame_id: str, editorial: bool) -> str:
        key = f"image:{ref}"
        resolved_url = self.image_fill_urls.get(ref)
        if resolved_url is None and self.image_resolver is not None:
            resolved_url = self.image_resolver(ref)
        asset_id = f"figma-asset-image-{_digest(ref)}"
        provenance = _provenance(node, file_key=self.file_key, page_node_id=self.page_node_id, frame_node_id=frame_id)
        draft = self._drafts.get(key)
        if draft is None:
            box = _box(node)
            draft = {
                "id": asset_id, "kind": AssetKind.IMAGE,
                "role": AssetRole.EDITORIAL if editorial else AssetRole.DECORATIVE,
                "source_url": f"figma://{self.file_key}/{ref}" if resolved_url else None,
                "missing_reason": None if resolved_url else "Figma image fill URL was not supplied or resolved",
                "width": round(box.width) if box else None, "height": round(box.height) if box else None,
                "provenance": [provenance],
                "metadata": {
                    "figma_image_ref": ref,
                    "resolution": "original_fill",
                    "original_available": bool(resolved_url),
                    "owner_node_ids": [str(node.get("id"))],
                },
            }
            self._drafts[key] = draft
            if not resolved_url:
                self.warnings.append(DesignWarning(
                    code="FIGMA_IMAGE_FILL_UNRESOLVED",
                    message=f"Original image fill {ref!r} has no signed URL; provide image_fill_urls or image_resolver.",
                    path=f"figma.nodes[{node.get('id')}]", provenance=[provenance],
                ))
        else:
            owner = str(node.get("id"))
            if owner not in draft["metadata"]["owner_node_ids"]:
                draft["metadata"]["owner_node_ids"].append(owner)
                draft["provenance"].append(provenance)
            if editorial:
                draft["role"] = AssetRole.EDITORIAL
        return asset_id

    def vector(self, node: Mapping[str, Any], frame_id: str) -> str:
        node_id = str(node.get("id"))
        key = f"vector:{node_id}"
        resolved_url = self.vector_resolver(node) if self.vector_resolver is not None else None
        asset_id = f"figma-asset-vector-{_digest(node_id)}"
        provenance = _provenance(node, file_key=self.file_key, page_node_id=self.page_node_id, frame_node_id=frame_id)
        if key not in self._drafts:
            self._drafts[key] = {
                "id": asset_id, "kind": AssetKind.SVG, "role": AssetRole.DECORATIVE,
                "source_url": f"figma://{self.file_key}/node/{node_id}" if resolved_url else None,
                "missing_reason": None if resolved_url else "Vector export URL was not supplied",
                "provenance": [provenance],
                "metadata": {
                    "figma_node_id": node_id,
                    "resolution": "vector_export",
                    "original_available": bool(resolved_url),
                },
            }
            if not resolved_url:
                self.warnings.append(DesignWarning(
                    code="FIGMA_VECTOR_EXPORT_UNRESOLVED",
                    message=f"Visible vector node {node_id!r} requires a vector_resolver export URL.",
                    path=f"figma.nodes[{node_id}]", provenance=[provenance],
                ))
        return asset_id

    def records(self) -> list[AssetRecord]:
        return [AssetRecord(**draft) for _, draft in sorted(self._drafts.items())]


def _extract_section(
    node: Mapping[str, Any], *, page_frame: Mapping[str, Any], page_node_id: str | None,
    file_key: str, page_id: str, order: int, viewport: BreakpointName,
    assets: _AssetRegistry,
) -> Section:
    role, role_confidence, candidates = _section_role(node)
    section_id = f"{page_id}.section.{order}.{_safe(str(node.get('name', node.get('id', 'section'))))}"
    frame_id = str(page_frame.get("id"))
    layout, layout_confidence, layout_method = _layout(node, page_frame, role)
    boundary_inference = node.get("_vanjaro_inferred_boundary")
    base_provenance = _provenance(
        node, file_key=file_key, page_node_id=page_node_id, frame_node_id=frame_id,
        viewport=viewport,
        method=ObservationMethod.INFERRED if boundary_inference else ObservationMethod.API,
        metadata={"inference": boundary_inference, "confidence": 0.78} if boundary_inference else None,
    )
    provenance = [base_provenance]
    if layout_method == ObservationMethod.INFERRED:
        provenance.append(_provenance(
            node, file_key=file_key, page_node_id=page_node_id, frame_node_id=frame_id,
            method=ObservationMethod.INFERRED, viewport=viewport,
            metadata={"inference": "geometry_layout", "confidence": layout_confidence},
        ))

    content: list[ContentElement] = []
    decorative_layers: list[DecorativeLayer] = []
    node_to_element: dict[str, str] = {}
    repeat_descendant_ids = {
        str(descendant.get("id"))
        for unit in _repeat_units(node)
        for descendant in _walk(unit)
        if descendant.get("id") is not None
    }
    first_text = True
    for current in _walk(node):
        if current is node or not _visible(current):
            continue
        node_id = str(current.get("id", f"anonymous-{len(content)}"))
        current_provenance = [_provenance(
            current, file_key=file_key, page_node_id=page_node_id,
            frame_node_id=frame_id, viewport=viewport,
        )]
        if current.get("type") == "TEXT":
            value = str(current.get("characters", "")).strip()
            if not value:
                continue
            in_repeat_unit = node_id in repeat_descendant_ids
            kind, element_role = _text_kind_role(current, role, first_text, in_repeat_unit)
            if not in_repeat_unit:
                first_text = False
            element_id = f"{section_id}.element.{_safe(node_id)}"
            attributes: dict[str, Any] = {"figma_node_id": node_id, "figma_node_name": str(current.get("name", ""))}
            style = current.get("style") or {}
            if style.get("fontFamily"):
                attributes["font_family"] = str(style["fontFamily"])
            if style.get("fontSize") is not None:
                attributes["font_size"] = style["fontSize"]
            if style.get("fontWeight") is not None:
                attributes["font_weight"] = style["fontWeight"]
            content.append(ContentElement(
                id=element_id, kind=kind, role=element_role, value=value,
                attributes=attributes, order=len(content), provenance=current_provenance,
                confidence=0.95 if element_role != "body" else 0.86,
            ))
            node_to_element[node_id] = element_id

        image_fills = [
            fill for fill in (current.get("fills") or [])
            if isinstance(fill, Mapping) and fill.get("type") == "IMAGE" and fill.get("visible") is not False
        ]
        for fill_index, fill in enumerate(image_fills):
            ref = fill.get("imageRef")
            if not ref:
                continue
            decorative = _is_decorative(current)
            asset_id = assets.image(str(ref), current, frame_id, editorial=not decorative)
            if decorative:
                decorative_layers.append(DecorativeLayer(
                    id=f"{section_id}.decoration.{_safe(node_id)}.{fill_index}",
                    kind="figma_image_fill", order=len(decorative_layers), asset_id=asset_id,
                    provenance=current_provenance, confidence=0.92,
                ))
            else:
                element_id = f"{section_id}.element.{_safe(node_id)}.image.{fill_index}"
                image_role = (
                    "card_media"
                    if role in {"feature_cards", "class_cards", "blog_cards"}
                    else "person_media"
                    if role == "team_grid"
                    else "author_media"
                    if role.startswith("testimonial")
                    else "hero_media"
                    if role == "hero"
                    else "section_media"
                )
                content.append(ContentElement(
                    id=element_id, kind=ContentKind.IMAGE, role=image_role,
                    value=str(ref), asset_id=asset_id, order=len(content),
                    attributes={"figma_node_id": node_id, "figma_node_name": str(current.get("name", ""))},
                    provenance=current_provenance, confidence=0.91,
                ))
                node_to_element[node_id] = element_id

        if current.get("type") in {"VECTOR", "STAR", "LINE", "BOOLEAN_OPERATION"} and _is_decorative(current):
            asset_id = assets.vector(current, frame_id)
            decorative_layers.append(DecorativeLayer(
                id=f"{section_id}.decoration.{_safe(node_id)}.vector",
                kind="figma_vector", order=len(decorative_layers), asset_id=asset_id,
                provenance=current_provenance, confidence=0.96,
            ))

    content, inferred_decorations = _refine_section_content(
        content, section_role=role, section_id=section_id, section_box=_box(node),
    )
    decorative_layers.extend(inferred_decorations)
    groups, content = _repeat_groups(
        node, section_id=section_id, section_role=role, content=content,
        node_to_element=node_to_element, file_key=file_key,
        page_node_id=page_node_id, frame_id=frame_id,
    )
    return Section(
        id=section_id, order=order, semantic_role=role,
        role_confidence=role_confidence, candidate_roles=candidates,
        layout=layout, content=content, groups=groups, style=StyleSet(),
        responsive=[], decorative_layers=decorative_layers, interactions=[],
        provenance=provenance,
        metadata={
            "figma_node_id": str(node.get("id")),
            "section_boundary_confidence": 0.78 if boundary_inference else (0.98 if node.get("layoutMode") else 0.84),
            "section_boundary_evidence": "inferred" if boundary_inference else "observed",
            "layout_confidence": layout_confidence,
            "layout_evidence_status": "observed" if layout_method == ObservationMethod.API else "inferred",
        },
    )


def _structural_signature(node: Mapping[str, Any]) -> tuple[int, int, int]:
    descendants = list(_walk(node))
    return (
        sum(item.get("type") == "TEXT" for item in descendants),
        sum(any(isinstance(fill, Mapping) and fill.get("type") == "IMAGE" for fill in (item.get("fills") or [])) for item in descendants),
        sum(item.get("type") == "INSTANCE" for item in descendants),
    )


def _repeat_units(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[list[dict[str, Any]]] = []
    for parent in _walk(node):
        units = [child for child in _children(parent) if _visible(child) and child.get("type") in _CONTAINER_TYPES]
        if len(units) < 2:
            continue
        signatures = [_structural_signature(unit) for unit in units]
        dominant = max(set(signatures), key=signatures.count)
        similar = [unit for unit, signature in zip(units, signatures) if signature == dominant]
        if len(similar) >= 2 and dominant != (0, 0, 0):
            candidates.append(similar)
    return max(candidates, key=len) if candidates else []


def _element_box(element: ContentElement) -> BoundingBox | None:
    return element.provenance[0].bounds if element.provenance else None


def _font_size(element: ContentElement) -> float:
    try:
        return float(element.attributes.get("font_size") or 0)
    except (TypeError, ValueError):
        return 0.0


def _content_position(element: ContentElement) -> tuple[float, float]:
    box = _element_box(element)
    return (box.y, box.x) if box is not None else (float(element.order), 0.0)


def _boxes_overlap(first: BoundingBox | None, second: BoundingBox | None) -> float:
    if first is None or second is None:
        return 0.0
    width = max(
        0.0,
        min(first.x + first.width, second.x + second.width) - max(first.x, second.x),
    )
    height = max(
        0.0,
        min(first.y + first.height, second.y + second.height) - max(first.y, second.y),
    )
    return width * height / max(
        1.0,
        min(first.width * first.height, second.width * second.height),
    )


def _refine_section_content(
    content: list[ContentElement], *, section_role: str, section_id: str,
    section_box: BoundingBox | None,
) -> tuple[list[ContentElement], list[DecorativeLayer]]:
    """Refine ownership after every descendant is available for comparison.

    Figma traversal order is frequently layer order rather than reading order.  This
    pass uses typography and geometry to distinguish headlines, subtitles, media,
    and decorative image layers without relying on file-specific node identifiers.
    """

    updated = {element.id: element for element in content}
    text = [
        element for element in content
        if element.kind in {ContentKind.HEADING, ContentKind.TEXT, ContentKind.OTHER}
    ]
    if section_role in {"hero", "split_media", "call_to_action", "video_feature"} and text:
        title = select_hero_title(text)
        remaining = [element for element in text if element.id != title.id]
        subtitles: list[ContentElement] = []
        eyebrow: ContentElement | None = None
        if section_role == "video_feature" and remaining:
            heading_peers = [
                element for element in remaining
                if _font_size(element) >= max(18.0, _font_size(title) * 0.8)
            ]
            if heading_peers:
                eyebrow = min(heading_peers, key=_content_position)
        elif section_role in {"split_media", "call_to_action"} and remaining:
            candidate = max(remaining, key=lambda element: (_font_size(element), -_content_position(element)[0]))
            if _font_size(candidate) >= max(24.0, _font_size(title) * 0.5):
                subtitles.append(candidate)

        updated[title.id] = title.model_copy(
            update={"kind": ContentKind.HEADING, "role": "section_title"}
        )
        for element in remaining:
            if eyebrow is not None and element.id == eyebrow.id:
                updated[element.id] = element.model_copy(
                    update={"kind": ContentKind.HEADING, "role": "eyebrow"}
                )
            elif element in subtitles:
                updated[element.id] = element.model_copy(
                    update={"kind": ContentKind.HEADING, "role": "subtitle"}
                )
            else:
                updated[element.id] = element.model_copy(
                    update={"kind": ContentKind.TEXT, "role": "body"}
                )

    images = [element for element in content if element.kind == ContentKind.IMAGE]
    duplicate_ids: set[str] = set()
    for index, first in enumerate(images):
        if first.id in duplicate_ids:
            continue
        cluster = [
            candidate for candidate in images[index + 1 :]
            if candidate.id not in duplicate_ids
            and candidate.asset_id == first.asset_id
            and _boxes_overlap(_element_box(first), _element_box(candidate)) >= 0.8
        ]
        if not cluster:
            continue
        choices = [first, *cluster]
        chosen = min(
            choices,
            key=lambda element: (
                (_element_box(element).width * _element_box(element).height)
                if _element_box(element) is not None else float("inf"),
                element.order,
            ),
        )
        duplicate_ids.update(element.id for element in choices if element.id != chosen.id)

    decorative: list[DecorativeLayer] = []
    retained_images = [element for element in images if element.id not in duplicate_ids]
    if section_role == "video_feature" and retained_images:
        text_bottom = max(
            (
                box.y + box.height
                for element in text
                if (box := _element_box(element)) is not None
            ),
            default=-float("inf"),
        )
        after_copy = [
            element for element in retained_images
            if (box := _element_box(element)) is not None and box.y >= text_bottom
        ]
        primary = min(after_copy, key=_content_position) if after_copy else max(
            retained_images,
            key=lambda element: (
                (_element_box(element).width * _element_box(element).height)
                if _element_box(element) is not None else 0.0
            ),
        )
        updated[primary.id] = primary.model_copy(update={"role": "section_media"})
        for element in retained_images:
            if element.id == primary.id:
                continue
            duplicate_ids.add(element.id)
            decorative.append(
                DecorativeLayer(
                    id=f"{section_id}.decoration.{_safe(element.id)}.inferred",
                    kind="editorial_illustration",
                    order=len(decorative),
                    asset_id=element.asset_id,
                    provenance=element.provenance,
                    confidence=0.88,
                )
            )
    else:
        for element in retained_images:
            role = element.role
            box = _element_box(element)
            if (
                section_role == "hero"
                and section_box is not None and box is not None
                and box.width >= section_box.width * 0.75
            ):
                role = "background_media"
            elif (
                section_role == "call_to_action"
                and section_box is not None and box is not None
                and box.width >= section_box.width * 0.75
            ):
                role = "background_media"
            updated[element.id] = element.model_copy(update={"role": role})

    ordered = [updated[element.id] for element in content if element.id not in duplicate_ids]
    ordered.sort(key=lambda element: (element.order, element.id))
    return [element.model_copy(update={"order": index}) for index, element in enumerate(ordered)], decorative


def _image_anchor_clusters(
    content: list[ContentElement], section_role: str,
) -> tuple[list[ContentElement], set[str]]:
    images = [element for element in content if element.kind == ContentKind.IMAGE and _element_box(element)]
    clusters: list[list[ContentElement]] = []
    for element in sorted(
        images,
        key=lambda item: (_element_box(item).y, _element_box(item).x),  # type: ignore[union-attr]
    ):
        box = _element_box(element)
        assert box is not None
        target = None
        for cluster in clusters:
            representative = _element_box(cluster[0])
            assert representative is not None
            horizontal_overlap = max(
                0.0,
                min(box.x + box.width, representative.x + representative.width)
                - max(box.x, representative.x),
            )
            vertical_overlap = max(
                0.0,
                min(box.y + box.height, representative.y + representative.height)
                - max(box.y, representative.y),
            )
            overlap_ratio = (
                horizontal_overlap * vertical_overlap
                / max(1.0, min(box.width * box.height, representative.width * representative.height))
            )
            if overlap_ratio >= 0.45:
                target = cluster
                break
        if target is None:
            clusters.append([element])
        else:
            target.append(element)

    selected: list[ContentElement] = []
    duplicates: set[str] = set()
    for cluster in clusters:
        def preference(element: ContentElement) -> tuple[int, float, int]:
            box = _element_box(element)
            name = str(element.attributes.get("figma_node_name", "")).casefold()
            round_portrait = section_role == "team_grid" and "ellipse" in name
            return (1 if round_portrait else 0, -(box.width * box.height if box else 0), element.order)

        chosen = max(cluster, key=preference)
        selected.append(chosen)
        duplicates.update(element.id for element in cluster if element.id != chosen.id)
    selected.sort(
        key=lambda item: (_element_box(item).y, _element_box(item).x),  # type: ignore[union-attr]
    )
    return selected, duplicates


def _geometric_card_group(
    node: Mapping[str, Any], *, section_id: str, section_role: str,
    content: list[ContentElement], file_key: str, page_node_id: str | None,
    frame_id: str,
) -> tuple[list[RepeatGroup], list[ContentElement]] | None:
    anchors, duplicate_ids = _image_anchor_clusters(content, section_role)
    if len(anchors) < 2:
        return None

    anchor_boxes = [_element_box(anchor) for anchor in anchors]
    if any(box is None for box in anchor_boxes):
        return None
    boxes = [box for box in anchor_boxes if box is not None]
    first_item_top = min(box.y for box in boxes)
    last_item_bottom = max(box.y + box.height for box in boxes)
    section_level: set[str] = set()
    global_action: set[str] = set()
    updated_by_id = {element.id: element for element in content if element.id not in duplicate_ids}

    for element in list(updated_by_id.values()):
        box = _element_box(element)
        if box is None or element.kind == ContentKind.IMAGE:
            continue
        if box.y + box.height <= first_item_top - 12:
            section_level.add(element.id)
        elif (
            section_role == "blog_cards"
            and
            element.kind == ContentKind.BUTTON
            and box.y >= last_item_bottom + 120
        ):
            global_action.add(element.id)

    section_texts = sorted(
        (updated_by_id[element_id] for element_id in section_level),
        key=lambda item: (_element_box(item).y, _element_box(item).x),  # type: ignore[union-attr]
    )
    for index, element in enumerate(section_texts):
        max_section_font = max((_font_size(item) for item in section_texts), default=0)
        is_class_subtitle = (
            section_role == "class_cards"
            and index > 0
            and _font_size(element) >= max(18.0, max_section_font * 0.75)
        )
        updated_by_id[element.id] = element.model_copy(
            update={
                "kind": ContentKind.HEADING if index == 0 or is_class_subtitle else ContentKind.TEXT,
                "role": "section_title" if index == 0 else "subtitle" if is_class_subtitle else "section_body",
            }
        )

    for element_id in global_action:
        element = updated_by_id[element_id]
        updated_by_id[element_id] = element.model_copy(
            update={"kind": ContentKind.BUTTON, "role": "primary_action"}
        )

    assignments: list[list[ContentElement]] = [[anchor] for anchor in anchors]
    excluded = section_level | global_action | duplicate_ids | {anchor.id for anchor in anchors}
    section_box = _box(node)
    scale_x = max(1.0, section_box.width if section_box else 1.0)
    scale_y = max(1.0, section_box.height if section_box else 1.0)
    anchor_rows: list[list[int]] = []
    for anchor_index, box in sorted(enumerate(boxes), key=lambda item: (item[1].y, item[1].x)):
        tolerance = max(48.0, box.height * 0.35)
        row = next(
            (
                existing for existing in anchor_rows
                if abs(boxes[existing[0]].y - box.y) <= tolerance
            ),
            None,
        )
        if row is None:
            anchor_rows.append([anchor_index])
        else:
            row.append(anchor_index)
    anchor_rows.sort(key=lambda row: min(boxes[index].y for index in row))
    row_tops = [min(boxes[index].y for index in row) for row in anchor_rows]

    for element in updated_by_id.values():
        if element.id in excluded:
            continue
        box = _element_box(element)
        if box is None:
            continue
        center_x, center_y = box.x + box.width / 2, box.y + box.height / 2
        row_position = max(
            (index for index, top in enumerate(row_tops) if center_y >= top),
            default=0,
        )
        candidate_indices = anchor_rows[row_position]
        nearest = min(
            candidate_indices,
            key=lambda index: abs(center_x - (boxes[index].x + boxes[index].width / 2)) / scale_x,
        )
        assignments[nearest].append(element)

    group_id = f"{section_id}.group.1"
    items: list[RepeatGroupItem] = []
    bound_ids: set[str] = set()
    for index, assigned in enumerate(assignments, 1):
        anchor = anchors[index - 1]
        fields: dict[str, str | list[str]] = {"media": anchor.id}
        bound_ids.add(anchor.id)
        texts = sorted(
            (element for element in assigned if element.id != anchor.id and element.kind != ContentKind.IMAGE),
            key=lambda item: (_element_box(item).y, _element_box(item).x),  # type: ignore[union-attr]
        )
        actions = [element for element in texts if element.kind == ContentKind.BUTTON]
        values = [element for element in texts if element.kind != ContentKind.BUTTON]

        if section_role == "class_cards":
            title = max(values, key=lambda item: (_font_size(item), -len(str(item.value or ""))), default=None)
            body = max((item for item in values if item is not title), key=lambda item: len(str(item.value or "")), default=None)
            used_ids = {item.id for item in (title, body) if item is not None}
            tag = next((item for item in values if item.id not in used_ids), None)
            role_fields = (("title", title), ("tag", tag), ("body", body), ("action", actions[0] if actions else None))
        elif section_role == "team_grid":
            values.sort(key=lambda item: (_element_box(item).y, _element_box(item).x))  # type: ignore[union-attr]
            role_fields = (
                ("title", values[0] if values else None),
                ("role", values[1] if len(values) > 1 else None),
                ("body", values[2] if len(values) > 2 else None),
            )
        else:  # blog_cards
            title = max(values, key=lambda item: (_font_size(item), -len(str(item.value or ""))), default=None)
            body = max((item for item in values if item is not title), key=lambda item: len(str(item.value or "")), default=None)
            used_ids = {item.id for item in (title, body) if item is not None}
            remaining = [item for item in values if item.id not in used_ids]
            tag = remaining[0] if remaining else None
            meta_candidates = remaining[1:]
            meta = meta_candidates[0] if meta_candidates else None
            if meta is not None and len(meta_candidates) > 1:
                merged_ids = [item.id for item in meta_candidates]
                meta = meta.model_copy(
                    update={
                        "value": " | ".join(str(item.value or "").strip() for item in meta_candidates),
                        "provenance": [
                            provenance
                            for item in meta_candidates
                            for provenance in item.provenance
                        ],
                        "metadata": {
                            **meta.metadata,
                            "merged_source_element_ids": merged_ids,
                        },
                    }
                )
                updated_by_id[meta.id] = meta
                for merged in meta_candidates[1:]:
                    updated_by_id.pop(merged.id, None)
            role_fields = (
                ("title", title), ("tag", tag), ("body", body), ("meta", meta),
                ("action", actions[0] if actions else None),
            )

        for field, element in role_fields:
            if element is None:
                continue
            fields[field] = element.id
            bound_ids.add(element.id)
            kind = (
                ContentKind.HEADING if field == "title"
                else ContentKind.BUTTON if field == "action"
                else ContentKind.TEXT
            )
            role = {
                "title": "card_title",
                "tag": "tag",
                "body": "card_body",
                "meta": "meta",
                "role": "role",
                "action": "primary_action",
            }[field]
            updated_by_id[element.id] = element.model_copy(
                update={"kind": kind, "role": role, "group_id": group_id}
            )
        updated_by_id[anchor.id] = anchor.model_copy(
            update={
                "role": "person_media" if section_role == "team_grid" else "card_media",
                "group_id": group_id,
            }
        )
        items.append(
            RepeatGroupItem(
                id=f"{group_id}.item.{index}",
                fields=fields,
                provenance=anchor.provenance,
            )
        )

    updated = [
        updated_by_id[element.id]
        for element in content
        if element.id in updated_by_id
    ]
    group = RepeatGroup(
        id=group_id,
        kind=_group_kind(section_role),
        items=items,
        provenance=[
            _provenance(
                node, file_key=file_key, page_node_id=page_node_id,
                frame_node_id=frame_id, method=ObservationMethod.INFERRED,
                metadata={"inference": "geometric_repeat_ownership", "confidence": 0.82},
            )
        ],
    )
    return [group], updated


def _geometric_stats_group(
    node: Mapping[str, Any], *, section_id: str, content: list[ContentElement],
    file_key: str, page_node_id: str | None, frame_id: str,
) -> tuple[list[RepeatGroup], list[ContentElement]] | None:
    labels = sorted(
        (element for element in content if element.role == "stat_label" and _element_box(element)),
        key=lambda item: _element_box(item).x,  # type: ignore[union-attr]
    )
    values = sorted(
        (element for element in content if element.role == "stat_value" and _element_box(element)),
        key=lambda item: _element_box(item).x,  # type: ignore[union-attr]
    )
    if len(labels) < 2:
        return None
    group_id = f"{section_id}.group.1"
    available = set(range(len(values)))
    items: list[RepeatGroupItem] = []
    updated_by_id = {element.id: element for element in content}
    section_box = _box(node)
    max_distance = (section_box.width if section_box else 1000.0) / max(2, len(labels)) * 0.65
    for index, label in enumerate(labels, 1):
        label_box = _element_box(label)
        assert label_box is not None
        label_center = label_box.x + label_box.width / 2
        nearest = min(
            available,
            key=lambda value_index: abs(
                label_center
                - (_element_box(values[value_index]).x + _element_box(values[value_index]).width / 2)  # type: ignore[union-attr]
            ),
            default=None,
        )
        fields: dict[str, str] = {"label": label.id}
        updated_by_id[label.id] = label.model_copy(update={"group_id": group_id})
        if nearest is not None:
            value = values[nearest]
            value_box = _element_box(value)
            assert value_box is not None
            if abs(label_center - (value_box.x + value_box.width / 2)) <= max_distance:
                fields["value"] = value.id
                updated_by_id[value.id] = value.model_copy(update={"group_id": group_id})
                available.remove(nearest)
        items.append(
            RepeatGroupItem(
                id=f"{group_id}.item.{index}", fields=fields,
                provenance=label.provenance,
            )
        )
    group = RepeatGroup(
        id=group_id, kind=RepeatGroupKind.STAT, items=items,
        provenance=[_provenance(
            node, file_key=file_key, page_node_id=page_node_id,
            frame_node_id=frame_id, method=ObservationMethod.INFERRED,
            metadata={"inference": "geometric_stat_ownership", "confidence": 0.86},
        )],
    )
    return [group], [updated_by_id[element.id] for element in content]


def _marquee_group(
    node: Mapping[str, Any], *, section_id: str, content: list[ContentElement],
    file_key: str, page_node_id: str | None, frame_id: str,
) -> tuple[list[RepeatGroup], list[ContentElement]] | None:
    if len(content) != 1 or not isinstance(content[0].value, str):
        return None
    pieces = [piece.strip() for piece in re.split(r"\s{2,}", content[0].value) if piece.strip()]
    if len(pieces) < 2 or len({re.sub(r"\W+", "", piece).casefold() for piece in pieces}) != 1:
        return None
    group_id = f"{section_id}.group.1"
    expanded = [
        content[0].model_copy(
            update={
                "id": f"{content[0].id}.repeat.{index}",
                "value": piece,
                "kind": ContentKind.LIST_ITEM,
                "role": "body",
                "order": index - 1,
                "group_id": group_id,
                "metadata": {**content[0].metadata, "split_from_repeated_text": content[0].id},
            }
        )
        for index, piece in enumerate(pieces, 1)
    ]
    items = [
        RepeatGroupItem(
            id=f"{group_id}.item.{index}", fields={"body": element.id},
            provenance=element.provenance,
        )
        for index, element in enumerate(expanded, 1)
    ]
    return [
        RepeatGroup(
            id=group_id, kind=RepeatGroupKind.OTHER, items=items,
            provenance=[_provenance(
                node, file_key=file_key, page_node_id=page_node_id,
                frame_node_id=frame_id, method=ObservationMethod.INFERRED,
                metadata={"inference": "repeated_text_marquee", "confidence": 0.94},
            )],
        )
    ], expanded


def _repeat_groups(
    node: Mapping[str, Any], *, section_id: str, section_role: str,
    content: list[ContentElement], node_to_element: dict[str, str],
    file_key: str, page_node_id: str | None, frame_id: str,
) -> tuple[list[RepeatGroup], list[ContentElement]]:
    if node.get("_vanjaro_inferred_boundary") and section_role in {
        "class_cards", "team_grid", "blog_cards",
    }:
        inferred = _geometric_card_group(
            node, section_id=section_id, section_role=section_role,
            content=content, file_key=file_key, page_node_id=page_node_id,
            frame_id=frame_id,
        )
        if inferred is not None:
            return inferred
    if section_role == "marquee":
        inferred_marquee = _marquee_group(
            node, section_id=section_id, content=content, file_key=file_key,
            page_node_id=page_node_id, frame_id=frame_id,
        )
        if inferred_marquee is not None:
            return inferred_marquee
    if node.get("_vanjaro_inferred_boundary") and section_role == "stats":
        inferred_stats = _geometric_stats_group(
            node, section_id=section_id, content=content, file_key=file_key,
            page_node_id=page_node_id, frame_id=frame_id,
        )
        if inferred_stats is not None:
            return inferred_stats
    units = _repeat_units(node)
    item_element_ids: list[list[str]] = []
    item_nodes: list[Mapping[str, Any]] = []
    if units:
        for unit in units:
            ids = [node_to_element[str(item.get("id"))] for item in _walk(unit) if str(item.get("id")) in node_to_element]
            if ids:
                item_element_ids.append(ids)
                item_nodes.append(unit)
    else:
        eligible = [element for element in content if element.role != "section_title"]
        if section_role in {"logo_cloud", "call_to_action"}:
            role_filter = "logo_wordmark" if section_role == "logo_cloud" else "event_type"
            item_element_ids = [[element.id] for element in eligible if element.role == role_filter]
        elif section_role == "stats":
            current: list[str] = []
            for element in eligible:
                if element.role == "stat_value" and current:
                    item_element_ids.append(current)
                    current = []
                if element.role in {"stat_value", "stat_label"}:
                    current.append(element.id)
            if current:
                item_element_ids.append(current)
        elif section_role == "feature_cards":
            current = []
            for element in eligible:
                if element.role in {"card_media", "card_title"} and current and any(
                    next(item for item in content if item.id == identifier).role == element.role for identifier in current
                ):
                    item_element_ids.append(current)
                    current = []
                if element.role in {"card_media", "card_title", "card_body", "primary_action"}:
                    current.append(element.id)
            if current:
                item_element_ids.append(current)
        elif section_role == "testimonials":
            current = []
            for element in eligible:
                if element.role == "testimonial_quote" and current:
                    item_element_ids.append(current)
                    current = []
                if element.role in {"testimonial_quote", "author", "author_media"}:
                    current.append(element.id)
            if current:
                item_element_ids.append(current)

    if len(item_element_ids) < 2:
        return [], content

    group_id = f"{section_id}.group.1"
    by_id = {element.id: element for element in content}
    items: list[RepeatGroupItem] = []
    bound_ids: set[str] = set()
    for index, element_ids in enumerate(item_element_ids, 1):
        fields: dict[str, str | list[str]] = {}
        for element_id in element_ids:
            bound_ids.add(element_id)
            field = _field_name(by_id[element_id].role)
            previous = fields.get(field)
            if previous is None:
                fields[field] = element_id
            elif isinstance(previous, list):
                previous.append(element_id)
            else:
                fields[field] = [previous, element_id]
        unit = item_nodes[index - 1] if index - 1 < len(item_nodes) else node
        items.append(RepeatGroupItem(
            id=f"{group_id}.item.{index}", fields=fields,
            provenance=[_provenance(
                unit, file_key=file_key, page_node_id=page_node_id,
                frame_node_id=frame_id,
            )],
        ))
    updated = [element.model_copy(update={"group_id": group_id}) if element.id in bound_ids else element for element in content]
    group = RepeatGroup(
        id=group_id, kind=_group_kind(section_role), items=items,
        provenance=[_provenance(node, file_key=file_key, page_node_id=page_node_id, frame_node_id=frame_id)],
    )
    return [group], updated


def _section_text(section: Section) -> set[str]:
    return {
        str(element.value).strip().lower() for element in section.content
        if isinstance(element.value, str) and element.kind != ContentKind.IMAGE
    }


def _normalized_section_name(section: Section) -> str:
    name = str(section.metadata.get("figma_node_id", ""))
    if section.provenance and section.provenance[0].metadata.get("node_name"):
        name = str(section.provenance[0].metadata["node_name"])
    return _page_family(name)


def _pair_sections(base: list[Section], other: list[Section]) -> list[tuple[Section, Section, float, list[tuple[str, float]]]]:
    pairs: list[tuple[Section, Section, float, list[tuple[str, float]]]] = []
    unused = set(range(len(other)))
    for base_index, section in enumerate(base):
        scores: list[tuple[int, float]] = []
        base_text = _section_text(section)
        base_name = section.id.rsplit(".", 1)[-1]
        base_components = {p.component_id for p in section.provenance if p.component_id}
        for index in unused:
            candidate = other[index]
            score = 0.0
            if base_name == candidate.id.rsplit(".", 1)[-1]:
                score += 0.5
            common_components = base_components.intersection({p.component_id for p in candidate.provenance if p.component_id})
            if common_components:
                score += 0.2
            candidate_text = _section_text(candidate)
            if base_text or candidate_text:
                score += 0.2 * len(base_text.intersection(candidate_text)) / max(1, len(base_text.union(candidate_text)))
            score += 0.1 * max(0, 1 - abs(base_index - index) / max(1, len(base)))
            scores.append((index, round(score, 4)))
        scores.sort(key=lambda pair: (-pair[1], pair[0]))
        if scores and scores[0][1] >= 0.20:
            best_index, best_score = scores[0]
            alternatives = [(other[index].id, score) for index, score in scores[1:] if best_score - score <= 0.10]
            pairs.append((section, other[best_index], best_score, alternatives))
            unused.remove(best_index)
    return pairs


def _layout_changes(base: Section, other: Section) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for field in ("kind", "columns", "media_position", "alignment", "direction", "wrap"):
        before, after = getattr(base.layout, field), getattr(other.layout, field)
        if before != after:
            changes[field] = {"from": before.value if hasattr(before, "value") else before, "to": after.value if hasattr(after, "value") else after}
    return changes


_LOGO_ROLES = {"logo_bar", "logo_cloud", "partner_logos", "client_logos"}
_FIGMA_ACTION_ROLES = {"cta", "call_to_action", "contact", "contact_cta"}


def _infer_mobile(section: Section) -> dict[str, Any]:
    """Describe the section's layout *at* mobile, not only its delta.

    A responsive observation records the state at that breakpoint. Emitting
    only changed properties silently omits facts that are true at mobile
    regardless of the desktop value — a single-column section is still single
    column, and nothing overlaps on a 390px viewport.
    """

    changes: dict[str, Any] = {}
    columns = section.layout.columns
    # Logo bars keep a compact grid rather than becoming a very long
    # single-file list; everything else collapses to one column.
    target = 2 if section.semantic_role in _LOGO_ROLES else 1
    changes["columns"] = {"from": columns if columns else target, "to": target}
    if section.semantic_role in _LOGO_ROLES:
        changes["wrap"] = {"from": False, "to": True}
    if section.layout.direction == "row" or section.layout.kind == LayoutKind.SPLIT:
        changes["direction"] = {"from": section.layout.direction or "row", "to": "column"}
    if (
        section.semantic_role in _FIGMA_ACTION_ROLES
        and section.layout.media_position in {MediaPosition.LEFT, MediaPosition.RIGHT}
    ):
        # A dedicated action side-media split is deliberate, declared
        # structure — it leads with media on mobile regardless of content
        # order.
        changes["media_position"] = {"from": section.layout.media_position.value, "to": "top"}
    elif section.layout.media_position is MediaPosition.BOTTOM:
        # Media already trailing the copy stays trailing when the split stacks.
        changes["media_position"] = {"from": "bottom", "to": "bottom"}
    elif section.layout.media_position is MediaPosition.TOP:
        changes["media_position"] = {"from": "top", "to": "top"}
    else:
        # Any other desktop reading — including a geometry-inferred side
        # media position on a non-action section such as a hero — says
        # nothing about mobile order. Horizontal position is the wrong
        # signal (a photo placed right of the copy can still lead on
        # mobile), so stacking follows declared content order instead.
        stacked = _stacked_media_position(section)
        if stacked is not None:
            from_value = (
                section.layout.media_position.value
                if section.layout.media_position is not MediaPosition.NONE
                else "none"
            )
            changes["media_position"] = {"from": from_value, "to": stacked}
    if section.layout.kind == LayoutKind.FREEFORM:
        # Overlapping decoration cannot survive a 390px viewport, whether or
        # not the desktop layout overlapped.
        overlapped = bool(section.layout.metadata.get("overlap"))
        changes["overlap"] = {"from": overlapped, "to": False}
    elif section.layout.kind == LayoutKind.SPLIT and "text_overlaps_media" in section.layout.metadata:
        # A geometry-inferred side-media split (e.g. text partially overlapping
        # a dominant photo) records its own bounded overlap evidence separately
        # from the freeform "overlap" key above. That evidence must carry
        # through here too: once the section stacks to one column, whatever
        # actual overlap existed cannot persist. Sections with no such key —
        # unknown geometry, or a non-overlapping split — make no claim either way.
        overlapped = bool(section.layout.metadata["text_overlaps_media"])
        changes["overlap"] = {"from": overlapped, "to": False}
    if section.semantic_role in _FIGMA_ACTION_ROLES:
        changes.setdefault("direction", {"from": "horizontal", "to": "vertical"})
        if _has_action_element(section):
            changes["button_width"] = {"from": "auto", "to": "100%"}
    return changes or {"review_required": True}


_TEXTUAL_KINDS = frozenset(
    {
        ContentKind.HEADING,
        ContentKind.TEXT,
        ContentKind.QUOTE,
        ContentKind.BUTTON,
        ContentKind.LINK,
        ContentKind.STAT,
    }
)


def _stacked_media_position(section: Section) -> str | None:
    """Derive where media lands once a section collapses to one column.

    A desktop composition with no horizontal media position — an auto-layout
    frame or a freeform collage — still has a defined mobile order, because
    stacking preserves content order. That is the same stacking model the
    template capabilities declare as `stacking_order: "source"`, so deriving
    from it here keeps the adapter and the templates on one rule.

    Content order here is the declared child order of the Figma node, which is
    the order a designer arranged the layers in — and stacking preserves it.

    Geometry is deliberately not used, for two independent reasons. Horizontal
    position is the wrong signal: `riverkind.hero` places its image to the
    right of the copy (x=680 against x=120) and still leads with it on mobile,
    so an x-position rule would stack it to the bottom and be wrong. Vertical
    position is simply unavailable: auto-layout frames such as `orbit.hero`
    record no per-element bounds at all, so a y-position rule would have
    nothing to read.

    Media interleaved with copy returns None, so the observation stays
    unavailable rather than guessed.
    """

    media = [
        element.order
        for element in section.content
        if element.kind in {ContentKind.IMAGE, ContentKind.VIDEO}
    ]
    text = [
        element.order for element in section.content if element.kind in _TEXTUAL_KINDS
    ]
    if not media or not text:
        return None
    if max(media) < min(text):
        return "top"
    if min(media) > max(text):
        return "bottom"
    return None


def _infer_tablet(section: Section) -> dict[str, Any]:
    """Halve wide grids at tablet; narrower layouts survive unchanged."""

    changes: dict[str, Any] = {}
    columns = section.layout.columns
    if columns and columns > 2:
        changes["columns"] = {"from": columns, "to": 2}
    return changes


def _has_action_element(section: Section) -> bool:
    return any(
        element.kind in {ContentKind.BUTTON, ContentKind.LINK}
        for element in section.content
    )


def _typography_tokens(pages: list[Page], node_index: Mapping[str, Mapping[str, Any]], file_key: str, font_sources: Mapping[str, str] | None, warnings: list[DesignWarning]) -> list[TypographyToken]:
    tokens: dict[tuple[Any, ...], TypographyToken] = {}
    warned_fonts: set[str] = set()
    for page in pages:
        for section in page.sections:
            for element in section.content:
                node_id = str(element.attributes.get("figma_node_id", ""))
                node = node_index.get(node_id)
                if not node or node.get("type") != "TEXT":
                    continue
                style = node.get("style") or {}
                family = style.get("fontFamily")
                size = style.get("fontSize")
                weight = style.get("fontWeight")
                role = "body"
                if element.role == "section_title":
                    role = "display" if section.semantic_role == "hero" or (isinstance(size, (int, float)) and size >= 40) else "heading"
                elif element.kind == ContentKind.BUTTON:
                    role = "button"
                elif element.role in {"stat_label", "event_type", "eyebrow"}:
                    role = "label"
                elif section.semantic_role == "navigation":
                    role = "menu"
                elif _is_decorative(node):
                    role = "decorative"
                provenance = element.provenance
                key = (role, family, size, weight, style.get("lineHeightPx"), style.get("letterSpacing"))
                tokens.setdefault(key, TypographyToken(
                    role=role, font_family=str(family) if family else None,
                    font_size=f"{size:g}px" if isinstance(size, (int, float)) else None,
                    font_weight=weight,
                    line_height=f"{style['lineHeightPx']:g}px" if isinstance(style.get("lineHeightPx"), (int, float)) else None,
                    letter_spacing=f"{style['letterSpacing']:g}px" if isinstance(style.get("letterSpacing"), (int, float)) else None,
                    provenance=provenance,
                ))
                if family and family not in (font_sources or {}) and family not in warned_fonts:
                    warned_fonts.add(str(family))
                    warnings.append(DesignWarning(
                        code="FIGMA_FONT_SOURCE_UNRESOLVED",
                        message=f"Font family {family!r} has no registered source; supply font_sources before build.",
                        path=f"tokens.typography[{role}]", provenance=provenance,
                    ))
    return [tokens[key] for key in sorted(tokens, key=lambda item: tuple(str(part) for part in item))]


def _color_tokens(roots: list[dict[str, Any]], file_key: str) -> dict[str, TokenValue]:
    colors: dict[str, TokenValue] = {}
    for root in roots:
        for node in _walk(root):
            for fill in node.get("fills") or []:
                if not isinstance(fill, Mapping) or fill.get("type") != "SOLID" or fill.get("visible") is False:
                    continue
                color = fill.get("color")
                if not isinstance(color, Mapping):
                    continue
                channels = [round(max(0.0, min(1.0, float(color.get(key, 0)))) * 255) for key in ("r", "g", "b")]
                value = "#" + "".join(f"{channel:02x}" for channel in channels)
                colors.setdefault(value, TokenValue(value=value, provenance=[]))
    return {f"color-{index:02d}": colors[value] for index, value in enumerate(sorted(colors), 1)}


def analyze_figma_document(
    payload: Mapping[str, Any], *, file_key: str, node_id: str | None = None,
    image_fill_urls: Mapping[str, str] | None = None,
    image_resolver: ImageFillResolver | None = None,
    vector_resolver: VectorResolver | None = None,
    font_sources: Mapping[str, str] | None = None,
    captured_at: datetime | None = None,
    adapter_version: str = _ADAPTER_VERSION,
) -> DesignDocument:
    """Analyze an already-fetched Figma payload into Design Document v1.

    ``image_fill_urls`` should be the result of Figma's original image-fill
    endpoint. ``image_resolver`` and ``vector_resolver`` are lazy alternatives;
    neither hook performs network I/O unless the caller chooses to do so.
    """

    roots = _root_documents(payload)
    frames = _page_frames(roots, node_id)
    warnings: list[DesignWarning] = []
    families: dict[str, list[tuple[str | None, dict[str, Any]]]] = defaultdict(list)
    for canvas_id, frame in frames:
        families[_page_family(str(frame.get("name", "Page")))].append((canvas_id, frame))

    pages: list[Page] = []
    all_registries: list[_AssetRegistry] = []
    for family_name, variants in sorted(families.items()):
        variants.sort(key=lambda item: ({BreakpointName.DESKTOP: 0, BreakpointName.TABLET: 1, BreakpointName.MOBILE: 2}[_breakpoint(item[1])], str(item[1].get("id"))))
        base_canvas, base_frame = variants[0]
        desktop_variant = next((item for item in variants if _breakpoint(item[1]) == BreakpointName.DESKTOP), None)
        if desktop_variant is not None:
            base_canvas, base_frame = desktop_variant
        base_breakpoint = _breakpoint(base_frame)
        page_id = f"figma-page-{_safe(family_name)}-{_safe(str(base_frame.get('id')))}"
        registry = _AssetRegistry(
            file_key=file_key, page_node_id=base_canvas,
            image_fill_urls=image_fill_urls, image_resolver=image_resolver,
            vector_resolver=vector_resolver, warnings=warnings,
        )
        all_registries.append(registry)
        sections = [
            _extract_section(
                section_node, page_frame=base_frame, page_node_id=base_canvas,
                file_key=file_key, page_id=page_id, order=index,
                viewport=base_breakpoint, assets=registry,
            )
            for index, section_node in enumerate(_segment_frame(base_frame))
        ]

        observed_breakpoints = {_breakpoint(frame) for _, frame in variants}
        for canvas_id, variant in variants:
            breakpoint = _breakpoint(variant)
            if variant is base_frame:
                continue
            variant_registry = registry
            other_sections = [
                _extract_section(
                    section_node, page_frame=variant, page_node_id=canvas_id,
                    file_key=file_key, page_id=f"paired-{page_id}", order=index,
                    viewport=breakpoint, assets=variant_registry,
                )
                for index, section_node in enumerate(_segment_frame(variant))
            ]
            paired = _pair_sections(sections, other_sections)
            for base_section, paired_section, confidence, alternatives in paired:
                changes = _layout_changes(base_section, paired_section)
                observation = ResponsiveObservation(
                    breakpoint=breakpoint,
                    viewport=_BREAKPOINT_VIEWPORTS[breakpoint],
                    status=EvidenceStatus.OBSERVED,
                    layout_changes=changes,
                    provenance=paired_section.provenance,
                )
                metadata = dict(base_section.metadata)
                metadata.setdefault("responsive_pairing", {})[breakpoint.value] = {
                    "paired_section_id": paired_section.id,
                    "confidence": confidence,
                    "alternatives": [{"section_id": item_id, "score": score} for item_id, score in alternatives],
                }
                base_section.responsive.append(observation)
                base_section.metadata = metadata
                if alternatives:
                    warnings.append(DesignWarning(
                        code="FIGMA_RESPONSIVE_PAIR_AMBIGUOUS",
                        message=f"Responsive section pairing for {base_section.id!r} is ambiguous.",
                        path=base_section.id,
                        provenance=paired_section.provenance,
                    ))

        if BreakpointName.MOBILE not in observed_breakpoints:
            page_provenance = [_provenance(
                base_frame, file_key=file_key, page_node_id=base_canvas,
                frame_node_id=str(base_frame.get("id")), viewport=base_breakpoint,
            )]
            warnings.append(DesignWarning(
                code="FIGMA_MOBILE_FRAME_MISSING",
                message=f"Page {family_name!r} has no mobile frame; mobile behavior is inferred and requires review.",
                path=page_id, provenance=page_provenance,
            ))
            for section in sections:
                tablet_changes = _infer_tablet(section)
                if tablet_changes and BreakpointName.TABLET not in observed_breakpoints:
                    section.responsive.append(ResponsiveObservation(
                        breakpoint=BreakpointName.TABLET,
                        viewport=_BREAKPOINT_VIEWPORTS[BreakpointName.TABLET],
                        status=EvidenceStatus.INFERRED,
                        layout_changes=tablet_changes,
                        provenance=[Provenance(
                            source_kind=SourceKind.FIGMA, method=ObservationMethod.INFERRED,
                            viewport=BreakpointName.TABLET, file_key=file_key,
                            page_node_id=base_canvas, frame_node_id=str(base_frame.get("id")),
                            element_node_id=str(section.metadata.get("figma_node_id")),
                            metadata={"inference": "desktop_to_tablet_default", "confidence": 0.55},
                        )],
                    ))
                section.responsive.append(ResponsiveObservation(
                    breakpoint=BreakpointName.MOBILE,
                    viewport=_BREAKPOINT_VIEWPORTS[BreakpointName.MOBILE],
                    status=EvidenceStatus.INFERRED,
                    layout_changes=_infer_mobile(section),
                    provenance=[Provenance(
                        source_kind=SourceKind.FIGMA, method=ObservationMethod.INFERRED,
                        viewport=BreakpointName.MOBILE, file_key=file_key,
                        page_node_id=base_canvas, frame_node_id=str(base_frame.get("id")),
                        element_node_id=str(section.metadata.get("figma_node_id")),
                        metadata={"inference": "desktop_to_mobile_default", "confidence": 0.55},
                    )],
                ))

        # One frame-level provenance record per *observed* variant -- not just
        # the base frame, and not only variants whose sections managed to
        # pair with the base.  Each record carries the frame node's own
        # bounds (via `_box`), which is the only place downstream capture
        # planning can learn a Figma frame's real, directly-observed
        # dimensions; a section's bounds are section-local and must never be
        # substituted for it.
        frame_provenance = [_provenance(
            base_frame, file_key=file_key, page_node_id=base_canvas,
            frame_node_id=str(base_frame.get("id")), viewport=base_breakpoint,
        )]
        for canvas_id, variant in variants:
            if variant is base_frame:
                continue
            frame_provenance.append(_provenance(
                variant, file_key=file_key, page_node_id=canvas_id,
                frame_node_id=str(variant.get("id")), viewport=_breakpoint(variant),
            ))

        pages.append(Page(
            id=page_id, source_reference=str(base_frame.get("id")),
            title=str(base_frame.get("name") or family_name.title()), slug=_safe(family_name),
            sections=sections,
            breakpoints=sorted(observed_breakpoints, key=lambda item: {BreakpointName.DESKTOP: 0, BreakpointName.TABLET: 1, BreakpointName.MOBILE: 2}[item]),
            navigation_visibility=NavigationVisibility.UNKNOWN,
            provenance=frame_provenance,
            metadata={"figma_page_family": family_name},
        ))

    # Registries are page-scoped during extraction but asset IDs are ref-based;
    # merge duplicates across pages while retaining every owner provenance.
    merged_assets: dict[str, AssetRecord] = {}
    for registry in all_registries:
        for asset in registry.records():
            previous = merged_assets.get(asset.id)
            if previous is None:
                merged_assets[asset.id] = asset
            else:
                owner_ids = list(previous.metadata.get("owner_node_ids", []))
                for owner in asset.metadata.get("owner_node_ids", []):
                    if owner not in owner_ids:
                        owner_ids.append(owner)
                merged_assets[asset.id] = previous.model_copy(update={
                    "role": AssetRole.EDITORIAL if AssetRole.EDITORIAL in {previous.role, asset.role} else AssetRole.DECORATIVE,
                    "provenance": previous.provenance + asset.provenance,
                    "metadata": {**previous.metadata, "owner_node_ids": owner_ids},
                })

    node_index = {str(node.get("id")): node for root in roots for node in _walk(root) if node.get("id") is not None}
    tokens = DesignTokens(
        colors=_color_tokens(roots, file_key),
        typography=_typography_tokens(pages, node_index, file_key, font_sources, warnings),
        raw={"source": "figma_api", "font_sources": dict(font_sources or {})},
    )
    section_confidences = [section.role_confidence for page in pages for section in page.sections]
    captured = captured_at or datetime.now(timezone.utc)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA, identifier=file_key, captured_at=captured,
            adapter_version=adapter_version,
            metadata={"figma_file_name": str(payload.get("name", "")), "requested_node_id": node_id},
        ),
        tokens=tokens,
        assets=[merged_assets[key] for key in sorted(merged_assets)],
        pages=pages,
        warnings=warnings,
        analysis=DesignAnalysis(
            section_confidence_mean=sum(section_confidences) / len(section_confidences) if section_confidences else 0,
            unsupported_traits=sorted({warning.code for warning in warnings}),
            metadata={"page_count": len(pages), "section_count": len(section_confidences)},
        ),
    )
