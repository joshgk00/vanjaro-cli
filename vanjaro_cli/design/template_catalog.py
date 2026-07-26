"""Validated capability catalog for portable Vanjaro block templates.

Capability metadata is embedded in each authoring template.  This module is
deliberately independent of the CLI and the matcher so offline tooling, tests,
and future planners can all consume the same deterministic catalog.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

__all__ = [
    "CapabilityManifest",
    "FieldRequirement",
    "LayoutCapability",
    "PhysicalFieldCapability",
    "RepeatGroupCapability",
    "ResponsiveCapability",
    "TemplateCatalogEntry",
    "TemplateCatalogError",
    "check_generated_artifacts",
    "default_templates_dir",
    "load_template_catalog",
    "load_template_data",
    "render_capability_schema",
    "render_catalog_markdown",
    "write_generated_artifacts",
]


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TEMPLATES_DIR = _PROJECT_ROOT / "artifacts" / "block-templates"
_DEFAULT_SCHEMA_PATH = _PROJECT_ROOT / "schemas" / "template-capabilities-v1.1.schema.json"
_DEFAULT_CATALOG_DOC_PATH = _PROJECT_ROOT / "docs" / "template-capability-catalog.md"

FieldRequirement = Literal["required", "optional"]
LayoutKind = Literal["single", "split", "grid", "band", "list", "accordion", "navigation"]
MediaPosition = Literal["none", "top", "bottom", "left", "right", "background", "inline"]
Alignment = Literal["left", "center", "right", "mixed"]
StackingOrder = Literal["source", "media-first", "content-first", "not-applicable"]
CapabilityName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
CapabilityFieldName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]*$")]
ColumnCount = Annotated[int, Field(ge=1, le=12)]
PhysicalOwner = Literal["section", "repeat_item"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = [value.casefold() for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must not contain duplicates")
    return values


class LayoutCapability(_StrictModel):
    """Structural layouts a template can represent without composition changes."""

    kind: LayoutKind
    columns: tuple[ColumnCount, ...] = Field(min_length=1)
    media_positions: tuple[MediaPosition, ...] = Field(min_length=1)
    alignment: tuple[Alignment, ...] = Field(min_length=1)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 1 or value > 12 for value in values):
            raise ValueError("columns must be between 1 and 12")
        if len(values) != len(set(values)):
            raise ValueError("columns must not contain duplicates")
        return values

    @field_validator("media_positions", "alignment")
    @classmethod
    def validate_options(cls, values: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        return _unique(values, info.field_name)


class RepeatGroupCapability(_StrictModel):
    """Card/list-style repetition supported by a template."""

    kind: CapabilityName = Field(min_length=1)
    minimum: int = Field(ge=1)
    default: int = Field(ge=1)
    maximum: int | None = Field(default=None, ge=1)
    expandable: bool

    @model_validator(mode="after")
    def validate_range(self) -> "RepeatGroupCapability":
        if self.default < self.minimum:
            raise ValueError("default must be greater than or equal to minimum")
        if self.maximum is not None:
            if self.maximum < self.minimum:
                raise ValueError("maximum must be greater than or equal to minimum")
            if self.default > self.maximum:
                raise ValueError("default must be less than or equal to maximum")
        return self


class ResponsiveCapability(_StrictModel):
    """Canonical desktop, tablet, and mobile behavior."""

    desktop_columns: int = Field(ge=1, le=12)
    tablet_columns: int = Field(ge=1, le=12)
    mobile_columns: int = Field(ge=1, le=12)
    stacking_order: StackingOrder


class PhysicalFieldCapability(_StrictModel):
    """Executable GrapesJS slots owned by one semantic capability field."""

    owner: PhysicalOwner
    slot_type: CapabilityName
    slots: tuple[str, ...] = Field(min_length=1)
    slots_per_owner: int = Field(ge=1)

    @field_validator("slots")
    @classmethod
    def validate_slots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("physical slot keys must be non-empty")
        return _unique(values, "physical slots")


class CapabilityManifest(_StrictModel):
    """Versioned matcher-facing capabilities embedded in a template."""

    schema_version: Literal["1.0", "1.1"]
    roles: tuple[CapabilityName, ...] = Field(min_length=1)
    layout: LayoutCapability
    repeat_group: RepeatGroupCapability | None = None
    fields: dict[CapabilityFieldName, FieldRequirement] = Field(min_length=1)
    static_fields: tuple[CapabilityFieldName, ...] = ()
    physical_fields: dict[CapabilityFieldName, PhysicalFieldCapability] = Field(
        default_factory=dict
    )
    responsive: ResponsiveCapability
    interactions: tuple[CapabilityName, ...] = ()
    native_component_ratio: float = Field(ge=0.0, le=1.0)
    supported_modifiers: tuple[CapabilityName, ...] = ()

    @field_validator("roles", "interactions", "supported_modifiers")
    @classmethod
    def validate_unique_names(cls, values: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        pattern = re.compile(r"^[a-z][a-z0-9_-]*$")
        invalid = [value for value in values if not pattern.fullmatch(value)]
        if invalid:
            raise ValueError(f"{info.field_name} contains invalid names: {', '.join(invalid)}")
        return _unique(values, info.field_name)

    @field_validator("fields")
    @classmethod
    def validate_field_names(cls, values: dict[str, FieldRequirement]) -> dict[str, FieldRequirement]:
        pattern = re.compile(r"^[a-z][a-z0-9_.-]*$")
        invalid = [name for name in values if not pattern.fullmatch(name)]
        if invalid:
            raise ValueError(f"fields contains invalid names: {', '.join(invalid)}")
        return values

    @field_validator("static_fields")
    @classmethod
    def validate_static_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^[a-z][a-z0-9_.-]*$")
        if any(not pattern.fullmatch(value) for value in values):
            raise ValueError("static_fields contains invalid names")
        return _unique(values, "static_fields")

    @model_validator(mode="after")
    def validate_physical_field_ownership(self) -> "CapabilityManifest":
        overlap = set(self.fields).intersection(self.static_fields)
        if overlap:
            raise ValueError(
                f"static_fields must not duplicate editable fields: {sorted(overlap)}"
            )
        if self.schema_version == "1.0":
            if self.physical_fields:
                raise ValueError("physical_fields requires capability schema_version 1.1")
            return self
        if set(self.physical_fields) != set(self.fields):
            missing = sorted(set(self.fields) - set(self.physical_fields))
            extra = sorted(set(self.physical_fields) - set(self.fields))
            raise ValueError(
                f"physical_fields must exactly match fields; missing={missing}, extra={extra}"
            )
        for field_name, contract in self.physical_fields.items():
            is_repeat = field_name.startswith(("item.", "column."))
            expected_owner = "repeat_item" if is_repeat else "section"
            if contract.owner != expected_owner:
                raise ValueError(
                    f"physical field {field_name!r} must use owner {expected_owner!r}"
                )
            if is_repeat and self.repeat_group is None:
                raise ValueError(
                    f"physical repeat field {field_name!r} requires repeat_group"
                )
        return self


class TemplateCatalogEntry(_StrictModel):
    """One validated catalog record, including its portable template identity."""

    template_id: str
    name: str
    category: str
    description: str
    relative_path: str
    source_path: Path
    capabilities: CapabilityManifest


class TemplateCatalogError(ValueError):
    """Raised when one or more template catalog records are invalid."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = tuple(issues)
        summary = "Template capability catalog validation failed:\n- " + "\n- ".join(issues)
        super().__init__(summary)


