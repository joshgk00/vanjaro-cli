"""``serialize_library_plan`` / ``emit_library_plan`` must never silently drop
an ``AGENCY_UTILITY`` decision that was already accepted at planning time.

``plan_design_document`` decides whether a style observation resolves to an
``AGENCY_UTILITY`` class using the ``agency_utilities`` mapping in its
``style_config``. That decision is baked into the ``CompositionPlan`` as a
``StyleDecision`` -- it does not carry the mapping itself. Emission (whether
through ``emit_library_plan`` directly or via ``serialize_library_plan``)
must be given the same mapping again, explicitly, or it has no way to
re-confirm the class is still safe to apply. Omitting, emptying, or changing
that mapping must raise an actionable ``PlanningError`` naming the section or
element and the mapping problem, never fall back to silently emitting a
plan with the decision missing.
"""

from __future__ import annotations

import json

import pytest

from tests.test_design_planner import CATALOG, _document, _feature_section
from vanjaro_cli.design.models import BreakpointName, StyleObservation, StyleProperty, StyleSet
from vanjaro_cli.design.planner import (
    PlanningError,
    emit_library_plan,
    plan_design_document,
    serialize_library_plan,
)
from vanjaro_cli.design.style_translation import StyleTranslationConfig, TranslationLayer
from vanjaro_cli.portal.block_library import compose_project_library

_AGENCY_MAPPING = {"order:2": "order-2"}


def _plan_with_agency_decision(owner: str):
    section = _feature_section()
    style = StyleSet(observations=[StyleObservation(property=StyleProperty.ORDER, value="2")])
    if owner == "section":
        section = section.model_copy(update={"style": style})
    else:
        first, *rest = section.content
        section = section.model_copy(
            update={"content": [first.model_copy(update={"style": style}), *rest]}
        )
    return plan_design_document(
        _document(section),
        catalog=CATALOG,
        style_config=StyleTranslationConfig(agency_utilities=_AGENCY_MAPPING),
    )


def _native_classes(payload: list[dict], owner: str) -> list[dict]:
    if owner == "section":
        return payload[0].get("native_classes", [])
    return [
        action
        for element in payload[0].get("element_styles", [])
        for action in element.get("native_classes", [])
    ]


@pytest.mark.parametrize("owner", ["section", "element"])
def test_valid_context_is_preserved_through_emit_and_serialize(owner: str) -> None:
    plan = _plan_with_agency_decision(owner)

    emitted = emit_library_plan(plan, agency_utilities=_AGENCY_MAPPING)
    assert any(action["target"] == "order-2" for action in _native_classes(emitted, owner))

    serialized = json.loads(serialize_library_plan(plan, agency_utilities=_AGENCY_MAPPING))
    assert any(action["target"] == "order-2" for action in _native_classes(serialized, owner))
    assert compose_project_library(serialized, agency_utilities=_AGENCY_MAPPING)


@pytest.mark.parametrize("owner", ["section", "element"])
def test_omitted_context_raises_instead_of_dropping(owner: str) -> None:
    plan = _plan_with_agency_decision(owner)
    with pytest.raises(PlanningError, match="(?i)agency|mapping"):
        emit_library_plan(plan)
    with pytest.raises(PlanningError, match="(?i)agency|mapping"):
        serialize_library_plan(plan)


@pytest.mark.parametrize("owner", ["section", "element"])
def test_empty_context_raises_instead_of_dropping(owner: str) -> None:
    plan = _plan_with_agency_decision(owner)
    with pytest.raises(PlanningError, match="(?i)agency|mapping"):
        emit_library_plan(plan, agency_utilities={})
    with pytest.raises(PlanningError, match="(?i)agency|mapping"):
        serialize_library_plan(plan, agency_utilities={})


@pytest.mark.parametrize("owner", ["section", "element"])
def test_mismatched_context_raises_instead_of_dropping(owner: str) -> None:
    plan = _plan_with_agency_decision(owner)
    changed = {"order:2": "order-1"}
    with pytest.raises(PlanningError, match="(?i)agency|mapping") as excinfo:
        serialize_library_plan(plan, agency_utilities=changed)
    message = str(excinfo.value)
    assert plan.entries[0].source_section_id in message


