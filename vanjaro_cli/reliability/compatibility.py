"""Authoritative supported-version policy and local compatibility checks."""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vanjaro_cli import __version__
from vanjaro_cli.project.models import PROJECT_SCHEMA_VERSION
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json
from vanjaro_cli.reliability.contracts import (
    COMPATIBILITY_POLICY_SCHEMA,
    COMPATIBILITY_REPORT_SCHEMA,
    PERSISTED_RUNTIME_CONTRACTS,
)


class _CompatibilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PythonPolicy(_CompatibilityModel):
    requires_python: Literal[">=3.10"]
    minimum_major: Literal[3]
    minimum_minor: Literal[10]


class CliPolicy(_CompatibilityModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class ContractPolicy(_CompatibilityModel):
    current: str = Field(min_length=1)
    accepted: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def current_must_be_accepted(self) -> "ContractPolicy":
        if self.current not in self.accepted:
            raise ValueError("current contract version must be accepted")
        if len(self.accepted) != len(set(self.accepted)):
            raise ValueError("accepted contract versions must be unique")
        return self


class MigrationPolicy(_CompatibilityModel):
    contract: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    migration_id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]+$")


class VanjaroAIPolicy(_CompatibilityModel):
    page_publish_capability: Literal["supportsExactVersionPublish"]
    global_publish_capability: Literal["supportsExactVersionPublish"]
    launch_state_schema: Literal["agency-launch-state-v1"]
    launch_preview_schema: Literal["agency-launch-preview-v1"]
    launch_apply_schema: Literal["agency-launch-apply-v1"]
    launch_result_schema: Literal["agency-launch-result-v1"]
    atomic_launch_capability: Literal["supportsExactLaunch"]


class PortalVersionPolicy(_CompatibilityModel):
    enforcement: Literal["capability-negotiation"]
    required_observations: tuple[
        Literal["dnn_version", "vanjaro_version", "vanjaro_ai_version"], ...
    ]


class CompatibilityPolicy(_CompatibilityModel):
    schema_version: Literal["agency-compatibility-policy-v1"] = COMPATIBILITY_POLICY_SCHEMA
    python: PythonPolicy
    cli: CliPolicy
    contracts: dict[str, ContractPolicy]
    migrations: tuple[MigrationPolicy, ...]
    vanjaro_ai: VanjaroAIPolicy
    portal_versions: PortalVersionPolicy

    @model_validator(mode="after")
    def require_contract_set(self) -> "CompatibilityPolicy":
        required = {
            "agency_pack",
            "composition_plan",
            "design_document",
            "project",
            "release_contract",
            "template_capability",
        } | set(PERSISTED_RUNTIME_CONTRACTS)
        if set(self.contracts) != required:
            missing = sorted(required - set(self.contracts))
            extra = sorted(set(self.contracts) - required)
            raise ValueError(
                "compatibility policy contracts must be exact; "
                f"missing={missing}, extra={extra}"
            )
        migration_ids = [item.migration_id for item in self.migrations]
        if len(migration_ids) != len(set(migration_ids)):
            raise ValueError("compatibility migration IDs must be unique")
        return self


class CompatibilityReport(_CompatibilityModel):
    schema_version: Literal["compatibility-report-v1"] = COMPATIBILITY_REPORT_SCHEMA
    status: Literal["passed", "failed"]
    policy_path: str
    checks: dict[str, Literal["passed", "failed"]]
    failures: tuple[str, ...]


def load_compatibility_policy(path: Path) -> CompatibilityPolicy:
    try:
        return CompatibilityPolicy.model_validate(load_strict_json(path))
    except (ArtifactContractError, ValidationError) as exc:
        raise ArtifactContractError(f"invalid compatibility policy: {exc}") from exc


def validate_compatibility_policy(path: Path, *, repository_root: Path) -> CompatibilityReport:
    """Validate policy structure against runtime and persisted contract constants."""

    root = repository_root.expanduser().resolve()
    policy_path = path.expanduser().resolve()
    policy = load_compatibility_policy(policy_path)
    checks: dict[str, Literal["passed", "failed"]] = {}
    failures: list[str] = []

    def check(identifier: str, condition: bool, reason: str) -> None:
        checks[identifier] = "passed" if condition else "failed"
        if not condition:
            failures.append(f"{identifier}:{reason}")

    pyproject_path = root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = pyproject["project"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        project = {}
        failures.append(f"pyproject:unreadable:{type(exc).__name__}")
    check(
        "python-runtime",
        sys.version_info[:2] >= (policy.python.minimum_major, policy.python.minimum_minor),
        "runtime-below-minimum",
    )
    check(
        "python-metadata",
        project.get("requires-python") == policy.python.requires_python,
        "requires-python-drift",
    )
    check(
        "cli-runtime-version",
        __version__ == policy.cli.version,
        "runtime-version-drift",
    )
    check(
        "cli-package-version",
        project.get("version") == policy.cli.version,
        "package-version-drift",
    )
    check(
        "project-contract-version",
        PROJECT_SCHEMA_VERSION == policy.contracts["project"].current,
        "project-schema-version-drift",
    )
    expected_contracts = {
        "agency_pack": ("1.0", ("1.0",)),
        "composition_plan": ("2.0", ("2.0",)),
        "design_document": ("1.0", ("1.0",)),
        "template_capability": ("1.1", ("1.0", "1.1")),
        **{
            name: (version, (version,))
            for name, version in PERSISTED_RUNTIME_CONTRACTS.items()
        },
    }
    for name, (current, accepted) in expected_contracts.items():
        observed = policy.contracts[name]
        check(
            f"contract-{name}",
            observed.current == current and observed.accepted == accepted,
            "contract-policy-drift",
        )
    check(
        "project-migration",
        any(
            item.contract == "project"
            and item.source == "1.0"
            and item.target == PROJECT_SCHEMA_VERSION
            and item.migration_id == "project-1.0-to-1.1"
            for item in policy.migrations
        ),
        "required-migration-missing",
    )
    check(
        "portal-version-observations",
        set(policy.portal_versions.required_observations)
        == {"dnn_version", "vanjaro_version", "vanjaro_ai_version"},
        "required-observation-missing",
    )

    try:
        relative_policy = policy_path.relative_to(root).as_posix()
    except ValueError:
        relative_policy = "[outside-repository]"
        failures.append("policy-path:outside-repository")
    return CompatibilityReport(
        status="failed" if failures else "passed",
        policy_path=relative_policy,
        checks=dict(sorted(checks.items())),
        failures=tuple(sorted(failures)),
    )


__all__ = [
    "CompatibilityPolicy",
    "CompatibilityReport",
    "load_compatibility_policy",
    "validate_compatibility_policy",
]
