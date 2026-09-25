"""Structured transport for native (non-scoped-CSS) style decisions.

``style_translation.py`` decides *what* a source style should become -- a
theme slot, a platform utility class, an agency utility class, a template
modifier label, or scoped CSS. Only the scoped-CSS layer had a transport that
survived into composed block output (``style_transport.py``); every other
layer's ``StyleDecision.target`` was a description, never applied to a real
component. This module is the missing transport for the three layers whose
target is a confirmed-safe reusable class name (platform utility, a safe
theme slot, a declared agency utility), plus the explicit, actionable
reporting the other layers need instead of a guess:

* ``TEMPLATE_MODIFIER`` targets are template capability *labels*
  (``"band-color=#fff"``), not code that knows how to execute them -- there
  is no generic modifier applier anywhere in this codebase, so every one is
  reported as unresolved rather than treated as applied.
* A ``THEME`` target is only ever transported when its slot is a name this
  module can independently confirm maps to a real Bootstrap 5.1 utility class
  (``SAFE_THEME_SLOTS``). Vanjaro's extended palette slots (``tertiary``,
  ``quaternary`` -- see ``design/theme_palette_plan.py``) and every
  typography/spacing/radius theme target are token identifiers, not classes,
  and are reported rather than guessed at.
* ``OBJECT_FIT``/``OBJECT_POSITION`` are media-only properties. A
  section-level style observation carries no per-element ownership, so there
  is no way to find the one image such a decision belongs to. Applying it to
  the section root would be exactly the "object-fit on a div" failure this
  transport exists to prevent; it is reported as an unresolved media-owner
  gap instead.
* A breakpoint-scoped native decision is never applied unconditionally (that
  would silently contradict the desktop decision it overrides) and no
  Bootstrap responsive variant is assumed to exist for every utility, so it
  is reported as an unresolved responsive scope rather than guessed.

Conflict handling: every action carries the full ``family`` of mutually
exclusive class names for its utility (e.g. every text-align utility, for a
``text-end`` action). Applying an action removes every family member already
present on the target component -- including a template's own baked-in
default -- before adding the target, so two decisions for the same property
can never both land as classes.

``build_native_style_report`` runs on a planner's own trusted
``StyleDecision`` sequence. ``validate_native_class_actions`` re-validates
serialized action metadata read back from an untrusted ``library-plan.json``:
it never trusts an incoming payload's own ``family`` list, and instead
recomputes the true family for each action's ``(property, layer)`` from the
same static tables (plus, for agency utilities, a mapping the caller must
supply explicitly) before anything is applied.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from vanjaro_cli.design.models import BreakpointName, StyleProperty
from vanjaro_cli.design.style_translation import (
    StyleDecision,
    TranslationLayer,
    _CSS_PROPERTY_NAMES,
    _UTILITY_VALUES,
)

# ``_UTILITY_VALUES`` is style_translation.py's own canonical source-value ->
# platform-utility-class mapping (owned by the responsive/style_translation
# worker; this is a narrow, read-only import of that single table, not a
# second copy of it). It is used only to confirm that a claimed target is the
# exact class its declared source value produces -- family membership alone
# (every class for the *property*) is not proof of that; see
# ``_expected_platform_or_agency_target`` below.
#
# ``_CSS_PROPERTY_NAMES`` is the same module's StyleProperty -> CSS property
# name table, reused below (``_important_css_properties``) rather than a
# second copy, to translate a colliding property into the css_declarations
# key suffix that needs the priority fix.

__all__ = [
    "SAFE_THEME_SLOTS",
    "NativeClassAction",
    "NativeStyleReport",
    "NativeStyleTransportError",
    "apply_important_css_properties",
    "apply_important_to_buckets",
    "apply_native_class_actions",
    "build_native_style_report",
    "important_css_properties_for_component",
    "validate_native_class_actions",
]


class NativeStyleTransportError(ValueError):
    """Raised when serialized native-class metadata is malformed or unsafe."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# Bootstrap 5.1's actual `bg-*`/`text-*` color utility set (root-inspected;
