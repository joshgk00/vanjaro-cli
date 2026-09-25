"""Transport for a content element's own captured style onto its exact bound owner.

``style_translation.py`` decides what a source style becomes; ``style_transport.py``
and ``native_style_transport.py`` already know how to safely apply and
re-validate the result. What was missing is *ownership*: a ``ContentElement``'s
``StyleSet`` is captured against the element itself (a heading, a card's own
action, an image), never against the section that contains it, but nothing
carried that style past ``SemanticBinding.source_element_ids`` into the actual
generated component. This module is that missing link -- it does not
reimplement translation or validation, it only:

1. Resolves which single physical override slot (``SemanticBinding.slot``,
   the same vocabulary ``utils/block_compose.enumerate_slots`` produces) a
   content element's own style is allowed to land on, reporting -- never
   guessing -- when that ownership is ambiguous.
2. Runs the existing translator (``style_translation.translate_style_set``)
   against that element's own ``StyleSet``, exactly as section styles already
   are.
3. Serializes the result into a plan's untrusted library-plan payload and
   re-validates it at composition, reusing ``style_transport``/
   ``native_style_transport`` for every safety check rather than duplicating
   their tables.
4. Applies an accepted action to the exact owner component
   ``utils.block_compose.apply_overrides_with_owners`` resolved for that slot
   -- never the section root, never a sibling.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from vanjaro_cli.design.composition import ElementStyleAction, SemanticBinding
from vanjaro_cli.design.models import ContentElement
from vanjaro_cli.design.native_style_transport import (
    NativeStyleTransportError,
    apply_important_css_properties,
    apply_important_to_buckets,
    apply_native_class_actions,
    build_native_style_report,
    important_css_properties_for_component,
    validate_native_class_actions,
)
from vanjaro_cli.design.style_transport import (
    StyleTransportError,
    build_style_rules,
    ensure_scoped_selector_id,
    validate_style_payload,
)
from vanjaro_cli.design.style_translation import StyleTranslationConfig, translate_style_set
from vanjaro_cli.design.template_catalog import CapabilityManifest

__all__ = [
    "ElementStyleTransportError",
    "apply_element_styles",
    "emit_element_style_payload",
    "translate_element_styles",
]


class ElementStyleTransportError(ValueError):
    """Raised when serialized element-style metadata is malformed, unsafe, or
    targets an owner slot that no longer exists in the composed tree."""


# Mirrors ElementStyleAction.slot / SemanticBinding.slot's pattern in
# design/composition.py. Duplicated rather than imported because that
# pattern lives inside a pydantic Field() call, not a named constant -- the
# same reasoning style_transport.py's own _CSS_SCOPE_PATTERN documents.
_SLOT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*(?:_\d+)?(?:_[a-z]+)?$")

# A binding whose semantic_field names an attribute alias of its owner (an
# image's alt text, an image/button/link's href) targets the same physical
# node (button/link) or a distinct wrapper (a linked image) rather than a
# second, competing owner for that element's own captured style. Only the
# non-alias binding is ever treated as the element's style owner.
_ALIAS_SUFFIXES = (".alt", ".href")

# A background image is rendered onto the section root itself (see
# apply_section_background / block_compose._apply_palette_background), which
# has no distinct addressable component of its own to own a per-element
# style separate from the section. Styling it here would be exactly the
# "style the section instead of the child" failure this module exists to
# prevent, so it is deliberately excluded rather than misattributed.
_UNOWNABLE_SLOTS = frozenset({"background_image"})

_MAX_ELEMENT_STYLE_ENTRIES = 64


def _owning_bindings(
    bindings: Sequence[SemanticBinding],
) -> tuple[dict[str, SemanticBinding], dict[str, str]]:
    """Map each source element id to its single style-owning binding.

    Returns ``(owners, unresolved)``: ``unresolved`` explains -- keyed by
    element id -- why no single owner could be resolved, for elements bound
    to more than one owner slot (one-to-many), bound only through an alias
    slot, or named by a binding that itself maps more than one source element
    onto one slot (many-to-one). Neither case falls back to a first or
    arbitrary node.
    """
    by_element: dict[str, list[SemanticBinding]] = defaultdict(list)
    unresolved: dict[str, str] = {}
    for binding in bindings:
        if len(binding.source_element_ids) != 1:
            joined = ", ".join(binding.source_element_ids)
            for element_id in binding.source_element_ids:
                unresolved[element_id] = (
                    f"binding for slot {binding.slot!r} maps multiple source elements "
                    f"({joined}) onto one slot; style ownership is ambiguous"
                )
            continue
        by_element[binding.source_element_ids[0]].append(binding)

    owners: dict[str, SemanticBinding] = {}
    for element_id, element_bindings in by_element.items():
        if element_id in unresolved:
            continue
        primaries = [
            binding
            for binding in element_bindings
            if not binding.semantic_field.endswith(_ALIAS_SUFFIXES)
            and binding.slot not in _UNOWNABLE_SLOTS
        ]
        if len(primaries) == 1:
            owners[element_id] = primaries[0]
        elif len(primaries) == 0:
            if any(binding.slot in _UNOWNABLE_SLOTS for binding in element_bindings):
                continue
            unresolved[element_id] = "no owning content slot was bound for this element"
        else:
            slots = ", ".join(sorted({binding.slot for binding in primaries}))
            unresolved[element_id] = (
                f"bound to more than one owner slot ({slots}); style ownership is ambiguous"
            )
    return owners, unresolved


def translate_element_styles(
    section_content: Sequence[ContentElement],
    bindings: Sequence[SemanticBinding],
    capabilities: CapabilityManifest,
    config: StyleTranslationConfig,
    *,
    css_scope: str | None,
    agency_utilities: Mapping[str, str] | None = None,
) -> tuple[tuple[ElementStyleAction, ...], tuple[str, ...]]:
    """Translate every bound content element's own style onto its exact owner slot.

    Reuses ``style_translation.translate_style_set`` -- the same precedence
    section styles already go through -- against each element's own
    ``StyleSet``. Only a ``StyleObservation``'s own ``condition`` (already
    supported evidence on the element) can produce a conditional rule here;
    no section-level responsive sample is ever attributed to a child.
    """

    elements_by_id = {element.id: element for element in section_content}
    owners, unresolved = _owning_bindings(bindings)
    warnings: list[str] = [
        f"element {element_id}: {reason}" for element_id, reason in sorted(unresolved.items())
    ]

    # A template modifier (config.modifier_properties, e.g. "band-color") is a
    # whole-section capability label -- the section's own band background,
    # not any one child's. Reusing it here would let a template that happens
    # to support a section-wide modifier for this property silently swallow
    # one specific element's own captured value into an unapplied capability
    # label instead of the theme/utility/scoped-CSS precedence a single
    # element's own style must still go through.
    element_config = config.model_copy(update={"modifier_properties": {}})

    actions: list[ElementStyleAction] = []
    for element_id in sorted(owners):
        binding = owners[element_id]
        element = elements_by_id.get(element_id)
        if element is None or not element.style.observations:
            continue
        result = translate_style_set(element.style, capabilities, element_config)
        if not result.decisions:
            continue
        native_report = build_native_style_report(
            result.decisions, agency_utilities=agency_utilities or {}
        )
        for message in result.warnings:
            warnings.append(f"element {element_id}: {message}")
        for message in native_report.diagnostics:
            warnings.append(f"element {element_id}: {message}")
        if not result.css_declarations and not native_report.actions:
            continue
        element_scoped_css = apply_important_css_properties(
            result.css_declarations, native_report.important_css_properties
        )
        actions.append(
            ElementStyleAction(
                source_element_id=element_id,
                slot=binding.slot,
                item_id=binding.item_id,
                style_decisions=result.decisions,
                css_scope=css_scope if element_scoped_css else None,
                scoped_css=dict(element_scoped_css),
            )
        )
    return tuple(actions), tuple(warnings)


def emit_element_style_payload(
    actions: Sequence[ElementStyleAction],
    *,
    agency_utilities: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Serialize accepted element-style actions for a library-plan entry.

    Mirrors ``planner.emit_library_plan``'s own defense-in-depth: this runs on
    the planner's trusted ``CompositionPlan``, but validates through the same
    functions ``compose_project_library`` re-runs on the untrusted payload, so
    a planner-side bug surfaces here rather than only downstream.
    """

    payload: list[dict[str, Any]] = []
    for action in actions:
        fields: dict[str, Any] = {
            "slot": action.slot,
            "source_element_id": action.source_element_id,
        }
        if action.item_id is not None:
            fields["item_id"] = action.item_id
        if action.scoped_css:
            try:
                validate_style_payload(action.css_scope, dict(action.scoped_css))
            except StyleTransportError as exc:
                raise ValueError(
                    f"element {action.source_element_id} (slot {action.slot}): {exc}"
                ) from exc
            fields["style_scope"] = action.css_scope
            fields["style_declarations"] = dict(action.scoped_css)
        native_report = build_native_style_report(
            action.style_decisions, agency_utilities=agency_utilities or {}
        )
        if native_report.actions:
            native_payload = [item.model_dump(mode="json") for item in native_report.actions]
            try:
                validate_native_class_actions(native_payload, agency_utilities=agency_utilities)
            except NativeStyleTransportError as exc:
                raise ValueError(
                    f"element {action.source_element_id} (slot {action.slot}): {exc}"
                ) from exc
            fields["native_classes"] = native_payload
        if "style_declarations" in fields or "native_classes" in fields:
            payload.append(fields)
    return payload


