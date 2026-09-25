"""Exact source-value/property/layer -> target semantic validation.

Family membership (every class a property's utility layer can ever produce)
is necessary but not sufficient: a target must also be the exact class its
own declared ``source_value`` produces. This file exercises the fix for two
gaps that survived pure family-membership checking:

* ``PLATFORM_UTILITY``: a same-family target for a *different* source value
  (e.g. ``text_align`` source ``right`` claiming ``text-start``) used to be
  accepted because ``text-start`` is a member of the text-align family.
* ``AGENCY_UTILITY``: a same-family target for a different declared mapping
  (e.g. ``order`` source ``2`` claiming ``order-1`` when both ``order-1``
  and ``order-2`` are declared) used to be accepted for the same reason.

These are covered end to end (``build_native_style_report`` on trusted
planner decisions, ``validate_native_class_actions`` on untrusted payloads,
and the real ``compose_project_library`` boundary) so the serializer can
never emit -- and the composer can never accept -- an action its own
validator would reject.
"""

from __future__ import annotations

from pathlib import Path
import runpy

import pytest

from vanjaro_cli.design.models import StyleObservation, StyleProperty, StyleSet
from vanjaro_cli.design.native_style_transport import (
    NativeClassAction,
    NativeStyleTransportError,
    build_native_style_report,
    validate_native_class_actions,
)
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.design.style_translation import StyleDecision, StyleTranslationConfig, TranslationLayer
from vanjaro_cli.portal.block_library import BlockLibraryError, compose_project_library

_FIXTURE = runpy.run_path(str(Path(__file__).resolve().parent / "test_design_planner.py"))
_feature_section = _FIXTURE["_feature_section"]
_document = _FIXTURE["_document"]
CATALOG = _FIXTURE["CATALOG"]


def _decision(**overrides) -> StyleDecision:
    base = dict(
        property=StyleProperty.TEXT_ALIGN,
        source_value="right",
        layer=TranslationLayer.PLATFORM_UTILITY,
        target="text-end",
        confidence=1.0,
        distance=0.0,
        reason="test decision",
    )
    base.update(overrides)
    return StyleDecision(**base)


# --- wrong same-family target: platform utility -----------------------------


def test_validate_rejects_wrong_target_within_the_same_platform_family():
    raw = [
        {
            "property": "text_align",
            "source_value": "right",
            "layer": "platform_utility",
            "target": "text-start",
            "family": ["text-center", "text-end", "text-start"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError, match="does not match"):
        validate_native_class_actions(raw)


def test_build_report_rejects_wrong_target_within_the_same_platform_family():
    """A trusted-looking StyleDecision is still checked -- the report builder
    must not emit an action its own validator would then reject."""

    decision = _decision(source_value="right", target="text-start")
    report = build_native_style_report([decision])
    assert report.actions == ()
    assert any("does not match" in warning for warning in report.diagnostics)


# --- wrong same-family target: agency utility -------------------------------


def test_validate_rejects_wrong_target_within_the_same_agency_family():
    agency_utilities = {"order:1": "order-1", "order:2": "order-2"}
    raw = [
        {
            "property": "order",
            "source_value": "2",
            "layer": "agency_utility",
            "target": "order-1",
            "family": ["order-1", "order-2"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError, match="does not match"):
        validate_native_class_actions(raw, agency_utilities=agency_utilities)


def test_build_report_rejects_wrong_target_within_the_same_agency_family():
    agency_utilities = {"order:1": "order-1", "order:2": "order-2"}
    decision = _decision(
        property=StyleProperty.ORDER,
        source_value="2",
        layer=TranslationLayer.AGENCY_UTILITY,
        target="order-1",
    )
    report = build_native_style_report([decision], agency_utilities=agency_utilities)
    assert report.actions == ()
    assert any("does not match" in warning for warning in report.diagnostics)


# --- exact agency mapping accepted, end to end through compose -------------


def test_exact_agency_mapping_is_accepted_through_compose_project_library():
    agency_utilities = {"order:1": "order-1", "order:2": "order-2"}
    raw = [
        {
            "property": "order",
            "source_value": "2",
            "layer": "agency_utility",
            "target": "order-2",
            "family": ["order-1", "order-2"],
            "breakpoint": None,
        }
    ]
    actions = validate_native_class_actions(raw, agency_utilities=agency_utilities)
    assert actions[0].target == "order-2"
    assert actions[0].family == ("order-1", "order-2")

    section = _feature_section().model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.ORDER, value="2")])}
    )
    document = _document(section)
    config = StyleTranslationConfig(agency_utilities=agency_utilities)
    plan = plan_design_document(document, catalog=CATALOG, style_config=config)
    library = emit_library_plan(plan, agency_utilities=agency_utilities)
    blocks = compose_project_library(library, agency_utilities=agency_utilities)
    block = next(item for item in blocks if item["key"] == plan.entries[0].source_section_id)
    classes = {
        entry["name"]
        for entry in block["content_json"][0].get("classes", [])
        if isinstance(entry, dict)
    }
    assert "order-2" in classes


