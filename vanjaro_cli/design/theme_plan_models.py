"""Strict artifact contracts for read-only project theme planning."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


THEME_PLAN_SCHEMA_VERSION = "1.0"
_PALETTE_SLOTS = {
    "primary", "secondary", "tertiary", "quaternary", "success", "info",
    "warning", "danger", "light", "dark",
}


class _ThemePlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ThemePlanWarning(_ThemePlanModel):
    """An explicit design token or portal capability that needs review."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    token_paths: list[str] = Field(default_factory=list)


class ThemeControlPlan(_ThemePlanModel):
    """One exact existing Vanjaro control and its proposed value."""

    guid: str = Field(min_length=1)
    less_variable: str = Field(min_length=1)
    category: str
    title: str
    current_value: str
    planned_value: str
    changed: bool
    source_token_paths: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class ThemeFontDecision(_ThemePlanModel):
    """Traceable disposition for one observed font family and semantic role."""

    role: str = Field(min_length=1)
    observed_family: str = Field(min_length=1)
    occurrences: int = Field(ge=1)
    status: Literal["mapped", "unresolved", "not_selected"]
    available_value: str | None = None
    source_token_paths: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def require_available_value_for_mapping(self) -> "ThemeFontDecision":
        if self.status in {"mapped", "not_selected"} and not self.available_value:
            raise ValueError("available font decisions require available_value")
        if self.status == "unresolved" and self.available_value is not None:
            raise ValueError("unresolved font decisions must not invent available_value")
        return self


class ProjectThemePlan(_ThemePlanModel):
    """Strict, reviewable and non-mutating theme plan artifact."""

    schema_version: Literal["1.0"] = THEME_PLAN_SCHEMA_VERSION
    mode: Literal["plan"] = "plan"
    theme_name: str = Field(min_length=1)
    mutated: Literal[False] = False
    current_palette: dict[str, str]
    proposed_palette: dict[str, str]
    controls: list[ThemeControlPlan]
    fonts: list[ThemeFontDecision]
    warnings: list[ThemePlanWarning]

    @model_validator(mode="after")
    def validate_deterministic_contract(self) -> "ProjectThemePlan":
        unknown_slots = (
            set(self.current_palette) | set(self.proposed_palette)
        ) - _PALETTE_SLOTS
        if unknown_slots:
            raise ValueError(f"unknown palette slots: {sorted(unknown_slots)}")
        identities = [
            (item.less_variable.casefold(), item.guid.casefold())
            for item in self.controls
        ]
        if identities != sorted(identities):
            raise ValueError("controls must be sorted by less_variable and guid")
        if len(identities) != len(set(identities)):
            raise ValueError("theme plan contains duplicate controls")
        return self


__all__ = [
    "ProjectThemePlan",
    "THEME_PLAN_SCHEMA_VERSION",
    "ThemeControlPlan",
    "ThemeFontDecision",
    "ThemePlanWarning",
]