def default_templates_dir() -> Path:
    """Return the authoring template directory, honoring the existing override."""

    override = os.environ.get("VANJARO_TEMPLATES_DIR")
    return Path(override) if override else _DEFAULT_TEMPLATES_DIR


def _validation_messages(path: Path, error: ValidationError) -> list[str]:
    messages: list[str] = []
    for detail in error.errors(include_url=False):
        location = ".".join(str(part) for part in detail["loc"])
        messages.append(f"{path.as_posix()}: capabilities.{location}: {detail['msg']}")
    return messages


def load_template_catalog(templates_dir: Path | None = None) -> tuple[TemplateCatalogEntry, ...]:
    """Load every JSON template and validate its embedded capabilities.

    Errors are aggregated so a bulk metadata edit can be repaired in one pass.
    Template names are unique case-insensitively, matching the behavior of the
    existing template resolver.
    """

    root = templates_dir or default_templates_dir()
    if not root.is_dir():
        raise TemplateCatalogError([f"template directory does not exist: {root}"])

    entries: list[TemplateCatalogEntry] = []
    issues: list[str] = []
    seen_names: dict[str, str] = {}

    for path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix().casefold()):
        relative_path = path.relative_to(root).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(f"{relative_path}: cannot read template JSON: {exc}")
            continue
        if not isinstance(data, dict):
            issues.append(f"{relative_path}: template root must be an object")
            continue

        name = data.get("name")
        category = data.get("category")
        description = data.get("description")
        for field_name, value in (("name", name), ("category", category), ("description", description)):
            if not isinstance(value, str) or not value.strip():
                issues.append(f"{relative_path}: {field_name} must be a non-empty string")

        capabilities_data = data.get("capabilities")
        if capabilities_data is None:
            issues.append(f"{relative_path}: capabilities is required")
            continue
        try:
            capabilities = CapabilityManifest.model_validate(capabilities_data)
        except ValidationError as exc:
            issues.extend(_validation_messages(Path(relative_path), exc))
            continue

        if capabilities.schema_version == "1.1":
            from vanjaro_cli.design.physical_contract import validate_physical_contract

            issues.extend(
                f"{relative_path}: {issue}"
                for issue in validate_physical_contract(
                    data.get("template"), capabilities
                )
            )
            if issues and any(issue.startswith(f"{relative_path}:") for issue in issues):
                continue

        if not all(isinstance(value, str) and value.strip() for value in (name, category, description)):
            continue
        normalized_name = name.casefold()
        if normalized_name in seen_names:
            issues.append(
                f"{relative_path}: duplicate template name {name!r}; "
                f"first declared in {seen_names[normalized_name]}"
            )
            continue
        seen_names[normalized_name] = relative_path

        entries.append(
            TemplateCatalogEntry(
                template_id=relative_path.removesuffix(".json"),
                name=name,
                category=category,
                description=description,
                relative_path=relative_path,
                source_path=path.resolve(),
                capabilities=capabilities,
            )
        )

    if not entries and not issues:
        issues.append(f"no JSON templates found in {root}")
    if issues:
        raise TemplateCatalogError(issues)
    return tuple(entries)