def apply_element_styles(
    rendered: dict[str, Any],
    owners: Mapping[str, dict[str, Any]],
    raw_element_styles: Any,
    *,
    library_key: str,
    agency_utilities: Mapping[str, str] | None = None,
) -> None:
    """Validate and apply an untrusted ``element_styles`` payload to ``rendered``.

    ``owners`` is ``utils.block_compose.apply_overrides_with_owners``'s second
    return value for the same ``rendered`` tree: the one physical component
    each surviving slot key resolved to. A payload naming any other slot key,
    a slot that was pruned, or a slot ``apply_overrides_with_owners`` never
    exposed at all, is rejected outright -- never redirected to a sibling or
    silently dropped. ``rendered`` and ``owners`` are mutated in place;
    ``raw_element_styles`` (untrusted input) is only read.
    """

    # Absence of the field entirely (the caller never calls this function
    # when "element_styles" not in raw) and an explicit empty list are the
    # only accepted legacy/no-op shapes. An explicit null/false/0/""/{} is a
    # caller mistake, not an equivalent way to say "nothing here" -- it is
    # rejected below by simply not matching the list check, same as any
    # other malformed shape.
    if raw_element_styles == []:
        return
    if not isinstance(raw_element_styles, list):
        raise ElementStyleTransportError("element_styles must be a list")
    if len(raw_element_styles) > _MAX_ELEMENT_STYLE_ENTRIES:
        raise ElementStyleTransportError("element_styles has an implausible number of entries")

    seen_slots: set[str] = set()
    for index, item in enumerate(raw_element_styles):
        if not isinstance(item, dict) or not item:
            raise ElementStyleTransportError(f"element_styles[{index}] must be a non-empty object")
        slot = item.get("slot")
        source_element_id = item.get("source_element_id")
        if not isinstance(slot, str) or not _SLOT_PATTERN.fullmatch(slot):
            raise ElementStyleTransportError(f"element_styles[{index}] has an invalid slot")
        if not isinstance(source_element_id, str) or not source_element_id.strip():
            raise ElementStyleTransportError(
                f"element_styles[{index}] requires a non-empty source_element_id"
            )
        item_id = item.get("item_id")
        if item_id is not None and not isinstance(item_id, str):
            raise ElementStyleTransportError(f"element_styles[{index}] item_id must be a string or null")
        if slot in seen_slots:
            raise ElementStyleTransportError(f"element_styles[{index}] duplicates slot {slot!r}")
        seen_slots.add(slot)

        owner = owners.get(slot)
        if owner is None:
            raise ElementStyleTransportError(
                f"element_styles[{index}]: owner slot {slot!r} for source element "
                f"{source_element_id!r} was removed or never resolved; refusing to "
                "redirect its style to a different component"
            )

        # native_classes is applied to the owner before style_declarations is
        # even validated, so that -- by the time a scoped rule for the same
        # property is checked for a colliding class -- this request's own
        # class already landed next to whatever the matched template baked
        # in by default. See
        # native_style_transport.important_css_properties_for_component.
        native_classes = item.get("native_classes")
        has_native = "native_classes" in item and native_classes != []
        if has_native:
            try:
                actions = validate_native_class_actions(
                    native_classes, agency_utilities=agency_utilities
                )
            except NativeStyleTransportError as exc:
                raise ElementStyleTransportError(
                    f"element_styles[{index}] ({source_element_id}): {exc}"
                ) from exc
            apply_native_class_actions(owner, actions)

        style_declarations = item.get("style_declarations")
        has_style = "style_declarations" in item and style_declarations != {}
        if has_style:
            try:
                buckets = validate_style_payload(item.get("style_scope"), style_declarations)
            except StyleTransportError as exc:
                raise ElementStyleTransportError(
                    f"element_styles[{index}] ({source_element_id}): {exc}"
                ) from exc
            # A Bootstrap utility class already on the owner (from the
            # native_classes action just applied above, or a baked-in
            # template default) compiles with !important on this
            # root-inspected target, so a same-property scoped rule at
            # normal priority is otherwise inert against it.
            important = important_css_properties_for_component(
                owner, {prop: value for style in buckets.values() for prop, value in style.items()}
            )
            buckets = apply_important_to_buckets(buckets, important)
            element_id = ensure_scoped_selector_id(owner, f"{library_key}:{slot}")
            rendered["styles"] = [
                *rendered.get("styles", []),
                *build_style_rules(element_id, buckets),
            ]

        if not has_style and not has_native:
            raise ElementStyleTransportError(
                f"element_styles[{index}] ({source_element_id}) declares neither "
                "style_declarations nor native_classes"
            )