# see style_translation.py's own Bootstrap 5.1 target note). Vanjaro's
# extended palette slots (`tertiary`, `quaternary` -- design/theme_palette_plan.py)
# have no matching utility class on this target, so a THEME decision naming
# one of those slots is a token identifier to report, never a class to apply.
SAFE_THEME_SLOTS: frozenset[str] = frozenset(
    {"primary", "secondary", "success", "info", "warning", "danger", "light", "dark"}
)

_MEDIA_ONLY_PROPERTIES: frozenset[StyleProperty] = frozenset(
    {StyleProperty.OBJECT_FIT, StyleProperty.OBJECT_POSITION}
)

_APPLICABLE_LAYERS: frozenset[TranslationLayer] = frozenset(
    {TranslationLayer.PLATFORM_UTILITY, TranslationLayer.THEME, TranslationLayer.AGENCY_UTILITY}
)

# Mirrors style_translation.py's own `_UTILITY_VALUES` mapping shape: every
# class value a StyleProperty's PLATFORM_UTILITY layer can produce, grouped
# so applying one removes every sibling before landing.
_PLATFORM_UTILITY_FAMILIES: dict[StyleProperty, frozenset[str]] = {
    StyleProperty.TEXT_ALIGN: frozenset({"text-start", "text-center", "text-end"}),
    StyleProperty.ITEM_ALIGN: frozenset(
        {"align-items-start", "align-items-center", "align-items-end", "align-items-stretch"}
    ),
    StyleProperty.DISPLAY: frozenset(
        {"d-none", "d-block", "d-inline", "d-inline-block", "d-flex", "d-grid"}
    ),
    StyleProperty.FLEX_DIRECTION: frozenset(
        {"flex-row", "flex-row-reverse", "flex-column", "flex-column-reverse"}
    ),
    StyleProperty.FLEX_WRAP: frozenset({"flex-wrap", "flex-nowrap"}),
    StyleProperty.POSITION: frozenset(
        {"position-relative", "position-absolute", "position-fixed", "position-sticky"}
    ),
    StyleProperty.VISIBILITY: frozenset({"visible", "invisible"}),
}

_THEME_BACKGROUND_PROPERTIES: frozenset[StyleProperty] = frozenset(
    {StyleProperty.BACKGROUND_COLOR, StyleProperty.OVERLAY_COLOR}
)

_CLASS_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _theme_family(property_name: StyleProperty) -> frozenset[str] | None:
    if property_name in _THEME_BACKGROUND_PROPERTIES:
        return frozenset(f"bg-{slot}" for slot in SAFE_THEME_SLOTS)
    if property_name is StyleProperty.TEXT_COLOR:
        return frozenset(f"text-{slot}" for slot in SAFE_THEME_SLOTS)
    return None


def _agency_family(
    property_name: StyleProperty, agency_utilities: Mapping[str, str]
) -> frozenset[str]:
    prefix = f"{property_name.value}:"
    return frozenset(
        target for key, target in agency_utilities.items() if key.startswith(prefix)
    )


def _true_family(
    property_name: StyleProperty,
    layer: TranslationLayer,
    agency_utilities: Mapping[str, str],
) -> frozenset[str] | None:
    """The independently-known-safe class family for a (property, layer) pair.

    Never derived from a caller-supplied ``family`` list -- platform-utility
    and theme families are the module's own static tables; the agency-utility
    family is only ever what the caller explicitly declares as safe.
    """

    if layer is TranslationLayer.PLATFORM_UTILITY:
        return _PLATFORM_UTILITY_FAMILIES.get(property_name)
    if layer is TranslationLayer.THEME:
        return _theme_family(property_name)
    if layer is TranslationLayer.AGENCY_UTILITY:
        family = _agency_family(property_name, agency_utilities)
        return family or None
    return None


def _normalize_source_value(value: str) -> str:
    """Match style_translation.py's own normalization before a mapping lookup.

    The translator strips ``StyleObservation.value`` once (``_string_value``)
    and then ``casefold()``s it at each lookup site (``_utility_decision``,
    ``_agency_decision``). Re-deriving both here -- rather than trusting a
    caller's casing/whitespace -- keeps a legitimate alias like ``" Right "``
    accepted while an unrelated string stays unrelated.
    """

    return value.strip().casefold()