@pytest.mark.parametrize("owner", ["section", "element"])
def test_direct_emission_is_not_a_bypass(owner: str) -> None:
    """``emit_library_plan`` itself must refuse the loss, not just its caller."""

    plan = _plan_with_agency_decision(owner)
    with pytest.raises(PlanningError, match="(?i)agency|mapping"):
        emit_library_plan(plan, agency_utilities=None)
    with pytest.raises(PlanningError, match="(?i)agency|mapping"):
        emit_library_plan(plan, agency_utilities={"order:2": "order-1"})


def test_two_mappings_used_sequentially_do_not_leak() -> None:
    """Using one plan's mapping must not affect the next call's own mapping."""

    section_plan = _plan_with_agency_decision("section")
    element_plan = _plan_with_agency_decision("element")
    other_mapping = {"order:2": "order-9"}

    first = serialize_library_plan(section_plan, agency_utilities=_AGENCY_MAPPING)
    assert "order-2" in first

    with pytest.raises(PlanningError):
        serialize_library_plan(element_plan, agency_utilities=other_mapping)

    # The first plan's own correct mapping must still work identically after
    # a failing call using an unrelated mapping for a different plan.
    second = serialize_library_plan(section_plan, agency_utilities=_AGENCY_MAPPING)
    assert first == second

    third = serialize_library_plan(element_plan, agency_utilities=_AGENCY_MAPPING)
    assert "order-2" in third


@pytest.mark.parametrize("owner", ["section", "element"])
def test_serialization_is_deterministic(owner: str) -> None:
    plan = _plan_with_agency_decision(owner)
    before = plan.model_dump(mode="json")
    first = serialize_library_plan(plan, agency_utilities=_AGENCY_MAPPING)
    second = serialize_library_plan(plan, agency_utilities=_AGENCY_MAPPING)
    assert first == second
    assert plan.model_dump(mode="json") == before


def _agency_decision(plan) -> object:
    entry = plan.entries[0]
    return next(d for d in entry.style_decisions if d.layer is TranslationLayer.AGENCY_UTILITY)


def _with_extra_decisions(plan, decisions: tuple):
    entry = plan.entries[0]
    changed_entry = entry.model_copy(update={"style_decisions": decisions})
    return plan.model_copy(update={"entries": (changed_entry, *plan.entries[1:])})


def test_later_valid_decision_legitimately_supersedes_earlier() -> None:
    """A later decision that actually resolves under the supplied mapping is a
    real supersession: no error, and the later target is what gets emitted."""

    plan = _plan_with_agency_decision("section")
    accepted = _agency_decision(plan)
    earlier = accepted.model_copy(update={"source_value": "1", "target": "order-1"})
    entry = plan.entries[0]
    changed_plan = _with_extra_decisions(plan, (earlier, *entry.style_decisions))

    encoded = serialize_library_plan(changed_plan, agency_utilities=_AGENCY_MAPPING)
    payload = json.loads(encoded)
    assert any(action["target"] == "order-2" for action in _native_classes(payload, "section"))


def test_responsive_echo_cannot_mask_a_lost_later_agency_choice() -> None:
    """Root-confirmed regression: an earlier valid order:1 decision, a later
    accepted order:2 decision whose mapping context is now missing, and a
    still-later responsive-only echo of order:1 must still raise -- the echo
    never becomes a native action (it is breakpoint-scoped), so it cannot be
    credited as a later valid replacement for the lost order:2 decision."""

    plan = _plan_with_agency_decision("section")
    accepted = _agency_decision(plan)
    earlier = accepted.model_copy(update={"source_value": "1", "target": "order-1"})
    echo = earlier.model_copy(update={"breakpoint": BreakpointName.MOBILE})
    entry = plan.entries[0]
    decisions = (earlier, *entry.style_decisions, echo)
    changed_plan = _with_extra_decisions(plan, decisions)

    with pytest.raises(PlanningError, match="(?i)agency|mapping") as excinfo:
        serialize_library_plan(changed_plan, agency_utilities={"order:1": "order-1"})
    assert plan.entries[0].source_section_id in str(excinfo.value)


def test_default_no_agency_project_is_unaffected() -> None:
    """A plan with no agency decisions must serialize the same with or
    without an ``agency_utilities`` argument -- no new requirement for
    ordinary projects that never used agency utilities."""

    plan = plan_design_document(_document(_feature_section()), catalog=CATALOG)
    without_context = serialize_library_plan(plan)
    with_empty_context = serialize_library_plan(plan, agency_utilities={})
    with_unrelated_context = serialize_library_plan(plan, agency_utilities={"order:9": "order-9"})
    assert without_context == with_empty_context == with_unrelated_context
