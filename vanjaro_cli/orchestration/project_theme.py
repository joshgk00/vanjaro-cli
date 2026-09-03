"""Read-only project theme planning against a verified Vanjaro target."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vanjaro_cli.design.serialization import read_design_document
from vanjaro_cli.design.theme_plan import build_project_theme_plan
from vanjaro_cli.orchestration.portal_identity import verify_project_portal
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.project.stage_engine import StageContext, StageResult
from vanjaro_cli.reliability import atomic_write_json


GET_THEME_SETTINGS = "/API/VanjaroAI/AIDesign/GetSettings"


def preview_project_theme_stage(
    root: Path,
    manifest: ProjectManifest,
) -> dict[str, Any]:
    """Return the proposed plan after GET-only live capability discovery.

    This function does not write local artifacts and never invokes a client
    mutation method. It is suitable for ``project build --dry-run`` previews.
    """

    client, verified = verify_project_portal(manifest)
    document = read_design_document(root / "plans/resolved-design-document.json")
    settings = _read_settings(client)
    plan = build_project_theme_plan(document, settings)
    return {
        **plan.model_dump(mode="json"),
        "target": verified.as_dict(),
        "http_writes": 0,
        "local_writes": 0,
    }


def plan_project_theme_stage(context: StageContext) -> StageResult:
    """Write deterministic plan artifacts without changing the live theme."""

    client, verified = verify_project_portal(context.manifest)
    document = read_design_document(
        context.root / "plans/resolved-design-document.json"
    )
    plan = build_project_theme_plan(document, _read_settings(client))
    plan_relative = "build/theme-plan.json"
    palette_relative = "build/theme-palette.json"
    result_relative = "build/theme-result.json"
    _write_json(context.root / plan_relative, plan.model_dump(mode="json"))
    _write_json(context.root / palette_relative, plan.proposed_palette)
    _write_json(
        context.root / result_relative,
        {
            "schema_version": "1.0",
            "mode": "plan",
            "mutated": False,
            "target": verified.as_dict(),
            "theme_name": plan.theme_name,
            "proposed_controls": len(plan.controls),
            "changed_controls": sum(item.changed for item in plan.controls),
            "palette_slots": len(plan.proposed_palette),
            "unresolved_warnings": len(plan.warnings),
            "http_writes": 0,
        },
    )
    return StageResult(
        artifacts=(plan_relative, palette_relative, result_relative),
        message=(
            f"Planned {len(plan.controls)} existing theme control(s) and "
            f"{len(plan.proposed_palette)} palette slot(s) without mutating portal "
            f"{verified.portal_id}."
        ),
    )


def _read_settings(client: Any) -> dict[str, Any]:
    payload = client.get(GET_THEME_SETTINGS).json()
    if not isinstance(payload, dict):
        raise ValueError("theme settings endpoint returned a non-object payload")
    return payload


def _write_json(path: Path, value: object) -> None:
    atomic_write_json(path, value)


__all__ = [
    "GET_THEME_SETTINGS",
    "plan_project_theme_stage",
    "preview_project_theme_stage",
]