def _expected_platform_or_agency_target(
    property_name: StyleProperty,
    layer: TranslationLayer,
    source_value: str,
    agency_utilities: Mapping[str, str],
) -> str | None:
    """The single class ``source_value`` is declared to produce, if any.

    Returns ``None`` when the layer is not one this function can verify
    exactly (``THEME``: color/typography matching depends on a palette,
    distance threshold, and lookup tables this transport is never given --
    family membership is the most it can confirm there) or when the source
    value has no known mapping at all for this property's layer.
    """

    if layer is TranslationLayer.PLATFORM_UTILITY:
        normalized = _normalize_source_value(source_value)
        return _UTILITY_VALUES.get(property_name, {}).get(normalized)
    if layer is TranslationLayer.AGENCY_UTILITY:
        normalized = _normalize_source_value(source_value)
        return agency_utilities.get(f"{property_name.value}:{normalized}")
    return None


def _validate_target(
    property_name: StyleProperty,
    layer: TranslationLayer,
    source_value: str,
    target: str,
    agency_utilities: Mapping[str, str],
) -> tuple[frozenset[str] | None, str | None]:
    """Validate a claimed (property, layer, source_value) -> target decision.

    Returns ``(family, reason)``: ``reason`` is ``None`` when ``target`` is
    accepted, else a human-readable explanation. ``family`` is always the
    independently recomputed true family for this ``(property, layer)`` when
    one exists -- including on rejection -- so a caller (``apply_native_class_actions``
    via ``build_native_style_report``/``validate_native_class_actions``) can
    still remove every contradictory default from an *accepted* sibling
    decision even though this particular claim was rejected.

    Family membership alone (every class a property's utility can ever
    produce) is necessary but not sufficient: for ``PLATFORM_UTILITY`` and
    ``AGENCY_UTILITY`` the target must also be the *exact* class this
    specific ``source_value`` is declared to produce, recomputed from
    style_translation.py's own canonical table (platform) or the caller's
    explicitly declared mapping (agency) -- never from the incoming
    payload's own claim. ``THEME`` keeps family-membership-only checking:
    exact source-color verification would require the palette and distance
    threshold used at translation time, which this transport is not given.
    """

    family = _true_family(property_name, layer, agency_utilities)
    not_recognized = (
        "is a token/variable identifier, not a confirmed reusable class"
        if layer is TranslationLayer.THEME
        else "is not a recognized or declared safe utility class"
    )
    if not family or target not in family:
        return family, not_recognized

    expected_target = _expected_platform_or_agency_target(
        property_name, layer, source_value, agency_utilities
    )
    if layer in (TranslationLayer.PLATFORM_UTILITY, TranslationLayer.AGENCY_UTILITY):
        if expected_target is None:
            return family, (
                f"source value {source_value!r} has no known mapping for property "
                f"{property_name.value!r} at layer {layer.value!r}"
            )
        if target != expected_target:
            return family, (
                f"does not match {expected_target!r}, the class source value "
                f"{source_value!r} is declared to produce -- family membership alone "
                "is not enough"
            )

    return family, None


class NativeClassAction(_StrictModel):
    """One property/source-value/layer/target/breakpoint decision to apply as a class."""

    property: StyleProperty
    source_value: str = Field(min_length=1)
    layer: TranslationLayer
    target: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    family: tuple[str, ...] = Field(min_length=1, max_length=16)
    breakpoint: BreakpointName | None = None

    @field_validator("layer")
    @classmethod
    def _layer_is_applicable(cls, value: TranslationLayer) -> TranslationLayer:
        if value not in _APPLICABLE_LAYERS:
            raise ValueError(f"layer {value.value!r} has no native-class transport")
        return value

    @field_validator("family")
    @classmethod
    def _family_is_well_formed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("family must not contain duplicate class names")
        if any(not _CLASS_NAME_RE.fullmatch(item) for item in value):
            raise ValueError("family contains an invalid class name")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def _target_in_family(self) -> "NativeClassAction":
        if self.target not in self.family:
            raise ValueError("target must be a member of its own declared family")
        return self


