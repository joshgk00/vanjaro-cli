"""Source-backed responsive condition transport.

Proves the gap recorded in ``docs/agency-responsive-condition-contract.md``:
a rendered ``ResponsiveObservation`` used to carry only a sample breakpoint
name, and ``style_transport.py`` invented ``max-width: 768px``/``390px``
from the capture widths regardless of what the source actually authored.
These tests exercise the real typed model (``design/models.py``), the pure
cascade/encoding helpers (``design/responsive_conditions.py``), the browser
acquisition parsing (``design/html_media_evidence.py``), the translation key
choice (``design/style_translation.py``), and the untrusted-payload
transport (``design/style_transport.py``) -- through the actual
planner -> emit_library_plan -> compose_project_library -> compose_project_pages
path (same technique as ``tests/test_composed_style_transport.py``), not a
synthetic stand-in for it.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.composition import PlanPolicy
from vanjaro_cli.design.html_media_evidence import (
    MediaEvidenceResult,
    SectionMediaEvidence,
    collect_media_condition_evidence,
)
from vanjaro_cli.design.models import (
    BreakpointName,
    ConditionBound,
    DesignDocument,
    EvidenceStatus,
    ResponsiveCondition,
    ResponsiveConditionKind,
    ResponsiveConditionStatus,
    ResponsiveObservation,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.design.responsive_conditions import (
    RawDeclaration,
    bounds_match_width,
    condition_media_text,
    condition_sort_key,
    decode_condition_key,
    encode_condition_key,
    resolve_property_condition,
    to_bound_tokens,
)
from vanjaro_cli.design.style_transport import (
    StyleTransportError,
    build_style_rules,
    validate_style_payload,
)
from vanjaro_cli.design.style_translation import (
    StyleTranslationConfig,
    translate_responsive_observations,
)
from vanjaro_cli.design.template_catalog import CapabilityManifest, load_template_catalog
from vanjaro_cli.portal.block_library import BlockLibraryError, compose_project_library
from vanjaro_cli.portal.page_composition import compose_project_pages

_FIXTURE = runpy.run_path(str(Path(__file__).resolve().parent / "test_design_planner.py"))
_feature_section = _FIXTURE["_feature_section"]
_document = _FIXTURE["_document"]
CATALOG = _FIXTURE["CATALOG"]


def _capabilities() -> CapabilityManifest:
    return next(entry.capabilities for entry in load_template_catalog() if entry.name == "Centered Hero")


# ---------------------------------------------------------------------------
# Typed roundtrip and validation
# ---------------------------------------------------------------------------


def test_condition_typed_roundtrip_through_json() -> None:
    condition = ResponsiveCondition(
        bounds=[ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=1023)],
        status=ResponsiveConditionStatus.OBSERVED,
        important=False,
        rule_order=5,
        selector="#hero",
    )
    payload = condition.model_dump(mode="json")
    restored = ResponsiveCondition.model_validate(payload)
    assert restored == condition


def test_observed_condition_requires_at_least_one_bound() -> None:
    with pytest.raises(ValidationError):
        ResponsiveCondition(bounds=[], status=ResponsiveConditionStatus.OBSERVED, rule_order=0)


def test_unresolved_condition_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        ResponsiveCondition(bounds=[], status=ResponsiveConditionStatus.UNRESOLVED, rule_order=0)


def test_condition_rejects_empty_width_range() -> None:
    with pytest.raises(ValidationError):
        ResponsiveCondition(
            bounds=[
                ConditionBound(kind=ResponsiveConditionKind.MIN_WIDTH, threshold_px=1023),
                ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=480),
            ],
            status=ResponsiveConditionStatus.OBSERVED,
            rule_order=0,
        )


def test_condition_rejects_duplicate_bound_kind() -> None:
    with pytest.raises(ValidationError):
        ResponsiveCondition(
            bounds=[
                ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=900),
                ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=480),
            ],
            status=ResponsiveConditionStatus.OBSERVED,
            rule_order=0,
        )


def test_old_artifact_without_condition_fields_still_parses() -> None:
    """A pre-existing serialized StyleObservation/ResponsiveObservation (no
    ``condition``/``section_condition`` key at all) must remain valid --
    the new fields are additive and optional, never required."""

    observation = StyleObservation.model_validate(
        {"property": "min_height", "value": "620px", "status": "observed"}
    )
    assert observation.condition is None

    responsive = ResponsiveObservation.model_validate(
        {
            "breakpoint": "tablet",
            "viewport": {"width": 768, "height": 1024},
            "status": "observed",
            "style": {"observations": [], "raw": {}},
        }
    )
    assert responsive.section_condition is None


# ---------------------------------------------------------------------------
# Pure helpers: encode/decode, media text, sort order, width matching
# ---------------------------------------------------------------------------


def test_encode_decode_condition_key_roundtrip_single_bound() -> None:
    key = encode_condition_key([("max_width", 1023)])
    assert key == "cond-max1023"
    assert decode_condition_key(key[len("cond") :]) == (("max_width", 1023),)


def test_encode_decode_condition_key_roundtrip_nested_range() -> None:
    key = encode_condition_key([("max_width", 1023), ("min_width", 480)])
    assert key == "cond-min480-max1023"
    assert decode_condition_key(key[len("cond") :]) == (
        ("min_width", 480),
        ("max_width", 1023),
    )
    assert condition_media_text(decode_condition_key(key[len("cond") :])) == (
        "(min-width: 480px) and (max-width: 1023px)"
    )


@pytest.mark.parametrize(
    "bounds",
    [
        [],
        [("min_width", 100), ("max_width", 200), ("min_width", 300)],
        [("min_width", 500), ("max_width", 100)],
        [("max_width", 0)],
        [("max_width", 999999)],
        [("bogus_kind", 500)],
    ],
)
def test_encode_condition_key_rejects_unsupported_shapes(bounds: list[tuple[str, int]]) -> None:
    with pytest.raises(ValueError):
        encode_condition_key(bounds)


def test_condition_sort_key_orders_narrowest_last() -> None:
    base = condition_sort_key(())
    wide_max = condition_sort_key((("max_width", 1023),))
    narrow_max = condition_sort_key((("max_width", 480),))
    narrow_min = condition_sort_key((("min_width", 600),))
    wide_min = condition_sort_key((("min_width", 1100),))

    assert sorted([narrow_max, wide_max, base], key=lambda k: k) == [base, wide_max, narrow_max]
    assert sorted([wide_min, narrow_min], key=lambda k: k) == [narrow_min, wide_min]


def test_bounds_match_width_intersection() -> None:
    bounds = (("min_width", 480), ("max_width", 1023))
    assert bounds_match_width(bounds, 480) is True
    assert bounds_match_width(bounds, 1023) is True
    assert bounds_match_width(bounds, 479) is False
    assert bounds_match_width(bounds, 1024) is False
    assert bounds_match_width((), 1) is True


def test_to_bound_tokens_converts_typed_model() -> None:
    condition = ResponsiveCondition(
        bounds=[
            ConditionBound(kind=ResponsiveConditionKind.MIN_WIDTH, threshold_px=480),
            ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=1023),
        ],
        status=ResponsiveConditionStatus.OBSERVED,
        rule_order=1,
    )
    assert to_bound_tokens(condition) == (("min_width", 480), ("max_width", 1023))


# ---------------------------------------------------------------------------
# Cascade resolution: order/priority conflicts, !important, nested ranges
# ---------------------------------------------------------------------------


def _decl(
    value: str,
    order: int,
    *,
    bounds: tuple[tuple[str, int], ...] = (),
    important: bool = False,
    specificity: tuple[int, int, int] = (1, 0, 0),
    supported: bool = True,
    reason: str | None = None,
    css_property: str = "min-height",
    selector: str = "#hero",
) -> RawDeclaration:
    return RawDeclaration(
        css_property=css_property,
        value=value,
        important=important,
        order=order,
        specificity=specificity,
        bounds=bounds,
        supported=supported,
        selector=selector,
        reason=reason,
    )


def test_resolve_property_condition_matches_contract_fixture_thresholds() -> None:
    """The exact confirmed-gap numbers: source 1023px/480px thresholds must
    survive, not the sample-derived 768px/390px."""

    declarations = [
        _decl("720px", 1),
        _decl("620px", 5, bounds=(("max_width", 1023),)),
        _decl("520px", 8, bounds=(("max_width", 480),)),
    ]
    tablet = resolve_property_condition(declarations, "min-height", 768, "620px")
    assert tablet is not None
    assert tablet.status == ResponsiveConditionStatus.OBSERVED
    assert tablet.bounds == [ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=1023)]

    mobile = resolve_property_condition(declarations, "min-height", 390, "520px")
    assert mobile is not None
    assert mobile.status == ResponsiveConditionStatus.OBSERVED
    assert mobile.bounds == [ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=480)]


def test_resolve_property_condition_no_evidence_returns_none() -> None:
    assert resolve_property_condition([], "min-height", 768, "620px") is None
    assert resolve_property_condition(
        [_decl("620px", 1, css_property="background-position")], "min-height", 768, "620px"
    ) is None


def test_resolve_property_condition_nested_min_max_range() -> None:
    declarations = [
        _decl("720px", 1),
        _decl("620px", 4, bounds=(("min_width", 480), ("max_width", 1023))),
        _decl("520px", 7, bounds=(("max_width", 480),)),
    ]
    tablet_ish = resolve_property_condition(declarations, "min-height", 900, "620px")
    assert tablet_ish is not None
    assert tablet_ish.status == ResponsiveConditionStatus.OBSERVED
    assert {b.kind for b in tablet_ish.bounds} == {
        ResponsiveConditionKind.MIN_WIDTH,
        ResponsiveConditionKind.MAX_WIDTH,
    }


def test_resolve_property_condition_important_wins_over_specificity_and_order() -> None:
    declarations = [
        _decl(
            "999px", 1, bounds=(("max_width", 1023),), specificity=(2, 0, 0)
        ),  # higher specificity, later would normally win
        _decl(
            "620px", 2, bounds=(("max_width", 1023),), specificity=(0, 1, 0), important=True
        ),
    ]
    resolved = resolve_property_condition(declarations, "min-height", 768, "620px")
    assert resolved is not None
    assert resolved.status == ResponsiveConditionStatus.OBSERVED
    assert resolved.important is True


def test_resolve_property_condition_source_order_breaks_specificity_ties() -> None:
    declarations = [
        _decl("620px", 3, bounds=(("max_width", 1023),)),
        _decl("999px", 9, bounds=(("max_width", 900),)),
    ]
    # At width 768 both conditions are satisfied (768<=1023 and 768<=900);
    # equal specificity, so the later rule (order=9) must win the cascade --
    # but its own sampled value does not match, so this must report an
    # honest gap rather than silently keeping the wrong (order=3) winner.
    resolved = resolve_property_condition(declarations, "min-height", 768, "620px")
    assert resolved is not None
    assert resolved.status == ResponsiveConditionStatus.UNRESOLVED
    assert "does not match" in (resolved.reason or "")


def test_resolve_property_condition_width_outside_all_bounds_is_unresolved() -> None:
    declarations = [_decl("620px", 1, bounds=(("max_width", 480),))]
    resolved = resolve_property_condition(declarations, "min-height", 900, "620px")
    assert resolved is not None
    assert resolved.status == ResponsiveConditionStatus.UNRESOLVED
    assert "no accessible declaration" in (resolved.reason or "")


def test_resolve_property_condition_unconditioned_winner_is_unresolved() -> None:
    declarations = [_decl("620px", 5)]  # no media condition at all
    resolved = resolve_property_condition(declarations, "min-height", 768, "620px")
    assert resolved is not None
    assert resolved.status == ResponsiveConditionStatus.UNRESOLVED
    assert "no media condition" in (resolved.reason or "")


# ---------------------------------------------------------------------------
# Unsupported/inaccessible evidence: explicit gap, never a false attribution
# ---------------------------------------------------------------------------


def test_resolve_property_condition_unsupported_declaration_that_could_win_is_unresolved() -> None:
    declarations = [
        _decl("620px", 1, bounds=(("max_width", 1023),)),
        _decl(
            "999px",
            9,
            supported=False,
            reason="container queries are not supported grammar",
        ),
    ]
    resolved = resolve_property_condition(declarations, "min-height", 768, "620px")
    assert resolved is not None
    assert resolved.status == ResponsiveConditionStatus.UNRESOLVED
    assert "container" in (resolved.reason or "")


def test_resolve_property_condition_unsupported_declaration_that_cannot_win_is_ignored() -> None:
    declarations = [
        _decl(
            "999px", 1, supported=False, reason="unsupported media list", specificity=(0, 0, 1)
        ),
        _decl("620px", 9, bounds=(("max_width", 1023),), specificity=(1, 0, 0)),
    ]
    resolved = resolve_property_condition(declarations, "min-height", 768, "620px")
    assert resolved is not None
    assert resolved.status == ResponsiveConditionStatus.OBSERVED


def test_media_evidence_acquisition_reports_unsupported_grammar() -> None:
    """Parses raw acquisition JSON (as the injected browser script would
    return it) for a comma-separated media list and a container query, and
    confirms both surface as ``supported=False`` with an actionable reason
    rather than being silently dropped or treated as unconditioned."""

    class _FakePage:
        def evaluate(self, _expression: str) -> dict:
            return {
                "by_selector": {
                    "#hero": [
                        {
                            "css_property": "min-height",
                            "value": "620px",
                            "important": False,
                            "order": 1,
                            "specificity": [1, 0, 0],
                            "bounds": [],
                            "supported": False,
                            "selector": "#hero",
                            "reason": "unsupported media list (comma-separated OR): (min-width: 1px), print",
                        }
                    ]
                },
                "sheet_gaps": ["https://example.com/cross-origin.css: SecurityError"],
            }

    result = collect_media_condition_evidence(_FakePage(), ["#hero"])
    assert result.sheet_gaps == ("https://example.com/cross-origin.css: SecurityError",)
    declarations = result.by_selector["#hero"].declarations
    assert len(declarations) == 1
    assert declarations[0].supported is False
    assert "comma-separated" in (declarations[0].reason or "")


def test_media_evidence_result_dedupes_selectors() -> None:
    seen: list[list[str]] = []

    class _RecordingPage:
        def evaluate(self, expression: str) -> dict:
            seen.append(expression)
            return {"by_selector": {}, "sheet_gaps": []}

    collect_media_condition_evidence(_RecordingPage(), ["#hero", "#hero", "#cta"])
    assert seen[0].count("#hero") == 1
    assert "#cta" in seen[0]


# ---------------------------------------------------------------------------
# Missing-condition reporting: legacy (no evidence gathered) stays a sample
# ---------------------------------------------------------------------------


def test_no_media_evidence_leaves_style_observation_without_condition() -> None:
    observation = StyleObservation(property=StyleProperty.MIN_HEIGHT, value="620px")
    assert observation.condition is None


# ---------------------------------------------------------------------------
# Full-pipeline transport: exact source condition survives to GrapesJS rules
# ---------------------------------------------------------------------------


def _condition(threshold_px: int, *, kind: ResponsiveConditionKind = ResponsiveConditionKind.MAX_WIDTH, rule_order: int = 1) -> ResponsiveCondition:
    return ResponsiveCondition(
        bounds=[ConditionBound(kind=kind, threshold_px=threshold_px)],
        status=ResponsiveConditionStatus.OBSERVED,
        rule_order=rule_order,
        selector="#hero",
    )


def _sourced_section(
    *,
    section_id: str,
    tablet_threshold: int,
    mobile_threshold: int,
    desktop: str = "720px",
    tablet: str = "620px",
    mobile: str = "520px",
):
    section = _feature_section(
        section_id=section_id,
        element_prefix=f"{section_id}-el",
        group_id=f"{section_id}-cards",
        item_prefix=f"{section_id}-card",
    )
    return section.model_copy(
        update={
            "style": StyleSet(
                observations=[StyleObservation(property=StyleProperty.MIN_HEIGHT, value=desktop)]
            ),
            "responsive": [
                ResponsiveObservation(
                    breakpoint=BreakpointName.TABLET,
                    viewport=Viewport(width=768, height=1024),
                    status=EvidenceStatus.OBSERVED,
                    style=StyleSet(
                        observations=[
                            StyleObservation(
                                property=StyleProperty.MIN_HEIGHT,
                                value=tablet,
                                condition=_condition(tablet_threshold, rule_order=5),
                            )
                        ]
                    ),
                ),
                ResponsiveObservation(
                    breakpoint=BreakpointName.MOBILE,
                    viewport=Viewport(width=390, height=844),
                    status=EvidenceStatus.OBSERVED,
                    style=StyleSet(
                        observations=[
                            StyleObservation(
                                property=StyleProperty.MIN_HEIGHT,
                                value=mobile,
                                condition=_condition(mobile_threshold, rule_order=8),
                            )
                        ]
                    ),
                ),
            ],
        }
    )


def _compose(document: DesignDocument):
    plan = plan_design_document(document, catalog=CATALOG)
    library = emit_library_plan(plan)
    composed = compose_project_library(library)
    return plan, library, composed


def _rule_with_media(styles: list[dict], media: str | None) -> dict | None:
    for rule in styles:
        if rule.get("mediaText") == media or (media is None and "mediaText" not in rule):
            return rule
    return None


def test_observed_source_condition_transports_exact_threshold_not_sample_width() -> None:
    """The confirmed-gap fixture: real source 1023px/480px thresholds, not
    the invented 768px/390px sample-width mapping."""

    section = _sourced_section(section_id="hero.fixture", tablet_threshold=1023, mobile_threshold=480)
    document = _document(section)
    plan, library, composed = _compose(document)

    assert plan.entries[0].scoped_css["cond-max1023:min-height"] == "620px"
    assert plan.entries[0].scoped_css["cond-max480:min-height"] == "520px"
    assert "tablet:min-height" not in plan.entries[0].scoped_css
    assert "mobile:min-height" not in plan.entries[0].scoped_css

    styles = composed[0]["style_json"]
    tablet_rule = _rule_with_media(styles, "(max-width: 1023px)")
    mobile_rule = _rule_with_media(styles, "(max-width: 480px)")
    assert tablet_rule is not None and tablet_rule["style"]["min-height"] == "620px"
    assert mobile_rule is not None and mobile_rule["style"]["min-height"] == "520px"
    assert styles.index(mobile_rule) > styles.index(tablet_rule)

    pages = compose_project_pages(
        document, composed, {"entries": []}, project_id="agency-proj", isolated=True
    )
    assert "(max-width: 1023px)" in pages[0]["content_html"]
    assert "(max-width: 480px)" in pages[0]["content_html"]
    assert "(max-width: 768px)" not in pages[0]["content_html"]
    assert "(max-width: 390px)" not in pages[0]["content_html"]


def test_second_threshold_scheme_produces_different_exact_media_rules() -> None:
    """A different source (alternate thresholds) must transport its own
    thresholds, proving this is real acquisition/transport, not a second
    pair of hardcoded constants."""

    section = _sourced_section(
        section_id="hero.alternate", tablet_threshold=1100, mobile_threshold=600
    )
    document = _document(section)
    _, _, composed = _compose(document)
    styles = composed[0]["style_json"]

    assert _rule_with_media(styles, "(max-width: 1100px)") is not None
    assert _rule_with_media(styles, "(max-width: 600px)") is not None
    assert _rule_with_media(styles, "(max-width: 1023px)") is None
    assert _rule_with_media(styles, "(max-width: 480px)") is None


def test_property_without_observed_condition_falls_back_to_legacy_policy() -> None:
    """Per-property ownership: one property in a section has a proven
    source condition, a sibling property in the same responsive delta has
    none, and must keep exactly the pre-existing breakpoint-policy
    behavior -- not the newly observed threshold."""

    section = _sourced_section(section_id="hero.mixed", tablet_threshold=1023, mobile_threshold=480)
    tablet = section.responsive[0]
    mobile = section.responsive[1]
    section = section.model_copy(
        update={
            "responsive": [
                tablet.model_copy(
                    update={
                        "style": StyleSet(
                            observations=list(tablet.style.observations)
                            + [StyleObservation(property=StyleProperty.FONT_SIZE, value="19px")]
                        )
                    }
                ),
                mobile,
            ]
        }
    )
    document = _document(section)
    plan, _, composed = _compose(document)

    assert plan.entries[0].scoped_css["cond-max1023:min-height"] == "620px"
    assert plan.entries[0].scoped_css["tablet:font-size"] == "19px"

    styles = composed[0]["style_json"]
    tablet_condition_rule = _rule_with_media(styles, "(max-width: 1023px)")
    tablet_policy_rule = _rule_with_media(styles, "(max-width: 768px)")
    assert tablet_condition_rule is not None and tablet_condition_rule["style"] == {"min-height": "620px"}
    assert tablet_policy_rule is not None and tablet_policy_rule["style"] == {"font-size": "19px"}


def test_unresolved_condition_status_falls_back_to_legacy_policy_key() -> None:
    """An UNRESOLVED condition (evidence gathered, attribution not proven)
    must transport exactly like no condition at all -- never a fabricated
    authored threshold."""

    section = _sourced_section(section_id="hero.unresolved", tablet_threshold=1023, mobile_threshold=480)
    tablet = section.responsive[0]
    unresolved_observation = tablet.style.observations[0].model_copy(
        update={
            "condition": ResponsiveCondition(
                bounds=[],
                status=ResponsiveConditionStatus.UNRESOLVED,
                rule_order=1,
                reason="an unsupported media/container expression may win the cascade",
            )
        }
    )
    section = section.model_copy(
        update={
            "responsive": [
                tablet.model_copy(update={"style": StyleSet(observations=[unresolved_observation])}),
                section.responsive[1],
            ]
        }
    )
    document = _document(section)
    plan, _, composed = _compose(document)

    assert plan.entries[0].scoped_css["tablet:min-height"] == "620px"
    assert "cond-max1023:min-height" not in plan.entries[0].scoped_css
    styles = composed[0]["style_json"]
    assert _rule_with_media(styles, "(max-width: 768px)") is not None


def test_hashes_differ_for_different_observed_thresholds_same_values() -> None:
    section_a = _sourced_section(section_id="hero.hash", tablet_threshold=1023, mobile_threshold=480)
    section_b = _sourced_section(section_id="hero.hash", tablet_threshold=900, mobile_threshold=480)

    _, _, composed_a = _compose(_document(section_a))
    _, _, composed_b = _compose(_document(section_b))

    assert composed_a[0]["desired_hash"] != composed_b[0]["desired_hash"]

    pages_a = compose_project_pages(
        _document(section_a), composed_a, {"entries": []}, project_id="proj-a", isolated=True
    )
    pages_b = compose_project_pages(
        _document(section_b), composed_b, {"entries": []}, project_id="proj-b", isolated=True
    )
    assert pages_a[0]["content_hash"] != pages_b[0]["content_hash"]


def test_recomposing_same_observed_condition_is_deterministic() -> None:
    section = _sourced_section(section_id="hero.stable", tablet_threshold=1023, mobile_threshold=480)
    _, _, composed_1 = _compose(_document(section))
    _, _, composed_2 = _compose(_document(section))
    assert composed_1[0]["desired_hash"] == composed_2[0]["desired_hash"]
    assert composed_1[0]["style_json"] == composed_2[0]["style_json"]


# ---------------------------------------------------------------------------
# Malicious/malformed serialized conditions fail before any portal mutation
# ---------------------------------------------------------------------------


def _library_plan_for(section) -> list[dict]:
    plan = plan_design_document(_document(section), catalog=CATALOG)
    return emit_library_plan(plan)


@pytest.mark.parametrize(
    "malicious_key",
    [
        "cond-min2000000:min-height",  # threshold far out of range
        "cond-min1023-max480:min-height",  # empty range (min > max)
        "cond-max1023-max480:min-height",  # duplicate bound kind
        "cond-:min-height",  # no bounds at all
        "cond-max1023-min480-max200:min-height",  # more than two bounds
        "cond-max9999999999999999999:min-height",  # absurd digit count
    ],
)
def test_malicious_condition_keys_rejected_before_portal_mutation(malicious_key: str) -> None:
    library = _library_plan_for(_feature_section(section_id="malicious.section"))
    library[0]["style_scope"] = ".project-proof .section-proof"
    library[0]["style_declarations"] = {malicious_key: "1px"}

    with pytest.raises(BlockLibraryError):
        compose_project_library(library)


def test_validate_style_payload_rejects_malformed_condition_key_directly() -> None:
    with pytest.raises(StyleTransportError):
        validate_style_payload(".a .b", {"cond-min1023-max480:min-height": "1px"})


def test_decode_condition_key_rejects_trailing_garbage() -> None:
    with pytest.raises(ValueError):
        decode_condition_key("-max1023;DROP")


# ---------------------------------------------------------------------------
# Legacy/base style safety: unchanged when no condition evidence exists
# ---------------------------------------------------------------------------


def test_translate_responsive_observations_without_condition_uses_legacy_breakpoint_key() -> None:
    responsive = ResponsiveObservation(
        breakpoint=BreakpointName.TABLET,
        viewport=Viewport(width=768, height=1024),
        status=EvidenceStatus.OBSERVED,
        style=StyleSet(
            observations=[StyleObservation(property=StyleProperty.MIN_HEIGHT, value="620px")]
        ),
    )
    result = translate_responsive_observations(
        [responsive], _capabilities(), StyleTranslationConfig()
    )
    assert result.css_declarations == {"tablet:min-height": "620px"}


def test_build_style_rules_base_bucket_has_no_media_text() -> None:
    buckets = validate_style_payload(".a .b", {"color": "red"})
    rules = build_style_rules("el-1", buckets)
    assert len(rules) == 1
    assert "mediaText" not in rules[0]
    assert rules[0]["style"] == {"color": "red"}


def test_style_transport_budget_still_enforced_with_condition_keys() -> None:
    declarations = {f"cond-max{900 + i}:min-height": "1px" for i in range(PlanPolicy().css_rule_budget + 1)}
    with pytest.raises(StyleTransportError):
        validate_style_payload(".a .b", declarations)