# --- legitimate platform aliases: case and whitespace normalization --------


@pytest.mark.parametrize("source_value", ["Right", " right ", "RIGHT", "\tright\n"])
def test_platform_alias_case_and_whitespace_is_normalized_like_the_translator(source_value):
    raw = [
        {
            "property": "text_align",
            "source_value": source_value,
            "layer": "platform_utility",
            "target": "text-end",
            "family": ["text-center", "text-end", "text-start"],
            "breakpoint": None,
        }
    ]
    actions = validate_native_class_actions(raw)
    assert actions[0].target == "text-end"


# --- unsupported / unknown source values ------------------------------------


def test_validate_rejects_an_unknown_source_value_for_platform_utility():
    raw = [
        {
            "property": "text_align",
            "source_value": "diagonal",
            "layer": "platform_utility",
            "target": "text-end",
            "family": ["text-center", "text-end", "text-start"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError, match="no known mapping"):
        validate_native_class_actions(raw)


def test_validate_rejects_an_unknown_source_value_for_agency_utility():
    agency_utilities = {"order:1": "order-1"}
    raw = [
        {
            "property": "order",
            "source_value": "99",
            "layer": "agency_utility",
            "target": "order-1",
            "family": ["order-1"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError, match="no known mapping"):
        validate_native_class_actions(raw, agency_utilities=agency_utilities)


# --- malicious family metadata: attacker-declared family is never trusted --


def test_validate_ignores_a_malicious_family_claim_and_still_rejects_wrong_target():
    """An attacker padding ``family`` with an unrelated class must not widen
    what a mismatched target can sneak past -- the true family is always
    recomputed from the static tables, never taken from the payload."""

    raw = [
        {
            "property": "text_align",
            "source_value": "right",
            "layer": "platform_utility",
            "target": "text-start",
            # Attacker-declared family widened with a class from a different
            # property entirely, plus a self-serving claim that text-start
            # is a family member (which it is, but only for text_align).
            "family": ["text-start", "d-flex", "d-none"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError, match="does not match"):
        validate_native_class_actions(raw)


def test_validate_recomputes_family_rather_than_trusting_the_payload():
    agency_utilities = {"order:1": "order-1"}
    raw = [
        {
            "property": "order",
            "source_value": "1",
            "layer": "agency_utility",
            "target": "order-1",
            "family": ["order-1", "order-999"],  # order-999 is not declared
            "breakpoint": None,
        }
    ]
    actions = validate_native_class_actions(raw, agency_utilities=agency_utilities)
    assert actions[0].family == ("order-1",)


# --- theme: family-membership-only limitation stays explicit ----------------


def test_theme_target_outside_its_safe_family_is_still_rejected_by_membership_only():
    """THEME has no per-source-value exact check here -- color matching needs
    the palette and distance threshold used at translation time, which this
    transport is never given. Family membership is the only thing verified;
    this test documents that boundary rather than inventing a palette check."""

    raw = [
        {
            "property": "background_color",
            "source_value": "#112233",
            "layer": "theme",
            "target": "bg-tertiary",  # not a Bootstrap 5.1 safe theme slot
            "family": ["bg-tertiary"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError, match="not a known-safe|is a token"):
        validate_native_class_actions(raw)


# --- malformed metadata still rejected before any action applies -----------


def test_validate_rejects_malformed_action_before_semantic_checks_run():
    raw = [{"property": "text_align", "source_value": "right", "layer": "platform_utility"}]
    with pytest.raises(NativeStyleTransportError):
        validate_native_class_actions(raw)


# --- unchanged caller inputs -------------------------------------------------


def test_validate_does_not_mutate_the_caller_supplied_payload():
    raw = [
        {
            "property": "text_align",
            "source_value": "right",
            "layer": "platform_utility",
            "target": "text-end",
            "family": ["text-center", "text-end", "text-start"],
            "breakpoint": None,
        }
    ]
    agency_utilities = {"order:1": "order-1"}
    snapshot = [dict(item) for item in raw]
    agency_snapshot = dict(agency_utilities)

    validate_native_class_actions(raw, agency_utilities=agency_utilities)

    assert raw == snapshot
    assert agency_utilities == agency_snapshot


def test_native_class_action_target_must_still_be_a_declared_family_member():
    with pytest.raises(Exception):
        NativeClassAction(
            property=StyleProperty.TEXT_ALIGN,
            source_value="right",
            layer=TranslationLayer.PLATFORM_UTILITY,
            target="text-end",
            family=("text-start", "text-center"),
        )