class NativeStyleReport(_StrictModel):
    """Native class actions safe to apply, plus every decision that was not."""

    actions: tuple[NativeClassAction, ...] = ()
    diagnostics: tuple[str, ...] = ()
    important_css_properties: frozenset[str] = frozenset()


def build_native_style_report(
    decisions: Sequence[StyleDecision],
    *,
    agency_utilities: Mapping[str, str] = {},
) -> NativeStyleReport:
    """Classify every style decision as a safe class to apply or a reported gap.

    One action per property survives (the last unconditional decision for
    that property); an earlier decision for the same property is reported as
    superseded rather than silently dropped.

    A ``PLATFORM_UTILITY`` class (Bootstrap's utility API, the only table this
    layer's targets are drawn from -- ``_UTILITY_VALUES``) compiles with
    ``!important`` on every root-inspected target this translator ships a
    default for (see ``style_translation.py``'s own Bootstrap 5.1 target
    note). That class keeps winning the cascade whether it is applied here or
    already baked into the matched template's own default classes, so a
    same-property ``SCOPED_CSS`` decision -- the only way a source's own
    conditional/responsive override for that property is represented -- is
    silently inert unless it is promoted to the same priority. This is a
    narrowly owned, deterministic promotion of the translator's *own*
    generated declaration, decided purely from the (property, layer) shape of
    the already-accepted decisions; it never inspects or relaxes
    ``important_allowlist``, which continues to gate only a *source* value
    that already spells ``!important`` on its own (``style_translation._css_decision``).
    ``important_css_properties`` reports the CSS property names that need
    it; the caller applies it to its own merged ``css_declarations`` via
    ``apply_important_css_properties``.
    """

    actions: dict[StyleProperty, NativeClassAction] = {}
    diagnostics: list[str] = []
    scoped_css_properties = {
        decision.property for decision in decisions if decision.layer is TranslationLayer.SCOPED_CSS
    }
    important_properties: set[StyleProperty] = set()

    for decision in decisions:
        label = f"{decision.property.value}={decision.source_value!r}"

        if decision.property in _MEDIA_ONLY_PROPERTIES:
            if decision.layer in _APPLICABLE_LAYERS:
                diagnostics.append(
                    f"{label}: media-specific property has no unique image/media owner "
                    "at section scope; not applied as a class"
                )
            continue

        if decision.layer is TranslationLayer.TEMPLATE_MODIFIER:
            diagnostics.append(
                f"{label}: template modifier {decision.target!r} is a capability label, "
                "not a runnable transformation; not applied"
            )
            continue

        if decision.layer not in _APPLICABLE_LAYERS:
            # scoped_css/measurement_only/manual already explain themselves
            # through their own existing warning channels.
            continue

        if decision.breakpoint is not None:
            diagnostics.append(
                f"{label}: responsive ({decision.breakpoint.value}) native decision has no "
                "verified responsive utility variant; not applied unconditionally or per breakpoint"
            )
            continue

        family, reason = _validate_target(
            decision.property, decision.layer, decision.source_value, decision.target, agency_utilities
        )
        if reason is not None:
            diagnostics.append(f"{label}: target {decision.target!r} {reason}; not applied")
            continue

        if decision.layer is TranslationLayer.PLATFORM_UTILITY and decision.property in scoped_css_properties:
            important_properties.add(decision.property)
            diagnostics.append(
                f"{label}: platform utility {decision.target!r} compiles with !important on "
                "the installed theme and would silently defeat this property's own scoped "
                "conditional override; that scoped declaration is promoted to !important to "
                "remain effective"
            )

        action = NativeClassAction(
            property=decision.property,
            source_value=decision.source_value,
            layer=decision.layer,
            target=decision.target,
            family=tuple(sorted(family)),
        )
        previous = actions.get(decision.property)
        if previous is not None and previous.target != action.target:
            diagnostics.append(
                f"{decision.property.value}: {previous.target!r} was superseded by "
                f"{action.target!r} from a later decision for the same utility family"
            )
        actions[decision.property] = action

    ordered_actions = tuple(actions[key] for key in sorted(actions, key=lambda item: item.value))
    important_css_properties = frozenset(
        _CSS_PROPERTY_NAMES[property_name]
        for property_name in important_properties
        if property_name in _CSS_PROPERTY_NAMES
    )
    return NativeStyleReport(
        actions=ordered_actions,
        diagnostics=tuple(diagnostics),
        important_css_properties=important_css_properties,
    )


