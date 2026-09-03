"""Turn a project Design Document into validated composition/build artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from vanjaro_cli.design.composition import (
    CompositionPlan,
    PlanPolicy,
    serialize_composition_plan,
)
from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.overlays import apply_design_overlays, read_design_overlays
from vanjaro_cli.design.planner import (
    plan_design_document,
    serialize_library_plan,
    validate_composition_plan,
)
from vanjaro_cli.design.serialization import (
    read_design_document,
    serialize_design_document,
)
from vanjaro_cli.design.template_catalog import (
    TemplateCatalogEntry,
    load_template_catalog,
    load_template_data,
)
from vanjaro_cli.portal.global_header import HEADER_COMPOSER_CONTRACT_VERSION
from vanjaro_cli.project.stage_engine import StageContext, StageResult
from vanjaro_cli.reliability import atomic_write_json


def template_catalog_fingerprint() -> str:
    """Fingerprint executable template content used by an approved plan."""

    catalog = load_template_catalog()
    payload = [
        {
            "template_id": entry.template_id,
            "data": load_template_data(entry),
        }
        for entry in catalog
    ]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_project_planning(
    context: StageContext,
    *,
    minimum_confidence: float = 0.65,
    allow_simplification: bool = False,
    css_rule_budget: int = 12,
    template_overrides: Mapping[str, str] | None = None,
    override_author: str = "cli-user",
    override_reason: str = "explicit template override",
    catalog: Sequence[TemplateCatalogEntry] | None = None,
    planning_request: Mapping[str, Any] | None = None,
) -> StageResult:
    """Create the Composition Plan, executable library plan, and gate report."""

    document = read_design_document(context.root / "analysis/design-document.json")
    overlay_path = context.root / "analysis/design-overlays.json"
    overlay_count = 0
    if overlay_path.is_file():
        overlay_set = read_design_overlays(overlay_path)
        document = apply_design_overlays(document, overlay_set)
        overlay_count = len(overlay_set.overlays)
    resolved_catalog = tuple(load_template_catalog() if catalog is None else catalog)
    body_document, global_plan, global_issues = split_global_sections(document)
    plan = plan_design_document(
        body_document,
        catalog=resolved_catalog,
        policy=PlanPolicy(
            minimum_confidence=minimum_confidence,
            allow_simplification=allow_simplification,
            css_rule_budget=css_rule_budget,
        ),
        template_overrides=template_overrides,
        override_author=override_author,
        override_reason=override_reason,
    )
    plan = _scope_block_identity(
        plan,
        project_id=context.manifest.project.id,
    )
    global_plan = _scope_global_identity(
        global_plan,
        project_id=context.manifest.project.id,
    )
    issues = (
        *validate_composition_plan(plan, catalog=resolved_catalog),
        *global_issues,
    )
    composition_path = context.root / "plans/composition-plan.json"
    library_path = context.root / "plans/library-plan.json"
    validation_path = context.root / "plans/validation.json"
    global_path = context.root / "plans/global-block-plan.json"
    resolved_design_path = context.root / "plans/resolved-design-document.json"
    _atomic_write_text(composition_path, serialize_composition_plan(plan))
    _atomic_write_text(library_path, serialize_library_plan(plan))
    _atomic_write_json(global_path, global_plan)
    _atomic_write_text(resolved_design_path, serialize_design_document(document))
    artifacts = [
        "plans/composition-plan.json",
        "plans/library-plan.json",
        "plans/global-block-plan.json",
        "plans/resolved-design-document.json",
        "plans/validation.json",
    ]
    if planning_request is not None:
        _atomic_write_json(
            context.root / "plans/planning-request.json",
            dict(planning_request),
        )
        artifacts.append("plans/planning-request.json")
    total_sections = plan.summary.section_count + global_plan["section_count"]
    combined_native_ratio = (
        (
            plan.summary.native_component_ratio * plan.summary.section_count
            + global_plan["section_count"]
        )
        / total_sections
        if total_sections
        else 0.0
    )
    content_losses = _content_losses(plan)
    _atomic_write_json(
        validation_path,
        {
            "schema_version": "1.0",
            "valid": not issues,
            "issue_count": len(issues),
            "issues": list(issues),
            "content_loss_count": sum(len(fields) for fields in content_losses.values()),
            "content_losses": content_losses,
            "section_count": total_sections,
            "composition_section_count": plan.summary.section_count,
            "global_section_count": global_plan["section_count"],
            "blocking_count": plan.summary.blocking_count + len(global_issues),
            "native_component_ratio": combined_native_ratio,
            "body_native_component_ratio": plan.summary.native_component_ratio,
            "editable_content_coverage": plan.summary.editable_content_coverage,
            "scoped_css_rule_count": plan.summary.scoped_css_rule_count,
            "scoped_css_bytes": plan.summary.scoped_css_bytes,
            "applied_overlay_count": overlay_count,
            "target": context.manifest.target.model_dump(mode="json"),
        },
    )
    return StageResult(
        artifacts=tuple(artifacts),
        message=(
            f"Planned {total_sections} section(s), including "
            f"{global_plan['section_count']} global section(s); "
            f"{len(issues)} approval-blocking validation issue(s)."
        ),
    )


_UNEDITABLE_PREFIX = "source field '"
_UNEDITABLE_SUFFIX = "' is not editable by template"


def _content_losses(plan: CompositionPlan) -> dict[str, list[str]]:
    """List, per section, the source fields the chosen template cannot hold.

    A plan reported `valid: true` with `issue_count: 0` while three card
    sections were losing their heading and two rich-text sections their image
    and their button. The evidence existed only inside the composition plan's
    per-entry requirements; nothing a reader looks at said the build would drop
    visitor content.

    Not blocking — a template that fits imperfectly is still buildable, and
    forcing a block here would stop plans that are fine. Visible, though.
    """

    losses: dict[str, list[str]] = {}
    for entry in plan.entries:
        fields = sorted(
            requirement[len(_UNEDITABLE_PREFIX) : -len(_UNEDITABLE_SUFFIX)]
            for requirement in entry.warnings
            if requirement.startswith(_UNEDITABLE_PREFIX)
            and requirement.endswith(_UNEDITABLE_SUFFIX)
        )
        if fields:
            losses[entry.source_section_id] = fields
    return losses


def _atomic_write_json(path: Path, value: object) -> None:
    atomic_write_json(path, value)


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _scope_block_identity(
    plan: CompositionPlan, *, project_id: str
) -> CompositionPlan:
    """Make editor-facing block identity deterministic and project-specific."""

    category = f"Agency - {project_id}"
    entries = tuple(
        entry.model_copy(
            update={
                "block": entry.block.model_copy(
                    update={
                        "name": f"{project_id} / {entry.block.name}",
                        "category": category,
                    }
                )
            }
        )
        for entry in plan.entries
    )
    return plan.model_copy(update={"entries": entries})


def _scope_global_identity(
    plan: dict[str, Any], *, project_id: str
) -> dict[str, Any]:
    category = f"Agency - {project_id}"
    entries = [
        {
            **entry,
            "name": f"{project_id} / Site {str(entry['kind']).title()}",
            "category": category,
            "type": "global",
        }
        for entry in plan.get("entries", [])
    ]
    return {
        **plan,
        "header_composer_contract_version": HEADER_COMPOSER_CONTRACT_VERSION,
        "entries": entries,
    }


__all__ = ["run_project_planning", "template_catalog_fingerprint"]