def load_template_data(entry: TemplateCatalogEntry) -> dict:
    """Load an entry's complete legacy-compatible template document."""

    data = json.loads(entry.source_path.read_text(encoding="utf-8"))
    if data.get("name") != entry.name:
        raise TemplateCatalogError([f"{entry.relative_path}: template changed after catalog load"])
    return data


def render_capability_schema() -> str:
    """Render the canonical JSON Schema generated from the runtime model."""

    schema = CapabilityManifest.model_json_schema()
    for property_name in ("roles", "interactions", "supported_modifiers"):
        schema["properties"][property_name]["uniqueItems"] = True
    schema["properties"]["fields"]["propertyNames"] = {"pattern": r"^[a-z][a-z0-9_.-]*$"}
    schema["properties"]["physical_fields"]["propertyNames"] = {
        "pattern": r"^[a-z][a-z0-9_.-]*$"
    }
    layout_schema = schema["$defs"]["LayoutCapability"]["properties"]
    for property_name in ("columns", "media_positions", "alignment"):
        layout_schema[property_name]["uniqueItems"] = True
    schema["$id"] = "https://clicksandmortars.com/schemas/template-capabilities-v1.1.schema.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["allOf"] = [
        {
            "if": {"properties": {"schema_version": {"const": "1.1"}}},
            "then": {"required": ["physical_fields"]},
        },
        {
            "if": {"properties": {"schema_version": {"const": "1.0"}}},
            "then": {"properties": {"physical_fields": {"maxProperties": 0}}},
        },
    ]
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_catalog_markdown(catalog: tuple[TemplateCatalogEntry, ...]) -> str:
    """Render deterministic human-readable documentation from a catalog."""

    lines = [
        "# Template Capability Catalog",
        "",
        "<!-- Generated by `python -m vanjaro_cli.design.template_catalog --write`. Do not edit. -->",
        "",
        f"Validated templates: **{len(catalog)}**",
        "",
        "Capability schema version: **1.1**. Unknown properties are rejected within v1.1. "
        "Schema 1.1 requires an exact physical contract for every editable field. "
        "Backward-compatible additions must be optional; breaking field or meaning changes require a new schema file.",
        "",
        "| Template | Category | Roles | Layout | Repeat group | Responsive D/T/M | Native ratio | Editable fields | Static fields | Interactions | Modifiers |",
        "|---|---|---|---|---|---:|---:|---|---|---|---|",
    ]
    for entry in catalog:
        capabilities = entry.capabilities
        repeat = "none"
        if capabilities.repeat_group:
            group = capabilities.repeat_group
            maximum = str(group.maximum) if group.maximum is not None else "unbounded"
            repeat = f"{group.kind} {group.minimum}/{group.default}/{maximum}"
            if group.expandable:
                repeat += " expandable"
        fields = ", ".join(f"{name}:{requirement}" for name, requirement in sorted(capabilities.fields.items()))
        responsive = capabilities.responsive
        cells = [
            f"[{entry.name}](../artifacts/block-templates/{entry.relative_path})",
            entry.category,
            ", ".join(capabilities.roles),
            f"{capabilities.layout.kind} ({'/'.join(str(column) for column in capabilities.layout.columns)})",
            repeat,
            f"{responsive.desktop_columns}/{responsive.tablet_columns}/{responsive.mobile_columns}",
            f"{capabilities.native_component_ratio:.2f}",
            fields,
            ", ".join(capabilities.static_fields) or "none",
            ", ".join(capabilities.interactions) or "none",
            ", ".join(capabilities.supported_modifiers) or "none",
        ]
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |")
    lines.append("")
    return "\n".join(lines)