def apply_important_css_properties(
    declarations: Mapping[str, str], important_css_properties: Iterable[str]
) -> dict[str, str]:
    """Promote scoped CSS declarations for colliding properties to !important.

    ``declarations`` is a ``css_declarations``/``scoped_css`` mapping keyed by
    ``style_translation._scoped_css_key`` (``"text-align"``,
    ``"mobile:text-align"``, ``"cond-max480:text-align"``, ...); every key
    ends in the plain CSS property name. A key whose property is in
    ``important_css_properties`` (``NativeStyleReport.important_css_properties``,
    from ``build_native_style_report``) gets ``!important`` appended unless it
    is already there -- covering every conditional bucket for that property at
    once, so "multiple conditional widths" for the same colliding property all
    stay effective. A value with no matching property is returned unchanged,
    so a caller with no collisions gets its input back untouched.
    """

    important = set(important_css_properties)
    if not important:
        return dict(declarations)
    updated: dict[str, str] = {}
    for key, value in declarations.items():
        css_property = key.rsplit(":", 1)[-1]
        if css_property in important and not value.rstrip().casefold().endswith("!important"):
            value = f"{value} !important"
        updated[key] = value
    return updated


# Reverse of _PLATFORM_UTILITY_FAMILIES, keyed by CSS property name instead of
# StyleProperty -- derived once from the same two canonical tables
# (_PLATFORM_UTILITY_FAMILIES, _CSS_PROPERTY_NAMES) rather than a third,
# independently maintained one. Used only to answer "is any class already on
# this component a member of a property's Bootstrap utility family", so a
# scoped CSS rule for that property can be promoted to !important -- the
# family membership check already proven safe for apply_native_class_actions'
# own conflict handling, reused here for a different purpose.
_CSS_PROPERTY_TO_PLATFORM_FAMILY: dict[str, frozenset[str]] = {
    _CSS_PROPERTY_NAMES[property_name]: family
    for property_name, family in _PLATFORM_UTILITY_FAMILIES.items()
    if property_name in _CSS_PROPERTY_NAMES
}


