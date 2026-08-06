"""Deterministic, source-neutral template matching for Design Document sections."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Iterable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.models import (
    Alignment,
    BreakpointName,
    ContentElement,
    DesignDocument,
    InteractionKind,
    LayoutKind,
    MediaPosition,
    Section,
    StyleProperty,
)
from vanjaro_cli.design.semantics import (
    item_capability_aliases,
    normalize_semantic_name,
    section_capability_aliases,
)
from vanjaro_cli.design.template_catalog import CapabilityManifest, TemplateCatalogEntry

__all__ = [
    "CandidateSnapshot",
    "ConfidenceLevel",
    "ConfidencePolicy",
    "DEFAULT_CONFIDENCE_POLICY",
    "DEFAULT_SCORING_WEIGHTS",
    "MaintainabilitySignals",
    "MatchContext",
    "MatchOverrideAudit",
    "MatchSubscores",
    "ScoringWeights",
    "TemplateMatchCandidate",
    "TemplateMatchResult",
    "apply_match_override",
    "match_design_document",
    "match_section",
    "score_template",
]


class _MatcherModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ScoringWeights(_MatcherModel):
    """The one typed location for all candidate-score weights."""

    semantic_role: float = Field(default=0.25, ge=0, le=1)
    fields: float = Field(default=0.20, ge=0, le=1)
    repeat_group: float = Field(default=0.15, ge=0, le=1)
    layout: float = Field(default=0.15, ge=0, le=1)
    responsive: float = Field(default=0.10, ge=0, le=1)
    style: float = Field(default=0.05, ge=0, le=1)
    interaction: float = Field(default=0.05, ge=0, le=1)
    maintainability: float = Field(default=0.05, ge=0, le=1)

    @model_validator(mode="after")
    def require_unit_total(self) -> "ScoringWeights":
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("template scoring weights must sum to 1.0")
        return self


class ConfidencePolicy(_MatcherModel):
    high_threshold: float = Field(default=0.85, ge=0, le=1)
    medium_threshold: float = Field(default=0.65, ge=0, le=1)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "ConfidencePolicy":
        if self.medium_threshold >= self.high_threshold:
            raise ValueError("medium_threshold must be lower than high_threshold")
        return self

    def classify(self, score: float) -> ConfidenceLevel:
        if score >= self.high_threshold:
            return ConfidenceLevel.HIGH
        if score >= self.medium_threshold:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW


DEFAULT_SCORING_WEIGHTS = ScoringWeights()
DEFAULT_CONFIDENCE_POLICY = ConfidencePolicy()


class MatchContext(_MatcherModel):
    """Optional planning evidence used by style and maintainability scoring."""

    required_modifiers: tuple[str, ...] = ()
    generated_css_bytes_by_template: dict[str, int] = Field(default_factory=dict)
    generated_css_selectors_by_template: dict[str, int] = Field(default_factory=dict)
    global_block_template_ids: frozenset[str] = frozenset()
    template_reuse_counts: dict[str, int] = Field(default_factory=dict)
    custom_code_template_ids: frozenset[str] = frozenset()
    css_byte_budget: int = Field(default=2000, gt=0)
    css_selector_budget: int = Field(default=10, gt=0)
    estimated_bytes_per_modifier: int = Field(default=160, ge=0)


class MatchSubscores(_MatcherModel):
    semantic_role: float = Field(ge=0, le=1)
    fields: float = Field(ge=0, le=1)
    repeat_group: float = Field(ge=0, le=1)
    layout: float = Field(ge=0, le=1)
    responsive: float = Field(ge=0, le=1)
    style: float = Field(ge=0, le=1)
    interaction: float = Field(ge=0, le=1)
    maintainability: float = Field(ge=0, le=1)


class MaintainabilitySignals(_MatcherModel):
    native_component_ratio: float = Field(ge=0, le=1)
    editable_content_coverage: float = Field(ge=0, le=1)
    required_modifier_count: int = Field(ge=0)
    estimated_css_bytes: int = Field(ge=0)
    estimated_css_selectors: int = Field(ge=0)
    uses_custom_code: bool
    global_block_reuse: bool
    template_reuse_count: int = Field(ge=0)


class TemplateMatchCandidate(_MatcherModel):
    template_id: str
    template_name: str
    score: float = Field(ge=0, le=1)
    confidence: ConfidenceLevel
    confidence_cap_reasons: tuple[str, ...] = ()
    subscores: MatchSubscores
    missing_requirements: tuple[str, ...] = ()
    required_modifiers: tuple[str, ...] = ()
    reasons: tuple[str, ...]
    maintainability: MaintainabilitySignals
    auto_selectable: bool = True


class CandidateSnapshot(_MatcherModel):
    template_id: str
    template_name: str
    score: float = Field(ge=0, le=1)
    confidence: ConfidenceLevel


class MatchOverrideAudit(_MatcherModel):
    section_id: str
    selected_template_id: str
    author: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    created_at: AwareDatetime
    prior_candidates: tuple[CandidateSnapshot, ...]


class TemplateMatchResult(_MatcherModel):
    section_id: str
    candidates: tuple[TemplateMatchCandidate, ...]
    selected_candidate: TemplateMatchCandidate
    blocking: bool
    override: MatchOverrideAudit | None = None


_ROLE_COMPATIBILITY: dict[str, dict[str, float]] = {
    "hero": {
        "hero": 1.0,
        "hero_centered": 0.98,
        "hero_split": 0.98,
        "hero_media": 0.78,
        "photo_band": 0.72,
        "split_media": 0.72,
        "image_text": 0.68,
    },
    "logo_cloud": {"logo_bar": 1.0, "partner_logos": 1.0, "client_logos": 1.0},
    "feature_cards": {
        "feature_cards": 1.0,
        "service_cards": 0.80,
        "feature_list": 0.82,
        "service_list": 0.78,
        "gallery": 0.68,
    },
    "testimonials": {"testimonials": 1.0, "quote_cards": 0.98},
    "testimonial_feature": {
        "split_media": 0.92,
        "image_text": 0.90,
        "bio": 0.88,
        "profile": 0.86,
        "about": 0.80,
        "testimonials": 0.72,
    },
    "call_to_action": {
        "cta": 1.0,
        "cta_banner": 0.98,
        "cta_split": 0.94,
        "contact_cta": 0.80,
        "contact": 0.72,
    },
    "stats": {"stats": 1.0, "metrics_band": 0.98, "metrics_grid": 0.95},
    "navigation": {"navigation": 1.0, "footer_navigation": 0.62, "footer": 0.55},
    "split_feature": {"split_media": 1.0, "image_text": 0.98, "about": 0.76},
    "project_gallery": {
        "gallery": 1.0,
        "portfolio_grid": 1.0,
        "feature_cards": 0.70,
    },
    "process_steps": {
        "stats": 0.92,
        "metrics_band": 0.90,
        "feature_list": 0.88,
        "service_list": 0.84,
    },
    "contact": {"contact": 1.0, "contact_cta": 0.98, "cta": 0.82, "cta_banner": 0.80},
    "about": {"about": 1.0, "bio": 0.95, "split_media": 0.88, "image_text": 0.86},
    "bio": {"bio": 1.0, "profile": 0.98, "about": 0.94},
    "gallery": {"gallery": 1.0, "portfolio_grid": 0.98},
    "faq": {"faq": 1.0, "question_answer": 0.98},
    "pricing": {"pricing_cards": 1.0, "membership_plans": 0.98},
    "team": {"team_grid": 1.0, "people_cards": 0.98},
}

_STYLE_MODIFIERS: dict[StyleProperty, str] = {
    StyleProperty.BACKGROUND_COLOR: "band-color",
    StyleProperty.BACKGROUND_IMAGE: "background-image",
    StyleProperty.BACKGROUND_POSITION: "image-focal-point",
    StyleProperty.OVERLAY_COLOR: "background-overlay",
    StyleProperty.BORDER_RADIUS: "card-radius",
    StyleProperty.BOX_SHADOW: "card-shadow",
    StyleProperty.COLUMN_GAP: "column-gap",
    StyleProperty.ROW_GAP: "column-gap",
    StyleProperty.TEXT_ALIGN: "text-alignment",
    StyleProperty.OBJECT_POSITION: "image-focal-point",
}


_normalize = normalize_semantic_name


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


def _semantic_score(section: Section, capabilities: CapabilityManifest) -> float:
    capability_roles = {_normalize(role) for role in capabilities.roles}

    def compatibility(role: str) -> float:
        normalized = _normalize(role)
        if normalized in capability_roles:
            return 1.0
        aliases = _ROLE_COMPATIBILITY.get(normalized, {})
        return max((aliases.get(candidate, 0.0) for candidate in capability_roles), default=0.0)

    scores = [compatibility(section.semantic_role)]
    scores.extend(compatibility(role.role) * role.score * 0.95 for role in section.candidate_roles)
    return _bounded(max(scores, default=0.0))


def _observed_fields(section: Section) -> tuple[tuple[str, tuple[str, ...]], ...]:
    observations: dict[tuple[str, ...], str] = {}
    grouped_ids = {element.id for element in section.content if element.group_id is not None}

    for group in section.groups:
        for item in group.items:
            for field_name in item.fields:
                alternatives = item_capability_aliases(field_name)
                observations.setdefault(alternatives, f"item.{_normalize(field_name)}")

    for element in section.content:
        if element.id in grouped_ids:
            alternatives = item_capability_aliases(element.role)
            label = f"item.{_normalize(element.role)}"
        else:
            alternatives = section_capability_aliases(element.role)
            label = _normalize(element.role)
        observations.setdefault(alternatives, label)

    return tuple(sorted(((label, aliases) for aliases, label in observations.items()), key=lambda item: item[0]))


def _field_score(
    section: Section,
    capabilities: CapabilityManifest,
) -> tuple[float, float, tuple[str, ...]]:
    observed = _observed_fields(section)
    editable = set(capabilities.fields)
    represented = editable.union(capabilities.static_fields)
    represented_matches = [
        label for label, alternatives in observed if represented.intersection(alternatives)
    ]
    editable_matches = [
        label for label, alternatives in observed if editable.intersection(alternatives)
    ]
    represented_coverage = len(represented_matches) / len(observed) if observed else 1.0
    editable_coverage = len(editable_matches) / len(observed) if observed else 1.0

    available_aliases = {alias for _, alternatives in observed for alias in alternatives}
    missing_template_fields = sorted(
        name
        for name, requirement in capabilities.fields.items()
        if requirement == "required" and name not in available_aliases
    )
    unsupported_source = sorted(
        label
        for label, alternatives in observed
        if not represented.intersection(alternatives)
    )
    # Represented by a *static* slot only. These are the quietest content losses
    # in the pipeline: the field looks supported, so it is never reported
    # unsupported, and then binding skips it because only editable fields bind.
    # Three designed images left the pilot build this way with no warning at all,
    # and the media dimension could not see it either (VF-214).
    static_only_source = sorted(
        label
        for label, alternatives in observed
        if represented.intersection(alternatives)
        and not editable.intersection(alternatives)
    )
    required_fill = (
        1.0
        if not [name for name, value in capabilities.fields.items() if value == "required"]
        else 1.0
        - len(missing_template_fields)
        / len([name for name, value in capabilities.fields.items() if value == "required"])
    )
    score = _bounded(represented_coverage * 0.7 + max(0.0, required_fill) * 0.3)
    missing = tuple(
        [f"required template field '{name}' has no source content" for name in missing_template_fields]
        + [f"source field '{name}' is not editable by template" for name in unsupported_source]
        + [
            f"source field '{name}' maps only to a static template slot, "
            "so its content cannot reach the build"
            for name in static_only_source
        ]
    )
    return score, _bounded(editable_coverage), missing


def _repeat_kind_score(source_kind: str, target_kind: str) -> float:
    source = _normalize(source_kind)
    target = _normalize(target_kind)
    if source == target:
        return 1.0
    aliases = {
        "blog_post": {"article": 1.0, "card": 0.8},
        "team_member": {"person": 1.0, "card": 0.75},
        "navigation_item": {"navigation_column": 0.7},
        "other": {"card": 0.55, "logo": 0.55, "feature": 0.55, "marquee_item": 0.5},
    }
    return aliases.get(source, {}).get(target, 0.25)


def _repeat_score(section: Section, capabilities: CapabilityManifest) -> float:
    target = capabilities.repeat_group
    if not section.groups and target is None:
        return 1.0
    if not section.groups:
        return 0.35
    if target is None:
        return 0.1

    best = 0.0
    for group in section.groups:
        kind_score = _repeat_kind_score(group.kind.value, target.kind)
        count = len(group.items)
        within_max = target.maximum is None or count <= target.maximum
        if target.minimum <= count and within_max:
            if count == target.default:
                count_score = 1.0
            else:
                count_score = 0.9 if target.expandable else 0.7
        elif target.expandable:
            count_score = 0.65
        else:
            distance = abs(count - target.default)
            count_score = max(0.0, 1.0 - distance / max(count, target.default, 1))
        best = max(best, kind_score * 0.6 + count_score * 0.4)
    return _bounded(best)


def _layout_kind_score(source: LayoutKind, target: str) -> float:
    target = _normalize(target)
    compatible = {
        LayoutKind.GRID: {"grid": 1.0, "list": 0.72, "band": 0.68},
        LayoutKind.SPLIT: {"split": 1.0, "grid": 0.65},
        LayoutKind.STACK: {"single": 1.0, "band": 0.90, "list": 0.78, "accordion": 0.72},
        LayoutKind.FLEX: {"split": 0.9, "grid": 0.85, "band": 0.82, "navigation": 0.72},
        LayoutKind.CAROUSEL: {"grid": 0.62, "single": 0.55},
        LayoutKind.FREEFORM: {"single": 0.58, "split": 0.55, "grid": 0.5},
        LayoutKind.OTHER: {target: 0.55},
    }
    return compatible.get(source, {}).get(target, 0.25)


def _layout_score(section: Section, capabilities: CapabilityManifest) -> float:
    parts: list[tuple[float, float]] = [(_layout_kind_score(section.layout.kind, capabilities.layout.kind), 0.5)]
    if section.layout.columns is not None:
        distance = min(abs(section.layout.columns - column) for column in capabilities.layout.columns)
        parts.append((max(0.0, 1.0 - distance / max(section.layout.columns, 1)), 0.25))
    if section.layout.media_position is not None:
        media_score = 1.0 if section.layout.media_position.value in capabilities.layout.media_positions else 0.25
        parts.append((media_score, 0.15))
    if section.layout.alignment is not None:
        source_alignment = {
            Alignment.START: "left",
            Alignment.END: "right",
        }.get(section.layout.alignment, section.layout.alignment.value)
        alignment_score = 1.0 if source_alignment in capabilities.layout.alignment else 0.4
        parts.append((alignment_score, 0.10))
    total_weight = sum(weight for _, weight in parts)
    return _bounded(sum(value * weight for value, weight in parts) / total_weight)


def _responsive_score(section: Section, capabilities: CapabilityManifest) -> float:
    if not section.responsive:
        return 0.8
    column_by_breakpoint = {
        BreakpointName.DESKTOP: capabilities.responsive.desktop_columns,
        BreakpointName.TABLET: capabilities.responsive.tablet_columns,
        BreakpointName.MOBILE: capabilities.responsive.mobile_columns,
    }
    comparisons: list[float] = []
    for observation in section.responsive:
        changes = observation.layout_changes
        if isinstance(changes.get("columns"), (int, float)):
            expected = int(changes["columns"])
            actual = column_by_breakpoint[observation.breakpoint]
            comparisons.append(max(0.0, 1.0 - abs(expected - actual) / max(expected, actual, 1)))
        media_position = changes.get("media_position")
        if isinstance(media_position, str):
            comparisons.append(1.0 if media_position in capabilities.layout.media_positions else 0.3)
        direction = changes.get("direction")
        if direction == "vertical":
            actual = column_by_breakpoint[observation.breakpoint]
            comparisons.append(1.0 if actual == 1 else 0.4)
        if "alignment" in changes and isinstance(changes["alignment"], str):
            comparisons.append(1.0 if changes["alignment"] in capabilities.layout.alignment else 0.5)
    return _bounded(sum(comparisons) / len(comparisons)) if comparisons else 0.8


def _required_modifiers(section: Section, context: MatchContext) -> tuple[str, ...]:
    modifiers = set(context.required_modifiers)
    for observation in section.style.observations:
        modifier = _STYLE_MODIFIERS.get(observation.property)
        if modifier:
            modifiers.add(modifier)
    return tuple(sorted(modifiers))


def _style_score(required: tuple[str, ...], capabilities: CapabilityManifest) -> tuple[float, tuple[str, ...]]:
    supported = set(capabilities.supported_modifiers)
    missing = tuple(modifier for modifier in required if modifier not in supported)
    if not required:
        return 1.0, missing
    return _bounded((len(required) - len(missing)) / len(required)), missing


def _interaction_score(
    section: Section,
    capabilities: CapabilityManifest,
) -> tuple[float, tuple[str, ...]]:
    aliases = {InteractionKind.VIDEO_EMBED: "video"}
    required = {_normalize(aliases.get(item.kind, item.kind.value)) for item in section.interactions}
    supported = {_normalize(item) for item in capabilities.interactions}
    missing = tuple(sorted(required - supported))
    if not required:
        return 1.0, missing
    return _bounded((len(required) - len(missing)) / len(required)), missing


def _maintainability_score(
    entry: TemplateCatalogEntry,
    editable_coverage: float,
    missing_modifiers: tuple[str, ...],
    context: MatchContext,
) -> tuple[float, MaintainabilitySignals]:
    template_id = entry.template_id
    uses_custom_code = (
        template_id in context.custom_code_template_ids
        or entry.capabilities.native_component_ratio <= 0.05
        or "custom_code" in entry.capabilities.roles
    )
    css_bytes = context.generated_css_bytes_by_template.get(
        template_id, len(missing_modifiers) * context.estimated_bytes_per_modifier
    )
    css_selectors = context.generated_css_selectors_by_template.get(template_id, len(missing_modifiers))
    global_reuse = template_id in context.global_block_template_ids
    reuse_count = context.template_reuse_counts.get(template_id, 0)
    css_byte_score = max(0.0, 1.0 - css_bytes / context.css_byte_budget)
    selector_score = max(0.0, 1.0 - css_selectors / context.css_selector_budget)
    score = (
        entry.capabilities.native_component_ratio * 0.35
        + editable_coverage * 0.25
        + css_byte_score * 0.10
        + selector_score * 0.10
        + (0.0 if uses_custom_code else 1.0) * 0.10
        + (1.0 if global_reuse else 0.0) * 0.05
        + min(reuse_count / 3, 1.0) * 0.05
    )
    signals = MaintainabilitySignals(
        native_component_ratio=entry.capabilities.native_component_ratio,
        editable_content_coverage=editable_coverage,
        required_modifier_count=len(missing_modifiers),
        estimated_css_bytes=css_bytes,
        estimated_css_selectors=css_selectors,
        uses_custom_code=uses_custom_code,
        global_block_reuse=global_reuse,
        template_reuse_count=reuse_count,
    )
    return _bounded(score), signals


def _weighted_score(subscores: MatchSubscores, weights: ScoringWeights) -> float:
    return _bounded(
        sum(
            getattr(subscores, field_name) * weight
            for field_name, weight in weights.model_dump().items()
        )
    )


def score_template(
    section: Section,
    entry: TemplateCatalogEntry,
    *,
    weights: ScoringWeights = DEFAULT_SCORING_WEIGHTS,
    confidence_policy: ConfidencePolicy = DEFAULT_CONFIDENCE_POLICY,
    context: MatchContext | None = None,
) -> TemplateMatchCandidate:
    """Score one section/template pair with explanations for every dimension."""

    context = context or MatchContext()
    semantic = _semantic_score(section, entry.capabilities)
    fields, editable_coverage, field_mismatches = _field_score(section, entry.capabilities)
    repeat_group = _repeat_score(section, entry.capabilities)
    layout = _layout_score(section, entry.capabilities)
    responsive = _responsive_score(section, entry.capabilities)
    required_modifiers = _required_modifiers(section, context)
    style, missing_modifiers = _style_score(required_modifiers, entry.capabilities)
    interaction, missing_interactions = _interaction_score(section, entry.capabilities)
    maintainability, maintainability_signals = _maintainability_score(
        entry, editable_coverage, missing_modifiers, context
    )
    subscores = MatchSubscores(
        semantic_role=semantic,
        fields=fields,
        repeat_group=repeat_group,
        layout=layout,
        responsive=responsive,
        style=style,
        interaction=interaction,
        maintainability=maintainability,
    )
    score = _weighted_score(subscores, weights)
    confidence = confidence_policy.classify(score)
    cap_reasons: list[str] = []
    if field_mismatches:
        cap_reasons.append("required field coverage is incomplete")
        if confidence == ConfidenceLevel.HIGH:
            confidence = ConfidenceLevel.MEDIUM
    if missing_interactions:
        cap_reasons.append("a required interaction is unsupported")
        if confidence == ConfidenceLevel.HIGH:
            confidence = ConfidenceLevel.MEDIUM
    missing_requirements = tuple(
        list(field_mismatches)
        + [f"required interaction '{interaction_name}' is unsupported" for interaction_name in missing_interactions]
    )
    reasons = (
        f"semantic role compatibility {semantic:.3f}",
        f"content field compatibility {fields:.3f}",
        f"repeat-group compatibility {repeat_group:.3f}",
        f"layout compatibility {layout:.3f}",
        f"responsive compatibility {responsive:.3f}",
        f"style/modifier compatibility {style:.3f}",
        f"interaction compatibility {interaction:.3f}",
        f"maintainability {maintainability:.3f}",
    )
    return TemplateMatchCandidate(
        template_id=entry.template_id,
        template_name=entry.name,
        score=score,
        confidence=confidence,
        confidence_cap_reasons=tuple(cap_reasons),
        subscores=subscores,
        missing_requirements=missing_requirements,
        required_modifiers=missing_modifiers,
        reasons=reasons,
        maintainability=maintainability_signals,
    )


def match_section(
    section: Section,
    catalog: Iterable[TemplateCatalogEntry],
    *,
    weights: ScoringWeights = DEFAULT_SCORING_WEIGHTS,
    confidence_policy: ConfidencePolicy = DEFAULT_CONFIDENCE_POLICY,
    context: MatchContext | None = None,
    top_k: int = 3,
) -> TemplateMatchResult:
    """Score the full catalog and return deterministic top candidates."""

    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    scored = [
        score_template(
            section,
            entry,
            weights=weights,
            confidence_policy=confidence_policy,
            context=context,
        )
        for entry in catalog
    ]
    if not scored:
        raise ValueError("template catalog must not be empty")
    scored.sort(key=lambda candidate: (-candidate.score, candidate.template_id.casefold(), candidate.template_id))

    native_medium_exists = any(
        not candidate.maintainability.uses_custom_code
        and candidate.score >= confidence_policy.medium_threshold
        for candidate in scored
    )
    if native_medium_exists:
        scored = [
            candidate.model_copy(
                update={
                    "auto_selectable": False,
                    "reasons": candidate.reasons
                    + ("automatic selection suppressed because a medium-or-better native template exists",),
                }
            )
            if candidate.maintainability.uses_custom_code
            else candidate
            for candidate in scored
        ]

    selected = next((candidate for candidate in scored if candidate.auto_selectable), scored[0])
    return TemplateMatchResult(
        section_id=section.id,
        candidates=tuple(scored[:top_k]),
        selected_candidate=selected,
        blocking=selected.confidence == ConfidenceLevel.LOW,
    )


def match_design_document(
    document: DesignDocument,
    catalog: Iterable[TemplateCatalogEntry],
    *,
    weights: ScoringWeights = DEFAULT_SCORING_WEIGHTS,
    confidence_policy: ConfidencePolicy = DEFAULT_CONFIDENCE_POLICY,
    context: MatchContext | None = None,
    top_k: int = 3,
) -> tuple[TemplateMatchResult, ...]:
    """Match every section in stable page/section order."""

    stable_catalog = tuple(catalog)
    results: list[TemplateMatchResult] = []
    for page in document.pages:
        for section in sorted(page.sections, key=lambda item: (item.order, item.id)):
            results.append(
                match_section(
                    section,
                    stable_catalog,
                    weights=weights,
                    confidence_policy=confidence_policy,
                    context=context,
                    top_k=top_k,
                )
            )
    return tuple(results)


def apply_match_override(
    result: TemplateMatchResult,
    selected_candidate: TemplateMatchCandidate,
    *,
    author: str,
    reason: str,
    created_at: datetime | None = None,
) -> TemplateMatchResult:
    """Select any explicitly scored candidate and retain the previous top candidates."""

    author = author.strip()
    reason = reason.strip()
    if not author:
        raise ValueError("override author is required")
    if not reason:
        raise ValueError("override reason is required")
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("override created_at must be timezone-aware")
    audit = MatchOverrideAudit(
        section_id=result.section_id,
        selected_template_id=selected_candidate.template_id,
        author=author,
        reason=reason,
        created_at=timestamp,
        prior_candidates=tuple(
            CandidateSnapshot(
                template_id=candidate.template_id,
                template_name=candidate.template_name,
                score=candidate.score,
                confidence=candidate.confidence,
            )
            for candidate in result.candidates
        ),
    )
    return result.model_copy(
        update={
            "selected_candidate": selected_candidate,
            "blocking": False,
            "override": audit,
        }
    )
