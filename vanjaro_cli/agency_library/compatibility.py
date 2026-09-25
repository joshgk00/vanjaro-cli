"""Pure deterministic compatibility planning for agency-pack upgrades."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.agency_library.models import PackUpgradeRule
from vanjaro_cli.agency_library.registry import ResolvedAgencyPack
from vanjaro_cli.utils.semver import compare_semver


class _CompatibilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgencyPackUsage(_CompatibilityModel):
    templates: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    sections_by_template: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    source_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    replan_input_fingerprint: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )

    @model_validator(mode="after")
    def sorted_unique(self) -> "AgencyPackUsage":
        if self.templates != tuple(sorted(set(self.templates), key=str.casefold)):
            raise ValueError("usage templates must be sorted and unique")
        if self.modifiers != tuple(sorted(set(self.modifiers), key=str.casefold)):
            raise ValueError("usage modifiers must be sorted and unique")
        if tuple(self.sections_by_template) != tuple(
            sorted(self.sections_by_template, key=str.casefold)
        ):
            raise ValueError("usage section mappings must be sorted by template")
        if set(self.sections_by_template) - set(self.templates):
            raise ValueError("usage section mappings must reference used templates")
        for sections in self.sections_by_template.values():
            if sections != tuple(sorted(set(sections), key=str.casefold)):
                raise ValueError("usage section mappings must be sorted and unique")
        return self


class AgencyPackChangeSummary(_CompatibilityModel):
    templates_added: tuple[str, ...]
    templates_removed: tuple[str, ...]
    templates_changed: tuple[str, ...]
    modifiers_added: tuple[str, ...]
    modifiers_removed: tuple[str, ...]
    modifiers_changed: tuple[str, ...]
    template_library_version_changed: bool
    modifier_library_version_changed: bool
    capability_schema_changed: bool


class AgencyPackCompatibilityIssue(_CompatibilityModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    severity: Literal["warning", "remediation", "blocker"]
    subject: str | None = None
    replacement: str | None = None
    message: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)


class AgencyPackUpgradeReport(_CompatibilityModel):
    schema_version: Literal["1.0"] = "1.0"
    pack_name: str
    from_version: str
    to_version: str
    from_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    to_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    usage: AgencyPackUsage
    changes: AgencyPackChangeSummary
    issues: tuple[AgencyPackCompatibilityIssue, ...]
    status: Literal["compatible", "remediation_required", "blocked"]
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class AgencyPackCompatibilityError(ValueError):
    def __init__(self, code: str, message: str, *, recommended_action: str) -> None:
        self.code = code
        self.recommended_action = recommended_action
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {
            "category": self.code,
            "message": str(self),
            "recommended_action": self.recommended_action,
        }


def read_project_pack_usage(
    composition_plan: Path, *, replan_inputs: tuple[Path, ...] = ()
) -> AgencyPackUsage:
    """Read only the governed template/modifier identities from a plan artifact."""

    if not composition_plan.is_file():
        return AgencyPackUsage()
    try:
        raw = composition_plan.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise AgencyPackCompatibilityError(
            "agency_pack_usage_invalid",
            f"cannot read composition plan usage: {exc}",
            recommended_action="Regenerate the project plan before checking a pack upgrade.",
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise AgencyPackCompatibilityError(
            "agency_pack_usage_invalid",
            "composition plan does not contain an entries list",
            recommended_action="Regenerate the project plan before checking a pack upgrade.",
        )
    templates: set[str] = set()
    modifiers: set[str] = set()
    sections: dict[str, set[str]] = {}
    for entry in payload["entries"]:
        if not isinstance(entry, dict):
            raise AgencyPackCompatibilityError(
                "agency_pack_usage_invalid",
                "composition plan entries must be objects",
                recommended_action="Regenerate the project plan before checking a pack upgrade.",
            )
        template_id = entry.get("template_id")
        if not isinstance(template_id, str) or not template_id.strip():
            raise AgencyPackCompatibilityError(
                "agency_pack_usage_invalid",
                "every composition plan entry must declare a non-empty template_id",
                recommended_action="Regenerate the project plan before checking a pack upgrade.",
            )
        templates.add(template_id.strip())
        section_id = entry.get("source_section_id")
        if section_id is not None:
            if not isinstance(section_id, str) or not section_id.strip():
                raise AgencyPackCompatibilityError(
                    "agency_pack_usage_invalid",
                    "composition plan source_section_id values must be non-empty strings",
                    recommended_action="Regenerate the project plan before checking a pack upgrade.",
                )
            sections.setdefault(template_id.strip(), set()).add(section_id.strip())
        entry_modifiers = entry.get("modifiers", [])
        if not isinstance(entry_modifiers, list) or not all(
            isinstance(item, str) and item.strip() for item in entry_modifiers
        ):
            raise AgencyPackCompatibilityError(
                "agency_pack_usage_invalid",
                "composition plan modifiers must be non-empty strings",
                recommended_action="Regenerate the project plan before checking a pack upgrade.",
            )
        modifiers.update(item.strip() for item in entry_modifiers)
    return AgencyPackUsage(
        templates=tuple(sorted(templates, key=str.casefold)),
        modifiers=tuple(sorted(modifiers, key=str.casefold)),
        sections_by_template={
            key: tuple(sorted(values, key=str.casefold))
            for key, values in sorted(sections.items(), key=lambda item: item[0].casefold())
        },
        source_fingerprint=hashlib.sha256(raw).hexdigest(),
        replan_input_fingerprint=(
            _fingerprint_replan_inputs(replan_inputs) if replan_inputs else None
        ),
    )


def _fingerprint_replan_inputs(paths: tuple[Path, ...]) -> str:
    inventory: list[dict[str, object]] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        exists = resolved.is_file()
        label = (
            resolved.name
            if resolved.name == "project.json"
            else f"{resolved.parent.name}/{resolved.name}"
        )
        inventory.append(
            {
                "path": label,
                "exists": exists,
                "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()
                if exists
                else None,
            }
        )
    return _canonical_sha256(inventory)


def plan_agency_pack_upgrade(
    current: ResolvedAgencyPack,
    target: ResolvedAgencyPack,
    usage: AgencyPackUsage,
) -> AgencyPackUpgradeReport:
    """Classify an upgrade and emit stable remediation without mutating a project."""

    if current.manifest.name != target.manifest.name:
        raise AgencyPackCompatibilityError(
            "agency_pack_name_mismatch",
            f"cannot upgrade {current.manifest.name!r} to {target.manifest.name!r}",
            recommended_action="Select a target version of the project's current pack.",
        )
    if compare_semver(target.manifest.version, current.manifest.version) <= 0:
        raise AgencyPackCompatibilityError(
            "agency_pack_upgrade_direction_invalid",
            f"target {target.manifest.version} must be newer than {current.manifest.version}",
            recommended_action="Select a newer published Semantic Version.",
        )
    if current.styles is not None or target.styles is not None:
        # W1 only defines the executable style payload and its pure,
        # non-installing resolution (style_context.py); it does not yet
        # define how an upgrade should compare, migrate, or replan style
        # utilities. Approving an upgrade here would be a silent guess about
        # compatibility this codebase has not reviewed, so it fails closed
        # -- called from apply_agency_pack_upgrade before any project file
        # is touched, so this also blocks before mutation.
        raise AgencyPackCompatibilityError(
            "agency_pack_style_upgrade_unsupported",
            "executable agency-pack styles are not yet supported by the upgrade "
            "planner; style compatibility and replanning ships in a later stage",
            recommended_action=(
                "Do not upgrade to or from a pack version that declares executable "
                "styles until style-aware upgrade planning is implemented."
            ),
        )

    current_templates = {item.template_id: item for item in current.templates.templates}
    target_templates = {item.template_id: item for item in target.templates.templates}
    current_modifiers = {item.modifier_id: item for item in current.modifiers.modifiers}
    target_modifiers = {item.modifier_id: item for item in target.modifiers.modifiers}
    changed_templates = tuple(
        sorted(
            (
                identifier
                for identifier in current_templates.keys() & target_templates.keys()
                if current_templates[identifier] != target_templates[identifier]
            ),
            key=str.casefold,
        )
    )
    changed_modifiers = tuple(
        sorted(
            (
                identifier
                for identifier in current_modifiers.keys() & target_modifiers.keys()
                if current_modifiers[identifier] != target_modifiers[identifier]
            ),
            key=str.casefold,
        )
    )
    changes = AgencyPackChangeSummary(
        templates_added=_difference(target_templates, current_templates),
        templates_removed=_difference(current_templates, target_templates),
        templates_changed=changed_templates,
        modifiers_added=_difference(target_modifiers, current_modifiers),
        modifiers_removed=_difference(current_modifiers, target_modifiers),
        modifiers_changed=changed_modifiers,
        template_library_version_changed=(
            current.templates.version != target.templates.version
        ),
        modifier_library_version_changed=(
            current.modifiers.version != target.modifiers.version
        ),
        capability_schema_changed=(
            current.templates.capability_schema_version
            != target.templates.capability_schema_version
        ),
    )
    rule = next(
        (
            item
            for item in target.manifest.upgrade_rules
            if item.from_version == current.manifest.version
        ),
        None,
    )
    issues = _compatibility_issues(
        current_templates=set(current_templates),
        current_modifiers=set(current_modifiers),
        target_templates=set(target_templates),
        target_modifiers=set(target_modifiers),
        usage=usage,
        changes=changes,
        rule=rule,
    )
    status: Literal["compatible", "remediation_required", "blocked"] = "compatible"
    if any(item.severity == "blocker" for item in issues):
        status = "blocked"
    elif any(item.severity == "remediation" for item in issues):
        status = "remediation_required"
    core = {
        "schema_version": "1.0",
        "pack_name": current.manifest.name,
        "from_version": current.manifest.version,
        "to_version": target.manifest.version,
        "from_digest": current.digest,
        "to_digest": target.digest,
        "usage": usage.model_dump(mode="json"),
        "changes": changes.model_dump(mode="json"),
        "issues": [item.model_dump(mode="json") for item in issues],
        "status": status,
    }
    return AgencyPackUpgradeReport(
        **core,
        fingerprint=_canonical_sha256(core),
    )


def _compatibility_issues(
    *,
    current_templates: set[str],
    current_modifiers: set[str],
    target_templates: set[str],
    target_modifiers: set[str],
    usage: AgencyPackUsage,
    changes: AgencyPackChangeSummary,
    rule: PackUpgradeRule | None,
) -> tuple[AgencyPackCompatibilityIssue, ...]:
    issues: list[AgencyPackCompatibilityIssue] = []
    if usage.source_fingerprint is None:
        issues.append(
            _issue(
                "project_usage_unavailable",
                "blocker",
                "The project has no composition plan, so no template or modifier usage could be assessed.",
                "Run project plan before applying a future pack upgrade.",
            )
        )
    if rule is None:
        issues.append(
            _issue(
                "upgrade_rule_missing",
                "blocker",
                "The target pack does not declare a compatibility rule from the current version.",
                "Publish an explicit reviewed upgrade rule before upgrading client projects.",
            )
        )
    if changes.capability_schema_changed and not (
        rule and rule.compatible_capability_schema_change
    ):
        issues.append(
            _issue(
                "capability_schema_changed",
                "blocker",
                "The template capability schema version changed.",
                "Migrate and revalidate physical capability contracts before upgrading.",
            )
        )
    elif changes.capability_schema_changed:
        issues.append(
            _issue(
                "capability_schema_change_reviewed",
                "warning",
                "The template capability schema change was explicitly reviewed as compatible.",
                "Run physical-contract and visual regression checks before applying the upgrade.",
            )
        )
    for template_id in usage.templates:
        if template_id not in current_templates:
            issues.append(
                _issue(
                    "current_template_unlocked",
                    "blocker",
                    f"The current plan uses template {template_id!r}, which is absent from the current pack.",
                    "Replan with the locked current pack before upgrading.",
                    subject=template_id,
                )
            )
            continue
        if template_id in changes.templates_removed:
            replacement = rule.template_replacements.get(template_id) if rule else None
            valid_replacement = replacement in target_templates if replacement else False
            issues.append(
                _issue(
                    "used_template_replacement_required" if valid_replacement else "used_template_removed",
                    "remediation" if valid_replacement else "blocker",
                    f"Used template {template_id!r} is removed from the target pack.",
                    (
                        f"Replan the affected sections with replacement {replacement!r}."
                        if valid_replacement
                        else "Restore the template or declare a valid replacement before upgrading."
                    ),
                    subject=template_id,
                    replacement=replacement if valid_replacement else None,
                )
            )
        elif template_id in changes.templates_changed:
            compatible = bool(rule and template_id in rule.compatible_template_changes)
            issues.append(
                _issue(
                    "used_template_changed_reviewed" if compatible else "used_template_changed_unreviewed",
                    "warning" if compatible else "blocker",
                    f"Used template {template_id!r} changed in the target pack.",
                    (
                        "Run visual regression after the reviewed compatible change."
                        if compatible
                        else "Review and declare the template change compatible or provide a replacement."
                    ),
                    subject=template_id,
                )
            )
    for modifier_id in usage.modifiers:
        if modifier_id not in current_modifiers:
            issues.append(
                _issue(
                    "current_modifier_unlocked",
                    "blocker",
                    f"The current plan uses modifier {modifier_id!r}, which is absent from the current pack.",
                    "Replan with the locked current pack before upgrading.",
                    subject=modifier_id,
                )
            )
            continue
        if modifier_id in changes.modifiers_removed:
            replacement = rule.modifier_replacements.get(modifier_id) if rule else None
            valid_replacement = replacement in target_modifiers if replacement else False
            issues.append(
                _issue(
                    "used_modifier_replacement_required" if valid_replacement else "used_modifier_removed",
                    "remediation" if valid_replacement else "blocker",
                    f"Used modifier {modifier_id!r} is removed from the target pack.",
                    (
                        f"Replan the affected sections with replacement {replacement!r}."
                        if valid_replacement
                        else "Restore the modifier or declare a valid replacement before upgrading."
                    ),
                    subject=modifier_id,
                    replacement=replacement if valid_replacement else None,
                )
            )
        elif modifier_id in changes.modifiers_changed:
            compatible = bool(rule and modifier_id in rule.compatible_modifier_changes)
            issues.append(
                _issue(
                    "used_modifier_changed_reviewed" if compatible else "used_modifier_changed_unreviewed",
                    "warning" if compatible else "blocker",
                    f"Used modifier {modifier_id!r} changed in the target pack.",
                    (
                        "Run visual regression after the reviewed compatible change."
                        if compatible
                        else "Review and declare the modifier change compatible or provide a replacement."
                    ),
                    subject=modifier_id,
                )
            )
    return tuple(sorted(issues, key=lambda item: (item.severity, item.code, item.subject or "")))


def _issue(
    code: str,
    severity: Literal["warning", "remediation", "blocker"],
    message: str,
    action: str,
    *,
    subject: str | None = None,
    replacement: str | None = None,
) -> AgencyPackCompatibilityIssue:
    return AgencyPackCompatibilityIssue(
        code=code,
        severity=severity,
        subject=subject,
        replacement=replacement,
        message=message,
        recommended_action=action,
    )


def _difference(left: dict[str, object], right: dict[str, object]) -> tuple[str, ...]:
    return tuple(sorted(left.keys() - right.keys(), key=str.casefold))


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "AgencyPackChangeSummary",
    "AgencyPackCompatibilityError",
    "AgencyPackCompatibilityIssue",
    "AgencyPackUpgradeReport",
    "AgencyPackUsage",
    "plan_agency_pack_upgrade",
    "read_project_pack_usage",
]
