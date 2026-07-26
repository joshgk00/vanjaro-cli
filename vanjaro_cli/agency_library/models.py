"""Strict contracts for independently versioned agency library packs."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vanjaro_cli.utils.semver import validate_semver


_TEMPLATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_MODIFIER_ID = re.compile(r"^[a-z][a-z0-9_-]*$")


class _PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PackPayloadReference(_PackModel):
    version: str
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return validate_semver(value)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or re.match(r"^[A-Za-z]:/", normalized)
            or any(character in normalized for character in (":", "?", "#"))
            or ".." in path.parts
            or not path.suffix
        ):
            raise ValueError("pack payload path must be a relative file without traversal")
        return path.as_posix()


class TemplateContract(_PackModel):
    template_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    template_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("template_id")
    @classmethod
    def reject_traversal(cls, value: str) -> str:
        if ".." in PurePosixPath(value).parts or "//" in value or value.endswith("/"):
            raise ValueError("template_id must not contain traversal or empty segments")
        return value


class TemplateLibraryPayload(_PackModel):
    schema_version: Literal["1.0"] = "1.0"
    version: str
    capability_schema_version: str = Field(min_length=1)
    templates: tuple[TemplateContract, ...] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return validate_semver(value)

    @model_validator(mode="after")
    def unique_templates(self) -> "TemplateLibraryPayload":
        identifiers = [item.template_id.casefold() for item in self.templates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("template library template_id values must be unique")
        return self


class ModifierContract(_PackModel):
    modifier_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ModifierLibraryPayload(_PackModel):
    schema_version: Literal["1.0"] = "1.0"
    version: str
    modifiers: tuple[ModifierContract, ...]

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return validate_semver(value)

    @model_validator(mode="after")
    def unique_modifiers(self) -> "ModifierLibraryPayload":
        identifiers = [item.modifier_id.casefold() for item in self.modifiers]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("modifier library modifier_id values must be unique")
        return self


class PackUpgradeRule(_PackModel):
    from_version: str
    compatible_capability_schema_change: bool = False
    compatible_template_changes: tuple[str, ...] = ()
    compatible_modifier_changes: tuple[str, ...] = ()
    template_replacements: dict[str, str] = Field(default_factory=dict)
    modifier_replacements: dict[str, str] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @field_validator("from_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return validate_semver(value)

    @field_validator(
        "compatible_template_changes",
        "compatible_modifier_changes",
        "notes",
    )
    @classmethod
    def unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("upgrade rule tuple values must be unique")
        return values

    @field_validator("compatible_template_changes")
    @classmethod
    def valid_template_changes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _TEMPLATE_ID.fullmatch(value) for value in values):
            raise ValueError("compatible template changes contain an invalid template ID")
        return values

    @field_validator("compatible_modifier_changes")
    @classmethod
    def valid_modifier_changes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _MODIFIER_ID.fullmatch(value) for value in values):
            raise ValueError("compatible modifier changes contain an invalid modifier ID")
        return values

    @field_validator("template_replacements")
    @classmethod
    def valid_template_replacements(cls, values: dict[str, str]) -> dict[str, str]:
        if any(
            not _TEMPLATE_ID.fullmatch(identifier)
            for pair in values.items()
            for identifier in pair
        ):
            raise ValueError("template replacements contain an invalid template ID")
        return values

    @field_validator("modifier_replacements")
    @classmethod
    def valid_modifier_replacements(cls, values: dict[str, str]) -> dict[str, str]:
        if any(
            not _MODIFIER_ID.fullmatch(identifier)
            for pair in values.items()
            for identifier in pair
        ):
            raise ValueError("modifier replacements contain an invalid modifier ID")
        return values


class AgencyPackManifest(_PackModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: str
    templates: PackPayloadReference
    modifiers: PackPayloadReference
    upgrade_rules: tuple[PackUpgradeRule, ...] = ()

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return validate_semver(value)

    @model_validator(mode="after")
    def unique_upgrade_sources(self) -> "AgencyPackManifest":
        versions = [item.from_version for item in self.upgrade_rules]
        if len(versions) != len(set(versions)):
            raise ValueError("upgrade rules must have unique from_version values")
        if self.version in versions:
            raise ValueError("an agency pack cannot define an upgrade from itself")
        return self


__all__ = [
    "AgencyPackManifest",
    "ModifierContract",
    "ModifierLibraryPayload",
    "PackPayloadReference",
    "PackUpgradeRule",
    "TemplateContract",
    "TemplateLibraryPayload",
]
