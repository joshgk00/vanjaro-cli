"""Design Document to Composition Plan v2 planning and semantic binding."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from vanjaro_cli.design.composition import (
    BlockType,
    CompositionPlan,
    CompositionPlanEntry,
    IssueSeverity,
    MatchAlternative,
    OverrideAudit,
    PlanBlock,
    PlanMatch,
    PlanPolicy,
    PlanSummary,
    SemanticBinding,
    SimplificationDecision,
    SimplificationKind,
)
from vanjaro_cli.design.matcher import MatchContext, match_section, score_template
from vanjaro_cli.design.models import (
    AssetRecord,
    ContentElement,
    ContentKind,
    DesignDocument,
    InteractionKind,
    Page,
    RepeatGroup,
    RepeatGroupItem,
    Section,
    StyleProperty,
)
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.semantics import (
    binding_field_aliases,
    section_capability_aliases,
    semantic_slot_types,
)
from vanjaro_cli.design.template_catalog import (
    TemplateCatalogEntry,
    load_template_catalog,
    load_template_data,
)
from vanjaro_cli.design.element_style_transport import (
    emit_element_style_payload,
    translate_element_styles,
)
from vanjaro_cli.design.native_style_transport import (
    NativeStyleTransportError,
    apply_important_css_properties,
    build_native_style_report,
    validate_native_class_actions,
)
from vanjaro_cli.design.style_transport import StyleTransportError, validate_style_payload
from vanjaro_cli.design.style_translation import (
    StyleTranslationConfig,
    TranslationLayer,
    translate_responsive_observations,
    translate_style_set,
)
from vanjaro_cli.utils.block_compose import enumerate_slots
from vanjaro_cli.utils.image_links import is_safe_link_href


_PLACEHOLDER_RE = re.compile(
    r"(?:placehold\.co|placeholder(?:\s+(?:text|image))?|lorem\s+ipsum|example\.com)",
    re.IGNORECASE,
)

_KIND_SLOT_TYPES: dict[ContentKind, tuple[str, ...]] = {
    ContentKind.HEADING: ("heading", "text"),
    ContentKind.TEXT: ("text", "heading"),
    ContentKind.IMAGE: ("image",),
    ContentKind.BUTTON: ("button", "link"),
    ContentKind.LINK: ("link", "button"),
    ContentKind.LIST: ("list-item", "text"),
    ContentKind.LIST_ITEM: ("list-item", "text"),
    ContentKind.QUOTE: ("text",),
    ContentKind.STAT: ("heading", "text"),
    ContentKind.VIDEO: ("video", "image"),
    ContentKind.FORM_PLACEHOLDER: ("form",),
    ContentKind.OTHER: ("text", "heading"),
}

_DEFAULT_MODIFIER_PROPERTIES = {
    StyleProperty.BACKGROUND_COLOR: "band-color",
    StyleProperty.PADDING: "spacing",
    StyleProperty.MARGIN: "spacing",
    StyleProperty.BORDER_RADIUS: "card-radius",
    StyleProperty.BOX_SHADOW: "card-shadow",
    StyleProperty.COLUMN_GAP: "column-gap",
    StyleProperty.OBJECT_POSITION: "image-focal-point",
    StyleProperty.TEXT_ALIGN: "text-alignment",
}


class PlanningError(ValueError):
    """Raised for actionable semantic-binding or planning failures."""

    def __init__(self, issues: Iterable[str]):
        self.issues = tuple(issues)
        super().__init__("Composition planning failed:\n- " + "\n- ".join(self.issues))


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value))


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


_URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.IGNORECASE)


def _page_usable_source(candidate: str) -> str:
    """Return a reference a built page can actually load, or an empty string.

    Only a relative path or a data URI works in a portal page. An absolute
    source is either hotlinking someone else's origin (http/https/figma) or
    unloadable from a served document — `file://` most of all, which a browser
    refuses outright and which reached a live pilot page as
    `Not allowed to load local resource`, one console error per visitor.

    Blanking here is what makes the drop visible: an empty source is reported
    by the binding sink as an asset that resolved to nothing, rather than being
    shipped as a URL that can never load.
    """

    text = candidate.strip()
    if not text:
        return ""
    match = _URL_SCHEME.match(text)
    if match is None:
        return text
    return text if text.casefold().startswith("data:") else ""


def _asset_value(element: ContentElement, assets: Mapping[str, AssetRecord]) -> tuple[str, str]:
    asset = assets.get(element.asset_id or "")
    if asset is None:
        candidate = _string_value(element.attributes.get("src") or element.value)
        return (
            _page_usable_source(candidate),
            _string_value(element.attributes.get("alt") or ""),
        )
    location = asset.local_path or _page_usable_source(asset.source_url or "")
    alt = asset.alt_text or _string_value(element.attributes.get("alt") or "")
    return location, alt


def _unmet_reason(
    semantic_field: str,
    candidates: Sequence[ContentElement],
    assets: Mapping[str, AssetRecord],
) -> str:
    """Explain why a required field bound nothing.

    "Missing or has no slot" was reported for a section that had the element
    and only lacked its bytes: a live page's images are remote until they are
    acquired, and a remote URL is deliberately refused rather than hotlinked.
    Reporting the wrong cause sent a reader looking for absent content.
    """

    if not candidates:
        return f"required field {semantic_field!r} is missing or has no slot"
    unacquired = [
        assets[element.asset_id].source_url
        for element in candidates
        if element.asset_id and element.asset_id in assets and not assets[element.asset_id].local_path
    ]
    if unacquired:
        return (
            f"required field {semantic_field!r} has {len(unacquired)} value(s) whose asset "
            "was never acquired, so nothing loadable can be bound"
        )
    return f"required field {semantic_field!r} is present but no value could be bound"


def _form_fields(section: Section) -> tuple[dict[str, Any], ...]:
    """Collect the form a section had, for the build to mark rather than rebuild."""

    return tuple(
        dict(element.attributes)
        for element in section.content
        if element.kind is ContentKind.FORM_PLACEHOLDER
    )


def _interaction_reason(kind: InteractionKind) -> str:
    """Explain an unrepresentable interaction in the terms that decided it.

    A contact form blocked with "selected template does not declare a native
    representation", which reads like a template shortfall to be fixed by
    picking a better template. It is not: a form is never rebuilt as HTML at
    all, so no template can or should represent one. Saying that plainly is the
    difference between a reader looking for a better match and a reader
    reaching for the forms plugin.
    """

    if kind is InteractionKind.FORM:
        return (
            "a form is never rebuilt from a template; it needs a placeholder "
            "and a hand-built form"
        )
    return "selected template does not declare a native representation"


def _slot_queues(entry: TemplateCatalogEntry) -> tuple[dict[str, deque[str]], dict[str, str]]:
    data = load_template_data(entry)
    slots = enumerate_slots(data["template"])
    queues: dict[str, deque[str]] = defaultdict(deque)
    defaults: dict[str, str] = {}
    for slot in slots:
        key = slot["key"]
        queues[slot["type"]].append(key)
        defaults[key] = _string_value(slot.get("value"))
    return queues, defaults


def _clear_slots(entry: TemplateCatalogEntry, bindings: Sequence[SemanticBinding]) -> tuple[str, ...]:
    """Clear every unbound visitor-content slot so template sample copy cannot leak."""

    data = load_template_data(entry)
    bound = {binding.slot for binding in bindings}
    return tuple(
        slot["key"]
        for slot in enumerate_slots(data["template"])
        if slot["key"] not in bound and slot["key"] != "background_image"
    )


def _take_slot(queues: dict[str, deque[str]], types: Sequence[str]) -> str | None:
    for slot_type in types:
        if queues.get(slot_type):
            return queues[slot_type].popleft()
    return None


def _discard_semantic_slot(queues: dict[str, deque[str]], semantic_field: str) -> None:
    """Reserve an absent repeat-item field so later items keep their visual owner."""

    leaf = semantic_field.rsplit(".", 1)[-1]
    slot = _take_slot(queues, semantic_slot_types(leaf) or ("text", "heading"))
    if slot is None:
        return
    if slot.startswith("image_") and slot.endswith("_src"):
        base = slot.removesuffix("_src")
        for suffix in ("_alt", "_href"):
            paired = base + suffix
            if paired in queues.get("image", ()):
                queues["image"].remove(paired)
    elif slot.startswith(("button_", "link_")) and not slot.endswith("_href"):
        slot_type = slot.split("_", 1)[0]
        paired = slot + "_href"
        if paired in queues.get(slot_type, ()):
            queues[slot_type].remove(paired)


def _aliases(field: str) -> tuple[str, ...]:
    return binding_field_aliases(field)


def _element_matches(element: ContentElement, field: str) -> bool:
    aliases = {_normalized(value) for value in _aliases(field)}
    return _normalized(element.role) in aliases or _normalized(element.kind.value) in aliases


def _element_match_rank(element: ContentElement, field: str) -> int:
    """Prefer an observed semantic role over a broad content-kind fallback."""

    aliases = {_normalized(value) for value in _aliases(field)}
    field_name = _normalized(field)
    role_fields = {
        _normalized(value) for value in section_capability_aliases(element.role)
    }
    return 0 if _normalized(element.role) in aliases or field_name in role_fields else 1


def _background_link_blocker(element: ContentElement) -> str | None:
    """An image with a retained destination cannot silently lose it to a background slot.

    A background-only slot has no native clickable owner: unlike an
    ``image_N_src`` slot, there is no anchor to wrap. Rather than binding the
    image and quietly dropping its destination, this is reported the same way
    an unsafe URL is -- as an actionable blocker, not a warning the plan can
    still approve.
    """
    href = _string_value(element.attributes.get("href"))
    if not href or _is_placeholder(href):
        return None
    return (
        f"image {element.id} has a retained destination but its selected slot is a "
        "background image, which has no native clickable owner to carry it"
    )


def _bind_element(
    *,
    semantic_field: str,
    element: ContentElement,
    queues: dict[str, deque[str]],
    owned_slots: deque[str] | None = None,
    assets: Mapping[str, AssetRecord],
    item_id: str | None,
    dropped: list[str] | None = None,
    issues: list[str] | None = None,
) -> list[SemanticBinding]:
    leaf = semantic_field.rsplit(".", 1)[-1]
    preferred = semantic_slot_types(leaf) or _KIND_SLOT_TYPES[element.kind]
    is_image = element.kind == ContentKind.IMAGE or "image" in preferred
    if is_image:
        src, alt = _asset_value(element, assets)
        if not src or _is_placeholder(src):
            # A designed image reaching an editable slot and still not binding
            # is a source problem, not a library gap. The distinction matters:
            # a missing slot is fixed in the template catalog, an unresolvable
            # asset upstream. Neither is visible in the fidelity score, because
            # the media dimension needs a sample on both sides.
            if dropped is not None:
                dropped.append(
                    f"image {element.id} was not bound: "
                    + (
                        f"its source is a placeholder ({src})"
                        if src
                        else "its asset resolved to no usable source"
                    )
                )
            return []
    else:
        value = _string_value(element.value)
        if not value or _is_placeholder(value):
            return []

    # Preserve semantic intent first; fall back to the observed element kind.
    slot = (
        owned_slots.popleft()
        if owned_slots is not None and owned_slots
        else _take_slot(queues, preferred + _KIND_SLOT_TYPES[element.kind])
    )
    if slot is None:
        return []

    if is_image or slot.startswith("image_"):
        if slot == "background_image":
            blocker = _background_link_blocker(element)
            if blocker is not None and issues is not None:
                issues.append(blocker)
            return [
                SemanticBinding(
                    semantic_field=semantic_field,
                    slot=slot,
                    source_element_ids=(element.id,),
                    value=src,
                    item_id=item_id,
                )
            ]
        if not slot.endswith("_src"):
            match = re.match(r"image_(\d+)", slot)
            slot = f"image_{match.group(1)}_src" if match else slot
        result = [
            SemanticBinding(
                semantic_field=semantic_field,
                slot=slot,
                source_element_ids=(element.id,),
                value=src,
                item_id=item_id,
            )
        ]
        alt_slot = slot.removesuffix("_src") + "_alt"
        href_slot = slot.removesuffix("_src") + "_href"
        # Attribute slots are present independently in enumerate_slots.
        if alt_slot in queues.get("image", ()):
            queues["image"].remove(alt_slot)
        if href_slot in queues.get("image", ()):
            queues["image"].remove(href_slot)
        if alt:
            result.append(
                SemanticBinding(
                    semantic_field=f"{semantic_field}.alt",
                    slot=alt_slot,
                    source_element_ids=(element.id,),
                    value=alt,
                    item_id=item_id,
                )
            )
        href = _string_value(element.attributes.get("href"))
        if href and not _is_placeholder(href):
            if is_safe_link_href(href):
                result.append(
                    SemanticBinding(
                        semantic_field=f"{semantic_field}.href",
                        slot=href_slot,
                        source_element_ids=(element.id,),
                        value=href,
                        item_id=item_id,
                    )
                )
            elif issues is not None:
                issues.append(
                    f"image {element.id} has an unsafe link destination that cannot be bound"
                )
        return result

    result = [
        SemanticBinding(
            semantic_field=semantic_field,
            slot=slot,
            source_element_ids=(element.id,),
            value=value,
            item_id=item_id,
        )
    ]
    if slot.startswith(("button_", "link_")):
        href = _string_value(element.attributes.get("href") or element.attributes.get("url"))
        href_slot = slot + "_href"
        slot_type = slot.split("_", 1)[0]
        if href_slot in queues.get(slot_type, ()):
            queues[slot_type].remove(href_slot)
        if href and not _is_placeholder(href):
            # A button/link's destination is validated the same way an
            # image's retained href already is: an unsafe scheme must become
            # an actionable planning blocker, never a silently dropped or
            # silently executed native href.
            if is_safe_link_href(href):
                result.append(
                    SemanticBinding(
                        semantic_field=f"{semantic_field}.href",
                        slot=href_slot,
                        source_element_ids=(element.id,),
                        value=href,
                        item_id=item_id,
                    )
                )
            elif issues is not None:
                issues.append(
                    f"{element.id} has an unsafe link destination that cannot be bound"
                )
    return result


def _item_elements(
    item: RepeatGroupItem, elements: Mapping[str, ContentElement], semantic_field: str
) -> list[ContentElement]:
    normalized_fields = {_normalized(key): value for key, value in item.fields.items()}
    identifiers: str | list[str] | None = None
    for alias in _aliases(semantic_field):
        if _normalized(alias) in normalized_fields:
            identifiers = normalized_fields[_normalized(alias)]
            break
    if identifiers is None:
        return []
    ids = [identifiers] if isinstance(identifiers, str) else identifiers
    return [elements[element_id] for element_id in ids if element_id in elements]


def _best_group(section: Section, entry: TemplateCatalogEntry) -> RepeatGroup | None:
    if entry.capabilities.repeat_group is None or not section.groups:
        return None
    desired = _normalized(entry.capabilities.repeat_group.kind)
    return max(
        section.groups,
        key=lambda group: (
            _normalized(group.kind.value) == desired,
            len(group.items),
            group.id,
        ),
    )


def _is_repeat_field(field: str) -> bool:
    return field.startswith(("item.", "column."))


def _conceptual_slots(queue: deque[str], slot_type: str) -> list[str]:
    if slot_type in {"button", "link"}:
        return [slot for slot in queue if not slot.endswith("_href")]
    if slot_type == "image":
        return [slot for slot in queue if slot.endswith("_src")]
    return list(queue)


def _append_virtual_slots(
    queues: dict[str, deque[str]], slot_type: str, count: int
) -> None:
    if count <= 0:
        return
    all_slots = [slot for queue in queues.values() for slot in queue]
    pattern = re.compile(rf"^{re.escape(slot_type)}_(\d+)")
    next_index = max(
        (int(match.group(1)) for slot in all_slots if (match := pattern.match(slot))),
        default=0,
    ) + 1
    for index in range(next_index, next_index + count):
        if slot_type == "image":
            queues[slot_type].extend(
                (f"image_{index}_src", f"image_{index}_alt", f"image_{index}_href")
            )
        elif slot_type in {"button", "link"}:
            queues[slot_type].extend(
                (f"{slot_type}_{index}", f"{slot_type}_{index}_href")
            )
        else:
            queues[slot_type].append(f"{slot_type}_{index}")


def _ensure_repeat_slots(
    queues: dict[str, deque[str]],
    item_fields: Sequence[tuple[str, str]],
    group: RepeatGroup,
    elements: Mapping[str, ContentElement],
    entry: TemplateCatalogEntry,
) -> None:
    repeat = entry.capabilities.repeat_group
    if repeat is None or not repeat.expandable:
        return
    needed: dict[str, int] = defaultdict(int)
    for semantic_field, _requirement in item_fields:
        leaf = semantic_field.rsplit(".", 1)[-1]
        candidates = semantic_slot_types(leaf) or ("text", "heading")
        slot_type = next(
            (candidate for candidate in candidates if _conceptual_slots(queues.get(candidate, deque()), candidate)),
            candidates[0],
        )
        for item in group.items:
            needed[slot_type] += max(1, len(_item_elements(item, elements, semantic_field)))
    for slot_type, required in needed.items():
        available = len(_conceptual_slots(queues.get(slot_type, deque()), slot_type))
        _append_virtual_slots(queues, slot_type, required - available)


def bind_section(
    section: Section,
    entry: TemplateCatalogEntry,
    *,
    assets: Mapping[str, AssetRecord] | None = None,
    dropped: list[str] | None = None,
) -> tuple[SemanticBinding, ...]:
    """Bind only capability-declared semantic fields to real template slots.

    ``dropped`` collects reasons a designed element produced no binding, so a
    plan can report content that silently failed to reach the build.
    """

    if entry.capabilities.physical_fields:
        return _bind_section_physical(section, entry, assets=assets, dropped=dropped)

    asset_map = assets or {}
    elements = {element.id: element for element in section.content}
    queues, _ = _slot_queues(entry)
    bindings: list[SemanticBinding] = []
    issues: list[str] = []
    group = _best_group(section, entry)
    grouped_ids = {
        element_id
        for source_group in section.groups
        for item in source_group.items
        for value in item.fields.values()
        for element_id in ([value] if isinstance(value, str) else value)
    }

    item_fields = [
        (field, requirement)
        for field, requirement in entry.capabilities.fields.items()
        if _is_repeat_field(field)
    ]
    section_fields = [
        (field, requirement)
        for field, requirement in entry.capabilities.fields.items()
        if not _is_repeat_field(field)
    ]
    used_section_ids: set[str] = set()

    # Section-owned slots precede repeat items in the template component tree.
    # Missing optional section fields still reserve their physical slot.
    for semantic_field, requirement in section_fields:
        candidates = sorted(
            (
                element
                for element in section.content
                if element.id not in grouped_ids and _element_matches(element, semantic_field)
            ),
            key=lambda item: (_element_match_rank(item, semantic_field), item.order, item.id),
        )
        if candidates:
            best_rank = _element_match_rank(candidates[0], semantic_field)
            candidates = [
                candidate
                for candidate in candidates
                if _element_match_rank(candidate, semantic_field) == best_rank
            ]
        candidate = next(
            (element for element in candidates if element.id not in used_section_ids),
            candidates[0] if candidates else None,
        )
        created = (
            _bind_element(
                semantic_field=semantic_field,
                element=candidate,
                queues=queues,
                assets=asset_map,
                item_id=None,
                dropped=dropped,
                issues=issues,
            )
            if candidate
            else []
        )
        if not created:
            _discard_semantic_slot(queues, semantic_field)
            if requirement == "required":
                issues.append(f"{section.id}: required field '{semantic_field}' is missing or has no slot")
        bindings.extend(created)
        used_section_ids.update(
            source_id for binding in created for source_id in binding.source_element_ids
        )

    # Bind per item, not per field. Missing fields reserve their visual slot so
    # content from item N can never slide into item N-1's card.
    if item_fields:
        if group is None:
            for semantic_field, requirement in item_fields:
                if requirement == "required":
                    issues.append(f"{section.id}: required repeat field '{semantic_field}' has no group")
        else:
            repeat = entry.capabilities.repeat_group
            item_count = len(group.items)
            if repeat is not None and item_count < repeat.minimum:
                issues.append(
                    f"{section.id}/{group.id}: repeat item count {item_count} is below minimum {repeat.minimum}"
                )
            if repeat is not None and repeat.maximum is not None and item_count > repeat.maximum:
                issues.append(
                    f"{section.id}/{group.id}: repeat item count {item_count} exceeds maximum {repeat.maximum}"
                )
            if not issues:
                _ensure_repeat_slots(queues, item_fields, group, elements, entry)
            for item in group.items:
                for semantic_field, requirement in item_fields:
                    candidates = _item_elements(item, elements, semantic_field)
                    created: list[SemanticBinding] = []
                    for element in candidates:
                        created.extend(
                            _bind_element(
                                semantic_field=semantic_field,
                                element=element,
                                queues=queues,
                                assets=asset_map,
                                dropped=dropped,
                                item_id=item.id,
                                issues=issues,
                            )
                        )
                    if not created:
                        _discard_semantic_slot(queues, semantic_field)
                        if requirement == "required":
                            issues.append(
                                f"{section.id}/{item.id}: required field '{semantic_field}' is missing or has no slot"
                            )
                    bindings.extend(created)

            reserve_count = max(0, (repeat.default if repeat else 0) - len(group.items))
            for _ in range(reserve_count):
                for semantic_field, _requirement in item_fields:
                    _discard_semantic_slot(queues, semantic_field)

    if issues:
        raise PlanningError(issues)
    return tuple(bindings)


def _bind_section_physical(
    section: Section,
    entry: TemplateCatalogEntry,
    *,
    assets: Mapping[str, AssetRecord] | None = None,
    dropped: list[str] | None = None,
) -> tuple[SemanticBinding, ...]:
    """Bind within exact per-field ownership chunks; content cannot shift owners."""

    asset_map = assets or {}
    elements = {element.id: element for element in section.content}
    owned = {
        field: deque(contract.slots)
        for field, contract in entry.capabilities.physical_fields.items()
    }
    bindings: list[SemanticBinding] = []
    issues: list[str] = []
    group = _best_group(section, entry)
    grouped_ids = {
        element_id
        for source_group in section.groups
        for item in source_group.items
        for value in item.fields.values()
        for element_id in ([value] if isinstance(value, str) else value)
    }
    used_section_ids: set[str] = set()
    section_fields = [
        (field, requirement)
        for field, requirement in entry.capabilities.fields.items()
        if not _is_repeat_field(field)
    ]
    for semantic_field, requirement in section_fields:
        contract = entry.capabilities.physical_fields[semantic_field]
        candidates = sorted(
            (
                element
                for element in section.content
                if element.id not in grouped_ids
                and element.id not in used_section_ids
                and _element_matches(element, semantic_field)
            ),
            key=lambda item: (_element_match_rank(item, semantic_field), item.order, item.id),
        )
        if candidates:
            best_rank = _element_match_rank(candidates[0], semantic_field)
            candidates = [
                candidate
                for candidate in candidates
                if _element_match_rank(candidate, semantic_field) == best_rank
            ]
        if len(candidates) > contract.slots_per_owner:
            issues.append(
                f"{section.id}: field '{semantic_field}' has {len(candidates)} values but "
                f"owns {contract.slots_per_owner} physical slots"
            )
        created: list[SemanticBinding] = []
        for element in candidates[: contract.slots_per_owner]:
            created.extend(
                _bind_element(
                    semantic_field=semantic_field,
                    element=element,
                    queues={},
                    owned_slots=owned[semantic_field],
                    assets=asset_map,
                    item_id=None,
                    dropped=dropped,
                    issues=issues,
                )
            )
        if not created and requirement == "required":
            issues.append(f"{section.id}: {_unmet_reason(semantic_field, candidates, asset_map)}")
        bindings.extend(created)
        used_section_ids.update(
            source_id for binding in created for source_id in binding.source_element_ids
        )

    repeat_fields = [
        (field, requirement)
        for field, requirement in entry.capabilities.fields.items()
        if _is_repeat_field(field)
    ]
    if repeat_fields:
        if group is None:
            for semantic_field, requirement in repeat_fields:
                if requirement == "required":
                    issues.append(
                        f"{section.id}: required repeat field '{semantic_field}' has no group"
                    )
        else:
            repeat = entry.capabilities.repeat_group
            item_count = len(group.items)
            if repeat is not None and item_count < repeat.minimum:
                issues.append(
                    f"{section.id}/{group.id}: repeat item count {item_count} is below minimum {repeat.minimum}"
                )
            if repeat is not None and repeat.maximum is not None and item_count > repeat.maximum:
                issues.append(
                    f"{section.id}/{group.id}: repeat item count {item_count} exceeds maximum {repeat.maximum}"
                )
            if not issues:
                _extend_physical_repeat_slots(owned, entry, item_count)
            for item in group.items:
                for semantic_field, requirement in repeat_fields:
                    contract = entry.capabilities.physical_fields[semantic_field]
                    candidates = _item_elements(item, elements, semantic_field)
                    slots_before = len(owned[semantic_field])
                    if len(candidates) > contract.slots_per_owner:
                        issues.append(
                            f"{section.id}/{item.id}: field '{semantic_field}' has "
                            f"{len(candidates)} values but owns {contract.slots_per_owner} physical slots"
                        )
                    created: list[SemanticBinding] = []
                    for element in candidates[: contract.slots_per_owner]:
                        created.extend(
                            _bind_element(
                                semantic_field=semantic_field,
                                element=element,
                                queues={},
                                owned_slots=owned[semantic_field],
                                assets=asset_map,
                                item_id=item.id,
                                dropped=dropped,
                                issues=issues,
                            )
                        )
                    consumed_slots = slots_before - len(owned[semantic_field])
                    for _ in range(contract.slots_per_owner - consumed_slots):
                        if owned[semantic_field]:
                            owned[semantic_field].popleft()
                    if not created and requirement == "required":
                        issues.append(
                            f"{section.id}/{item.id}: required field '{semantic_field}' is missing or has no slot"
                        )
                    bindings.extend(created)
    if issues:
        raise PlanningError(issues)
    return tuple(bindings)


def _extend_physical_repeat_slots(
    owned: dict[str, deque[str]],
    entry: TemplateCatalogEntry,
    item_count: int,
) -> None:
    repeat = entry.capabilities.repeat_group
    if repeat is None or item_count <= repeat.default:
        return
    if not repeat.expandable:
        return
    all_slots = [slot for queue in owned.values() for slot in queue]
    next_index: dict[str, int] = {}
    for contract in entry.capabilities.physical_fields.values():
        slot_type = contract.slot_type
        pattern = re.compile(rf"^{re.escape(slot_type)}_(\d+)")
        next_index[slot_type] = max(
            (
                int(match.group(1))
                for slot in all_slots
                if (match := pattern.match(slot))
            ),
            default=0,
        ) + 1
    repeat_fields = [
        field
        for field in entry.capabilities.fields
        if _is_repeat_field(field)
    ]
    for _owner in range(repeat.default, item_count):
        for field in repeat_fields:
            contract = entry.capabilities.physical_fields[field]
            for _ in range(contract.slots_per_owner):
                index = next_index[contract.slot_type]
                next_index[contract.slot_type] += 1
                suffix = "_src" if contract.slot_type == "image" else ""
                owned[field].append(f"{contract.slot_type}_{index}{suffix}")


def _safe_name(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value.replace("_", " "))
    return " ".join(word.capitalize() for word in words) or "Section"


def _block_name(page: Page, section: Section, used: set[str]) -> str:
    base = f"{_safe_name(page.title)} {_safe_name(section.semantic_role)}"
    candidate = base
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{base} {suffix}"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def _simplifications(section: Section, entry: TemplateCatalogEntry) -> tuple[SimplificationDecision, ...]:
    supported = {_normalized(value) for value in entry.capabilities.supported_modifiers}
    decisions: list[SimplificationDecision] = []
    for layer in section.decorative_layers:
        if _normalized(layer.kind) not in supported:
            decisions.append(
                SimplificationDecision(
                    trait=f"decorative:{layer.kind}",
                    classification=SimplificationKind.OMIT,
                    severity=IssueSeverity.MEDIUM,
                    reason="selected template has no declared modifier for this decorative layer",
                    source_ids=(layer.id,),
                )
            )
    supported_interactions = {_normalized(value) for value in entry.capabilities.interactions}
    for interaction in section.interactions:
        key = _normalized(interaction.kind.value)
        if key not in supported_interactions:
            severity = (
                IssueSeverity.HIGH
                if interaction.kind
                in {InteractionKind.FORM, InteractionKind.MENU, InteractionKind.ACCORDION, InteractionKind.TABS}
                else IssueSeverity.MEDIUM
            )
            decisions.append(
                SimplificationDecision(
                    trait=f"interaction:{interaction.kind.value}",
                    classification=SimplificationKind.MANUAL_MODULE,
                    severity=severity,
                    reason=_interaction_reason(interaction.kind),
                    source_ids=(interaction.id,),
                )
            )
    return tuple(decisions)


def _document_id(document: DesignDocument) -> str:
    digest = hashlib.sha256(serialize_design_document(document).encode("utf-8")).hexdigest()[:16]
    return f"design-{digest}"


def _style_config(document: DesignDocument, policy: PlanPolicy) -> StyleTranslationConfig:
    def string_tokens(values):
        return {
            name: str(token.value)
            for name, token in values.items()
            if isinstance(token.value, (str, int, float))
        }

    prefix = re.sub(r"[^a-z0-9-]+", "-", _normalized(document.source.identifier)).strip("-")
    if not prefix or not prefix[0].isalpha():
        prefix = f"project-{prefix or 'design'}"
    return StyleTranslationConfig(
        palette=string_tokens(document.tokens.colors),
        spacing=string_tokens(document.tokens.spacing),
        modifier_properties=_DEFAULT_MODIFIER_PROPERTIES,
        project_prefix=prefix[:64],
        max_scoped_rules_per_section=policy.css_rule_budget,
    )


def _css_scope(config: StyleTranslationConfig, section: Section) -> str:
    section_slug = re.sub(r"[^a-z0-9-]+", "-", _normalized(section.id)).strip("-")
    if not section_slug or not section_slug[0].isalpha():
        section_slug = f"section-{section_slug or 'design'}"
    return f".{config.project_prefix} .design-section-{section_slug}"


def plan_design_document(
    document: DesignDocument,
    *,
    catalog: Iterable[TemplateCatalogEntry] | None = None,
    policy: PlanPolicy | None = None,
    template_overrides: Mapping[str, str] | None = None,
    context: MatchContext | None = None,
    style_config: StyleTranslationConfig | None = None,
    override_author: str = "cli-user",
    override_reason: str = "explicit template override",
) -> CompositionPlan:
    """Match and bind every section in stable page order."""

    resolved_catalog = tuple(catalog or load_template_catalog())
    by_id = {entry.template_id.casefold(): entry for entry in resolved_catalog}
    by_name = {entry.name.casefold(): entry for entry in resolved_catalog}
    plan_policy = policy or PlanPolicy()
    overrides = {key: value for key, value in (template_overrides or {}).items()}
    assets = {asset.id: asset for asset in document.assets}
    entries: list[CompositionPlanEntry] = []
    used_names: set[str] = set()
    native_total = 0.0
    editable_values = 0
    source_values = 0
    css_rule_count = 0
    css_bytes = 0
    resolved_style_config = style_config or _style_config(document, plan_policy)

    for page in document.pages:
        for section in sorted(page.sections, key=lambda item: (item.order, item.id)):
            result = match_section(
                section,
                resolved_catalog,
                context=context,
            )
            selected = result.selected_candidate
            override = overrides.get(section.id)
            override_audit = None
            if override:
                entry = by_id.get(override.casefold()) or by_name.get(override.casefold())
                if entry is None:
                    raise PlanningError((f"{section.id}: unknown template override '{override}'",))
                selected = next(
                    (candidate for candidate in result.candidates if candidate.template_id == entry.template_id),
                    None,
                ) or score_template(section, entry, context=context)
                override_audit = OverrideAudit(
                    author=override_author,
                    reason=override_reason,
                    previous_candidates=tuple(
                        MatchAlternative(
                            template_id=item.template_id,
                            template_name=item.template_name,
                            score=item.score,
                            confidence=item.confidence.value,
                        )
                        for item in result.candidates
                    ),
                )
            else:
                entry = by_id[selected.template_id.casefold()]

            binding_issues: tuple[str, ...] = ()
            dropped_content: list[str] = []
            try:
                bindings = bind_section(
                    section, entry, assets=assets, dropped=dropped_content
                )
            except PlanningError as exc:
                bindings = ()
                binding_issues = exc.issues
            base_style = translate_style_set(section.style, entry.capabilities, resolved_style_config)
            responsive_style = translate_responsive_observations(
                section.responsive, entry.capabilities, resolved_style_config
            )
            style_decisions = base_style.decisions + responsive_style.decisions
            scoped_css = {**base_style.css_declarations, **responsive_style.css_declarations}
            native_report = build_native_style_report(
                style_decisions, agency_utilities=resolved_style_config.agency_utilities
            )
            scoped_css = apply_important_css_properties(
                scoped_css, native_report.important_css_properties
            )
            element_style_actions, element_style_warnings = translate_element_styles(
                section.content,
                bindings,
                entry.capabilities,
                resolved_style_config,
                css_scope=_css_scope(resolved_style_config, section),
                agency_utilities=resolved_style_config.agency_utilities,
            )
            simplification_list = list(_simplifications(section, entry))
            if binding_issues:
                simplification_list.append(
                    SimplificationDecision(
                        trait="semantic_binding",
                        classification=SimplificationKind.NEW_TEMPLATE,
                        severity=IssueSeverity.HIGH,
                        reason="; ".join(binding_issues),
                        source_ids=(section.id,),
                    )
                )
            for decision in style_decisions:
                if decision.layer == TranslationLayer.MANUAL:
                    simplification_list.append(
                        SimplificationDecision(
                            trait=f"style:{decision.property.value}",
                            classification=SimplificationKind.APPROXIMATE,
                            severity=IssueSeverity.MEDIUM,
                            reason=decision.reason,
                        )
                    )
            simplifications = tuple(simplification_list)
            section_form_fields = _form_fields(section)
            blocks_for_gaps = any(
                item.blocks_approval
                # A form is never rebuilt from a template, so no template can
                # represent one: it is the expected outcome rather than a
                # shortfall, and it is handled once its placeholder has fields.
                and not (item.trait == "interaction:form" and section_form_fields)
                for item in simplifications
            )
            blocking = (
                selected.score < plan_policy.minimum_confidence
                or result.blocking
                or blocks_for_gaps
            )
            alternatives = tuple(
                MatchAlternative(
                    template_id=item.template_id,
                    template_name=item.template_name,
                    score=item.score,
                    confidence=item.confidence.value,
                )
                for item in result.candidates
                if item.template_id != selected.template_id
            )
            plan_match = PlanMatch(
                score=selected.score,
                confidence=selected.confidence.value,
                blocking=blocking,
                reasons=selected.reasons,
                alternatives=alternatives,
            )
            entries.append(
                CompositionPlanEntry(
                    id=f"{section.id}.plan",
                    source_section_id=section.id,
                    template_id=entry.template_id,
                    template=entry.name,
                    match=plan_match,
                    override_audit=override_audit,
                    block=PlanBlock(
                        name=_block_name(page, section, used_names),
                        category=entry.category,
                        type=BlockType.CUSTOM,
                    ),
                    bindings=bindings,
                    clear_slots=_clear_slots(entry, bindings),
                    modifiers=tuple(
                        dict.fromkeys(
                            selected.required_modifiers
                            + tuple(
                                decision.target
                                for decision in style_decisions
                                if decision.layer == TranslationLayer.TEMPLATE_MODIFIER
                            )
                        )
                    ),
                    style_decisions=style_decisions,
                    css_scope=_css_scope(resolved_style_config, section) if scoped_css else None,
                    scoped_css=scoped_css,
                    element_styles=element_style_actions,
                    form_fields=section_form_fields,
                    simplifications=simplifications,
                    # Dropped content reports on the entry rather than as a
                    # validation issue: it is worth seeing, but whether it
                    # should block approval is a policy call, not this
                    # function's to make.
                    warnings=tuple(
                        dict.fromkeys(
                            selected.missing_requirements
                            + binding_issues
                            + tuple(dropped_content)
                            + base_style.warnings
                            + responsive_style.warnings
                            + native_report.diagnostics
                            + element_style_warnings
                        )
                    ),
                )
            )
            native_total += entry.capabilities.native_component_ratio
            editable_values += len({binding.source_element_ids[0] for binding in bindings})
            source_values += len([element for element in section.content if element.value is not None or element.asset_id])
            element_scoped_css_count = sum(len(action.scoped_css) for action in element_style_actions)
            element_scoped_css_bytes = sum(
                len(json.dumps(dict(action.scoped_css), sort_keys=True, separators=(",", ":")).encode("utf-8"))
                for action in element_style_actions
                if action.scoped_css
            )
            css_rule_count += len(scoped_css) + element_scoped_css_count
            css_bytes += (
                len(json.dumps(scoped_css, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                + element_scoped_css_bytes
            )

    section_count = len(entries)
    return CompositionPlan(
        source_document_id=_document_id(document),
        policy=plan_policy,
        entries=tuple(entries),
        summary=PlanSummary(
            section_count=section_count,
            blocking_count=sum(entry.match.blocking for entry in entries),
            native_component_ratio=native_total / section_count if section_count else 0.0,
            editable_content_coverage=min(1.0, editable_values / source_values) if source_values else 1.0,
            scoped_css_rule_count=css_rule_count,
            scoped_css_bytes=css_bytes,
        ),
    )


def _lost_agency_decision_reason(
    decisions: Sequence[Any],
    native_report: Any,
    agency_utilities: Mapping[str, str] | None,
) -> str | None:
    """Explain a previously accepted AGENCY_UTILITY decision that would vanish.

    ``build_native_style_report`` keeps, per property, the *last* decision in
    sequence order that both reaches its applicable-layer/breakpoint checks
    and passes ``_validate_target`` -- an earlier decision for that property
    is only truly superseded when a later one actually lands in
    ``native_report.actions``; a later decision that itself fails validation
    changes nothing there, and must not be able to hide behind whatever
    stale entry an earlier decision left in place. So "is this accepted
    decision's own property still covered" is not enough by itself: the
    covering action's own position in ``decisions`` must be at or after this
    decision's position, never before it, or the entry an emission sees is a
    leftover from before this decision was even accepted, not confirmation
    that it (or something that legitimately supersedes it) survived.

    Matching a candidate's ``source_value``/``layer``/``target`` against the
    surviving action is necessary but not sufficient to credit it as the
    decision that produced that action: ``build_native_style_report`` never
    lets a breakpoint-scoped decision win a property's action -- it is always
    reported as a diagnostic instead, no matter what it would otherwise
    resolve to. A later decision that merely echoes an earlier winner's
    fields at a breakpoint never reaches ``native_report.actions`` itself, so
    it must not be credited as the thing that kept that property's action
    alive; only an unconditional (``breakpoint is None``) decision can
    actually explain a surviving action.
    """

    resolved = agency_utilities or {}
    actions_by_property = {action.property: action for action in native_report.actions}
    winner_index_by_property: dict[Any, int] = {}
    for index, decision in enumerate(decisions):
        action = actions_by_property.get(decision.property)
        if (
            action is not None
            and decision.breakpoint is None
            and action.source_value == decision.source_value
            and action.layer == decision.layer
            and action.target == decision.target
        ):
            winner_index_by_property[decision.property] = index

    for index, decision in enumerate(decisions):
        if decision.layer is not TranslationLayer.AGENCY_UTILITY or decision.breakpoint is not None:
            continue
        winner_index = winner_index_by_property.get(decision.property)
        if winner_index is not None and winner_index >= index:
            continue
        key = f"{decision.property.value}:{decision.source_value.strip().casefold()}"
        if not resolved:
            reason = "no agency_utilities mapping was supplied"
        elif key not in resolved:
            reason = f"the supplied mapping has no entry for {key!r}"
        elif resolved[key] != decision.target:
            reason = (
                f"the supplied mapping resolves {key!r} to {resolved[key]!r}, "
                f"not the accepted class {decision.target!r}"
            )
        else:
            reason = "the supplied agency mapping does not reproduce the accepted class"
        return (
            f"accepted agency decision for property '{decision.property.value}' "
            f"(target {decision.target!r}) would be silently dropped: {reason}"
        )
    return None


def emit_library_plan(
    plan: CompositionPlan, *, agency_utilities: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Emit the current build-library format with placeholder leakage protection.

    ``agency_utilities`` is the same property-value-to-class mapping a caller
    may have passed into ``plan_design_document`` via ``style_config``; it
    only widens which ``AGENCY_UTILITY``-layer decisions are transported as
    ``native_classes`` entries. Platform-utility and safe theme-slot classes
    are transported regardless, since those come from this module's own
    static, project-independent tables.
    """

    catalog = load_template_catalog()
    templates_by_id = {entry.template_id.casefold(): entry for entry in catalog}
    templates_by_name = {entry.name.casefold(): entry for entry in catalog}
    output: list[dict[str, Any]] = []
    for entry in plan.entries:
        if entry.match.blocking:
            continue
        overrides: dict[str, str] = {slot: "" for slot in entry.clear_slots}
        for binding in entry.bindings:
            if _is_placeholder(binding.value):
                raise PlanningError(
                    (f"{entry.source_section_id}: placeholder value rejected for slot {binding.slot}",)
                )
            overrides[binding.slot] = binding.value
        template = templates_by_id.get(entry.template_id.casefold()) or templates_by_name.get(
            entry.template.casefold()
        )
        if template is None:
            raise PlanningError(
                (f"{entry.source_section_id}: template '{entry.template_id}' is unavailable",)
            )
        template_data = load_template_data(template)
        template_digest = hashlib.sha256(
            json.dumps(
                template_data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        style_fields: dict[str, Any] = {}
        if entry.scoped_css:
            # Defense in depth: emit_library_plan runs on the planner's own
            # trusted CompositionPlan, but validating here mirrors the same
            # boundary check compose_project_library performs on a
            # serialized (and therefore untrusted) library-plan.json, so a
            # planner-side bug surfaces at emission time rather than only
            # downstream.
            try:
                validate_style_payload(entry.css_scope, dict(entry.scoped_css))
            except StyleTransportError as exc:
                raise PlanningError((f"{entry.source_section_id}: {exc}",)) from exc
            style_fields = {
                "style_scope": entry.css_scope,
                "style_declarations": dict(entry.scoped_css),
            }
        native_report = build_native_style_report(
            entry.style_decisions, agency_utilities=agency_utilities or {}
        )
        lost_reason = _lost_agency_decision_reason(
            entry.style_decisions, native_report, agency_utilities
        )
        if lost_reason is not None:
            raise PlanningError((f"{entry.source_section_id}: {lost_reason}",))
        native_fields: dict[str, Any] = {}
        if native_report.actions:
            native_payload = [
                action.model_dump(mode="json") for action in native_report.actions
            ]
            try:
                validate_native_class_actions(
                    native_payload, agency_utilities=agency_utilities
                )
            except NativeStyleTransportError as exc:
                raise PlanningError((f"{entry.source_section_id}: {exc}",)) from exc
            native_fields = {"native_classes": native_payload}
        element_style_fields: dict[str, Any] = {}
        if entry.element_styles:
            for action in entry.element_styles:
                element_native_report = build_native_style_report(
                    action.style_decisions, agency_utilities=agency_utilities or {}
                )
                element_lost_reason = _lost_agency_decision_reason(
                    action.style_decisions, element_native_report, agency_utilities
                )
                if element_lost_reason is not None:
                    raise PlanningError(
                        (
                            f"{entry.source_section_id}/{action.source_element_id} "
                            f"(slot {action.slot}): {element_lost_reason}",
                        )
                    )
            try:
                element_style_payload = emit_element_style_payload(
                    entry.element_styles, agency_utilities=agency_utilities
                )
            except ValueError as exc:
                raise PlanningError((f"{entry.source_section_id}: {exc}",)) from exc
            if element_style_payload:
                element_style_fields = {"element_styles": element_style_payload}
        output.append(
            {
                "key": entry.source_section_id,
                "template": entry.template,
                "name": entry.block.name,
                "category": entry.block.category,
                "type": entry.block.type.value,
                "template_digest": template_digest,
                "overrides": overrides,
                "form_fields": [dict(field) for field in entry.form_fields],
                **style_fields,
                **native_fields,
                **element_style_fields,
            }
        )
    return output


def serialize_library_plan(
    plan: CompositionPlan, *, agency_utilities: Mapping[str, str] | None = None
) -> str:
    return (
        json.dumps(
            emit_library_plan(plan, agency_utilities=agency_utilities),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def validate_composition_plan(
    plan: CompositionPlan,
    *,
    catalog: Iterable[TemplateCatalogEntry] | None = None,
) -> tuple[str, ...]:
    """Return stable, actionable validation issues beyond Pydantic's schema checks."""

    resolved_catalog = tuple(catalog or load_template_catalog())
    by_id = {entry.template_id.casefold(): entry for entry in resolved_catalog}
    by_name = {entry.name.casefold(): entry for entry in resolved_catalog}
    issues: list[str] = []

    def expandable_slot(slot: str, template: TemplateCatalogEntry) -> bool:
        repeat = template.capabilities.repeat_group
        if repeat is None or not repeat.expandable:
            return False
        return bool(
            re.fullmatch(
                r"(?:heading|text|list-item)_\d+|(?:image)_\d+_(?:src|alt|href)|"
                r"(?:button|link)_\d+(?:_href)?",
                slot,
            )
        )

    for entry in plan.entries:
        template = by_id.get(entry.template_id.casefold()) or by_name.get(entry.template.casefold())
        prefix = entry.source_section_id
        if template is None:
            issues.append(f"{prefix}: template '{entry.template}' is not available")
            continue
        available_slots = {
            slot["key"] for slot in enumerate_slots(load_template_data(template)["template"])
        }
        for binding in entry.bindings:
            if binding.slot not in available_slots and not expandable_slot(binding.slot, template):
                issues.append(f"{prefix}: binding slot '{binding.slot}' is not exposed by {template.name}")
            if _is_placeholder(binding.value):
                issues.append(f"{prefix}: binding slot '{binding.slot}' contains placeholder content")
        for slot in entry.clear_slots:
            if slot not in available_slots:
                issues.append(f"{prefix}: clear slot '{slot}' is not exposed by {template.name}")
        for action in entry.element_styles:
            if action.slot not in available_slots and not expandable_slot(action.slot, template):
                issues.append(
                    f"{prefix}: element style slot '{action.slot}' is not exposed by {template.name}"
                )
        scoped_rules = len(entry.scoped_css) + sum(
            len(action.scoped_css) for action in entry.element_styles
        )
        if entry.scoped_css and not entry.css_scope:
            issues.append(f"{prefix}: generated CSS has no project/section scope")
        if scoped_rules > plan.policy.css_rule_budget:
            issues.append(
                f"{prefix}: scoped CSS rule count {scoped_rules} exceeds budget {plan.policy.css_rule_budget}"
            )
        if entry.match.score < plan.policy.minimum_confidence and not entry.match.blocking:
            issues.append(
                f"{prefix}: score {entry.match.score:.3f} is below minimum confidence without a blocker"
            )
        if entry.match.blocking:
            issues.append(f"{prefix}: unresolved blocking match or simplification")
    return tuple(issues)