def _component_class_names(component: Mapping[str, Any]) -> set[str]:
    return {
        entry.get("name")
        for entry in component.get("classes", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def important_css_properties_for_component(
    component: Mapping[str, Any], declarations: Mapping[str, str]
) -> frozenset[str]:
    """CSS properties in ``declarations`` that collide with a class already on
    ``component``.

    Call this *after* ``apply_native_class_actions`` has landed this
    request's own actions on ``component``, so a class this translator just
    applied is visible exactly like one already baked into the matched
    template's own default classes (e.g. ``feature-cards-3up.json``'s
    heading always carries ``text-center``, independent of any style
    decision at all -- there is no ``PLATFORM_UTILITY`` decision to inspect
    when a source's *only* observation for a property is the conditional
    override). Reading the component's actual classes, rather than the
    decisions that produced them, is what makes this collision check
    complete: it is the same component a real browser renders, so it is the
    only place this question has one right answer regardless of which path
    put the class there.
    """

    present = _component_class_names(component)
    if not present:
        return frozenset()
    css_properties = {key.rsplit(":", 1)[-1] for key in declarations}
    return frozenset(
        css_property
        for css_property in css_properties
        if present & _CSS_PROPERTY_TO_PLATFORM_FAMILY.get(css_property, frozenset())
    )


def apply_important_to_buckets(
    buckets: Mapping[Any, Mapping[str, str]], important_css_properties: Iterable[str]
) -> dict[Any, dict[str, str]]:
    """``apply_important_css_properties``, for an already-validated bucket map.

    ``style_transport.validate_style_payload`` groups a flat declarations
    mapping into ``{bounds: {css_property: value}}`` buckets; this promotes
    the same way but against that already-parsed shape (a bare ``css_property``
    key, not a ``[breakpoint:|cond-<bounds>:]property`` string), so a caller
    validating before promoting -- the correct order, since it rejects a
    malformed payload before this function ever has to guess at its shape --
    does not have to re-flatten and re-parse keys it has already parsed once.
    """

    important = set(important_css_properties)
    if not important:
        return {bounds: dict(style) for bounds, style in buckets.items()}
    return {
        bounds: {
            css_property: (
                f"{value} !important"
                if css_property in important and not value.rstrip().casefold().endswith("!important")
                else value
            )
            for css_property, value in style.items()
        }
        for bounds, style in buckets.items()
    }


def validate_native_class_actions(
    raw: Any,
    *,
    agency_utilities: Mapping[str, str] | None = None,
) -> tuple[NativeClassAction, ...]:
    """Validate untrusted serialized native-class metadata before composition.

    Mirrors ``style_transport.validate_style_payload``'s role for scoped CSS:
    ``emit_library_plan`` runs on the planner's own trusted plan, but
    ``compose_project_library`` reads a serialized (and therefore untrusted)
    library-plan.json off disk, so the same membership *and* exact
    source-value -> target checks run again at that boundary. The incoming
    ``family`` is used only to satisfy schema shape; every returned action's
    family is replaced with the independently recomputed true family for its
    ``(property, layer)``, so a payload can never smuggle an unrelated class
    in as a "family member" to remove or add -- and a target that is merely
    a member of the right family but not the class its own declared
    ``source_value`` produces is rejected too.
    """

    if not isinstance(raw, list):
        raise NativeStyleTransportError("native_classes must be a list")
    if len(raw) > 32:
        raise NativeStyleTransportError("native_classes has an implausible number of entries")

    resolved_agency_utilities = agency_utilities or {}
    actions: list[NativeClassAction] = []
    seen_properties: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise NativeStyleTransportError(f"native_classes[{index}] must be an object")
        try:
            action = NativeClassAction.model_validate(item)
        except ValidationError as exc:
            raise NativeStyleTransportError(f"native_classes[{index}] is invalid: {exc}") from exc
        if action.breakpoint is not None:
            raise NativeStyleTransportError(
                f"native_classes[{index}]: breakpoint-scoped native class actions are not supported"
            )
        if action.property.value in seen_properties:
            raise NativeStyleTransportError(
                f"native_classes[{index}]: duplicate action for property {action.property.value!r}"
            )
        true_family, reason = _validate_target(
            action.property, action.layer, action.source_value, action.target, resolved_agency_utilities
        )
        if reason is not None:
            raise NativeStyleTransportError(
                f"native_classes[{index}]: target {action.target!r} {reason} "
                f"for property {action.property.value!r} and layer {action.layer.value!r}"
            )
        seen_properties.add(action.property.value)
        actions.append(action.model_copy(update={"family": tuple(sorted(true_family))}))
    return tuple(actions)


def apply_native_class_actions(
    component: dict[str, Any], actions: Sequence[NativeClassAction]
) -> None:
    """Apply every action's target class to ``component``, resolving family conflicts.

    ``component`` is the section root of a rendered template. Removes every
    other member of an action's utility family already present -- including a
    template's own baked-in default -- before adding the target, so two
    classes from the same utility can never both land. Only the ``classes``
    list is touched; content, attributes, component type and every unrelated
    class are left exactly as composed.
    """

    if not actions:
        return
    classes = component.setdefault("classes", [])
    for action in actions:
        family = set(action.family)
        classes[:] = [
            entry
            for entry in classes
            if not (isinstance(entry, dict) and entry.get("name") in family)
        ]
        if not any(isinstance(entry, dict) and entry.get("name") == action.target for entry in classes):
            classes.append({"name": action.target, "active": False})