def write_generated_artifacts(
    *,
    templates_dir: Path | None = None,
    schema_path: Path = _DEFAULT_SCHEMA_PATH,
    documentation_path: Path = _DEFAULT_CATALOG_DOC_PATH,
) -> tuple[Path, Path]:
    """Validate the catalog and regenerate its schema and documentation."""

    catalog = load_template_catalog(templates_dir)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    documentation_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(render_capability_schema(), encoding="utf-8")
    documentation_path.write_text(render_catalog_markdown(catalog), encoding="utf-8")
    return schema_path, documentation_path


def check_generated_artifacts(
    *,
    templates_dir: Path | None = None,
    schema_path: Path = _DEFAULT_SCHEMA_PATH,
    documentation_path: Path = _DEFAULT_CATALOG_DOC_PATH,
) -> tuple[str, ...]:
    """Return generated artifacts that are absent or differ from current data."""

    catalog = load_template_catalog(templates_dir)
    expected = {
        schema_path: render_capability_schema(),
        documentation_path: render_catalog_markdown(catalog),
    }
    drift: list[str] = []
    for path, content in expected.items():
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError:
            drift.append(f"missing generated artifact: {path}")
            continue
        if actual != content:
            drift.append(f"generated artifact is stale: {path}")
    return tuple(drift)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and document block template capabilities.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Regenerate schema and catalog documentation.")
    mode.add_argument("--check", action="store_true", help="Check generated files for drift (default).")
    parser.add_argument("--templates-dir", type=Path, help="Override the template source directory.")
    args = parser.parse_args(argv)
    try:
        if args.write:
            schema, documentation = write_generated_artifacts(templates_dir=args.templates_dir)
            print(f"Wrote {schema}")
            print(f"Wrote {documentation}")
            return 0
        drift = check_generated_artifacts(templates_dir=args.templates_dir)
    except TemplateCatalogError as exc:
        print(exc)
        return 1
    if drift:
        print("\n".join(drift))
        return 1
    print("Template capability catalog is valid and generated artifacts are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
