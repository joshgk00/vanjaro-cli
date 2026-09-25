"""Strict, deterministic Composition Plan v2 contract."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from vanjaro_cli.design.style_translation import StyleDecision


class _PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class BlockType(str, Enum):
    CUSTOM = "custom"
    GLOBAL = "global"


class SimplificationKind(str, Enum):
    OMIT = "omit"
    APPROXIMATE = "approximate"
    MODIFIER = "modifier"
    NEW_TEMPLATE = "new_template"
    MANUAL_MODULE = "manual_module"


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MatchAlternative(_PlanModel):
    template_id: str = Field(min_length=1)
    template_name: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    confidence: Literal["high", "medium", "low"]


class PlanMatch(_PlanModel):
    score: float = Field(ge=0, le=1)
    confidence: Literal["high", "medium", "low"]
    blocking: bool = False
    reasons: tuple[str, ...] = ()
    alternatives: tuple[MatchAlternative, ...] = ()


class OverrideAudit(_PlanModel):
    author: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    previous_candidates: tuple[MatchAlternative, ...] = Field(min_length=1)


class PlanBlock(_PlanModel):
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    type: BlockType = BlockType.CUSTOM


class SemanticBinding(_PlanModel):
    """One declared semantic field bound to one actual override slot."""

    semantic_field: str = Field(min_length=1)
    slot: str = Field(pattern=r"^[a-z][a-z0-9_-]*(?:_\d+)?(?:_[a-z]+)?$")
    source_element_ids: tuple[str, ...] = Field(min_length=1)
    value: str
    item_id: str | None = None
    editable: bool = True


class ElementStyleAction(_PlanModel):
    """One content element's own captured style, translated onto the exact
    physical slot its semantic binding owns -- never onto the section that
    contains it, and never onto a sibling slot.

    ``slot`` reuses the same override-slot vocabulary as ``SemanticBinding.slot``
    (see ``utils/block_compose.enumerate_slots``): the physical owner is
    resolved by that same slot key at composition time, through
    ``apply_overrides_with_owners``, not by any independent text/position
    search.
    """

    source_element_id: str = Field(min_length=1)
    slot: str = Field(pattern=r"^[a-z][a-z0-9_-]*(?:_\d+)?(?:_[a-z]+)?$")
    item_id: str | None = None
    style_decisions: tuple[StyleDecision, ...] = ()
    css_scope: str | None = Field(default=None, pattern=r"^\.[a-z][a-z0-9-]*(?: \.[a-z][a-z0-9-]*)+$")
    scoped_css: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action(self) -> "ElementStyleAction":
        if self.scoped_css and not self.css_scope:
            raise ValueError("scoped_css requires an explicit client-safe css_scope")
        return self


class SimplificationDecision(_PlanModel):
    trait: str = Field(min_length=1)
    classification: SimplificationKind
    severity: IssueSeverity
    reason: str = Field(min_length=1)
    source_ids: tuple[str, ...] = ()

    @property
    def blocks_approval(self) -> bool:
        return self.severity == IssueSeverity.HIGH and self.classification in {
            SimplificationKind.OMIT,
            SimplificationKind.NEW_TEMPLATE,
            SimplificationKind.MANUAL_MODULE,
        }


class CompositionPlanEntry(_PlanModel):
    id: str = Field(min_length=1)
    source_section_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    template: str = Field(min_length=1)
    match: PlanMatch
    override_audit: OverrideAudit | None = None
    block: PlanBlock
    bindings: tuple[SemanticBinding, ...] = ()
    clear_slots: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    style_decisions: tuple[StyleDecision, ...] = ()
    css_scope: str | None = Field(default=None, pattern=r"^\.[a-z][a-z0-9-]*(?: \.[a-z][a-z0-9-]*)+$")
    scoped_css: dict[str, str] = Field(default_factory=dict)
    # Owner-aware element styles, additive to schema 2.0: a plan serialized
    # before this field existed simply has none (the default below), so it
    # still validates and loads unchanged.
    element_styles: tuple[ElementStyleAction, ...] = ()
    simplifications: tuple[SimplificationDecision, ...] = ()
    warnings: tuple[str, ...] = ()
    # Fields of a form the source page had. A form is never rebuilt from a
    # template, so these do not bind to slots — they travel to the build so it
    # can mark where the form was and list what to configure.
    form_fields: tuple[dict[str, JsonValue], ...] = ()

    @model_validator(mode="after")
    def validate_entry(self) -> "CompositionPlanEntry":
        slots = [binding.slot.casefold() for binding in self.bindings]
        if len(slots) != len(set(slots)):
            raise ValueError("binding slots must be unique within an entry")
        cleared = [slot.casefold() for slot in self.clear_slots]
        if len(cleared) != len(set(cleared)):
            raise ValueError("clear_slots must be unique within an entry")
        if set(slots) & set(cleared):
            raise ValueError("a slot cannot be both bound and cleared")
        element_slots = [action.slot.casefold() for action in self.element_styles]
        if len(element_slots) != len(set(element_slots)):
            raise ValueError("element_styles slots must be unique within an entry")
        if self.scoped_css and not self.css_scope:
            raise ValueError("scoped_css requires an explicit client-safe css_scope")
        should_block = any(
            item.blocks_approval and not self._handled_by_placeholder(item)
            for item in self.simplifications
        )
        if should_block and not self.match.blocking:
            raise ValueError("high-severity unresolved simplifications must block the match")
        return self

    def _handled_by_placeholder(self, decision: "SimplificationDecision") -> bool:
        """Report whether a simplification already has its intended handling.

        A form is never rebuilt from a template, so no template can represent
        one and the simplification is not a shortfall to resolve — it is the
        expected outcome. It stops blocking once the fields that make up its
        placeholder have actually been inventoried; a form nobody listed still
        blocks, because then there is nothing to put in the page's place.
        """

        return decision.trait == "interaction:form" and bool(self.form_fields)


class PlanPolicy(_PlanModel):
    minimum_confidence: float = Field(default=0.65, ge=0, le=1)
    allow_simplification: bool = False
    css_rule_budget: int = Field(default=12, ge=0)


class PlanSummary(_PlanModel):
    section_count: int = Field(ge=0)
    blocking_count: int = Field(ge=0)
    native_component_ratio: float = Field(ge=0, le=1)
    editable_content_coverage: float = Field(ge=0, le=1)
    scoped_css_rule_count: int = Field(default=0, ge=0)
    scoped_css_bytes: int = Field(default=0, ge=0)


class CompositionPlan(_PlanModel):
    schema_version: Literal["2.0"] = "2.0"
    source_document_id: str = Field(min_length=1)
    policy: PlanPolicy = Field(default_factory=PlanPolicy)
    entries: tuple[CompositionPlanEntry, ...]
    summary: PlanSummary

    @model_validator(mode="after")
    def validate_plan(self) -> "CompositionPlan":
        for label, values in (
            ("entry ids", [entry.id.casefold() for entry in self.entries]),
            ("source sections", [entry.source_section_id.casefold() for entry in self.entries]),
            ("block names", [entry.block.name.casefold() for entry in self.entries]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        if self.summary.section_count != len(self.entries):
            raise ValueError("summary.section_count must equal the number of entries")
        blocking_count = sum(entry.match.blocking for entry in self.entries)
        if self.summary.blocking_count != blocking_count:
            raise ValueError("summary.blocking_count does not match entries")
        return self


def serialize_composition_plan(plan: CompositionPlan, *, indent: int = 2) -> str:
    """Serialize with stable ordering and a trailing newline."""

    payload = plan.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False) + "\n"


def deserialize_composition_plan(value: str | bytes) -> CompositionPlan:
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid Composition Plan JSON: {exc}") from exc
    return CompositionPlan.model_validate(payload)


def write_composition_plan(path: str | Path, plan: CompositionPlan) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_composition_plan(plan), encoding="utf-8")
    return target


def render_composition_plan_schema() -> str:
    return json.dumps(CompositionPlan.model_json_schema(), indent=2, sort_keys=True) + "\n"
