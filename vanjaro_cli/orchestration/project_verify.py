"""Read-only verification gate for complete project drafts."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from pydantic import ValidationError

from vanjaro_cli.design.composition import deserialize_composition_plan
from vanjaro_cli.design.models import ContentKind
from vanjaro_cli.design.quality_counts import compute_quality_counts
from vanjaro_cli.design.serialization import read_design_document
from vanjaro_cli.design.template_catalog import TemplateCatalogError, load_template_catalog
from vanjaro_cli.migration.audit import audit_page
from vanjaro_cli.migration.text_match import fuzzy_set_match
from vanjaro_cli.orchestration.portal_identity import verify_project_portal
from vanjaro_cli.orchestration.project_capture_evidence import (
    resolve_workspace_capture_coverage,
)
from vanjaro_cli.orchestration.project_fidelity import evaluate_project_fidelity
from vanjaro_cli.portal.global_block_manifest import global_block_content_hash
from vanjaro_cli.portal.page_composition import page_content_hash
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.project.stage_engine import StageContext, StageResult
from vanjaro_cli.reliability import atomic_write_json


_COMPOSITION_PLAN_PATH = "plans/composition-plan.json"


GET_PAGE = "/API/VanjaroAI/AIPage/Get"
GET_GLOBAL = "/API/VanjaroAI/AIGlobalBlock/Get"


class ProjectVerificationError(ValueError):
    """Raised when draft verification inputs or live responses are invalid."""


def verify_project_drafts(context: StageContext) -> StageResult:
    """Verify page/global drafts and write a publish-approval owner artifact."""

    report = preview_project_drafts(context.root, context.manifest)
    report_relative = "verify/draft-verification.json"
    _write_json(context.root / report_relative, report)
    return StageResult(
        artifacts=(report_relative,),
        message=(
            f"Verified {report['page_count']} page draft(s) and "
            f"{report['global_count']} global draft(s); "
            f"{report['blocker_count']} publish blocker(s)."
        ),
    )


def preview_project_drafts(
    root: Path, manifest: ProjectManifest
) -> dict[str, Any]:
    """Evaluate the complete draft gate with GETs and local reads only."""

    client, verified = verify_project_portal(manifest)
    document = read_design_document(root / "build/design-document.json")
    page_manifest = _read_object(
        root / "build/global-page-manifest.json", "global page manifest"
    )
    global_manifest = _read_object(
        root / "build/global-block-manifest.json", "global block manifest"
    )
    page_records = page_manifest.get("pages", [])
    global_records = global_manifest.get("blocks", [])
    if not isinstance(page_records, list) or not isinstance(global_records, list):
        raise ProjectVerificationError("build manifests contain unexpected records")

    global_details: dict[str, dict[str, Any]] = {}
    for record in global_records:
        if not isinstance(record, dict) or not isinstance(record.get("guid"), str):
            raise ProjectVerificationError("global manifest contains an invalid record")
        detail = client.get(  # type: ignore[attr-defined]
            GET_GLOBAL, params={"guid": record["guid"]}
        ).json()
        if not isinstance(detail, dict):
            raise ProjectVerificationError("global detail returned an unexpected response")
        global_details[record["kind"]] = detail

    desired_global_guids = {
        record["kind"]: record["guid"]
        for record in global_records
        if isinstance(record, dict)
    }
    pages: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []
    all_rendered_text = _component_text(
        [
            component
            for detail in global_details.values()
            for component in _json_value(detail.get("contentJSON"), "global contentJSON")
        ]
    )

    for record in page_records:
        if not isinstance(record, dict) or not isinstance(record.get("page_id"), int):
            raise ProjectVerificationError("page manifest contains an invalid record")
        detail = client.get(  # type: ignore[attr-defined]
            GET_PAGE,
            params={
                "pageId": record["page_id"],
                "includeDraft": "true",
                "locale": "en-US",
            },
        ).json()
        if not isinstance(detail, dict):
            raise ProjectVerificationError("page detail returned an unexpected response")
        components = _json_value(detail.get("contentJSON"), "page contentJSON")
        styles = _json_value(detail.get("styleJSON"), "page styleJSON")
        if not isinstance(components, list) or not isinstance(styles, list):
            raise ProjectVerificationError("page draft content has an unexpected shape")
        html = detail.get("contentHtml", "")
        if not isinstance(html, str):
            raise ProjectVerificationError("page contentHtml is not a string")
        wrappers = [item for item in components if item.get("type") == "globalblockwrapper"]
        wrapper_guids = {
            str(item.get("name", "")).removeprefix("Global: ").casefold():
            item.get("attributes", {}).get("data-guid")
            for item in wrappers
        }
        ids = _component_ids(components)
        duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
        leaked_paths = sorted(
            value
            for value in _strings(components)
            if value.startswith("sources/") or value.startswith("figma://")
        )
        structural = audit_page(
            record.get("path", "draft"), f'<div id="vjEditor">{html}</div>'
        )
        page_blockers: list[str] = []
        live_hash = page_content_hash(components, styles, html)
        desired_hash = record.get("desired_hash")
        if not isinstance(desired_hash, str) or live_hash != desired_hash:
            page_blockers.append("draft content differs from the managed desired hash")
        if bool(detail.get("isVisible", False)):
            page_blockers.append("page is visible")
        if bool(detail.get("isPublished", False)):
            page_blockers.append("page is already published")
        if detail.get("version") != record.get("observed_version"):
            page_blockers.append("draft version differs from the managed manifest")
        if wrapper_guids != desired_global_guids:
            page_blockers.append("global wrapper GUIDs do not match the managed globals")
        if duplicate_ids:
            page_blockers.append(f"duplicate component IDs: {duplicate_ids[:5]}")
        if leaked_paths:
            page_blockers.append(f"local/source asset paths remain: {leaked_paths[:5]}")
        if structural["score"] < 80:
            page_blockers.append(
                f"structural audit score {structural['score']} is below 80"
            )
        blockers.extend(f"page {record['page_id']}: {message}" for message in page_blockers)
        all_rendered_text.extend(_component_text(components))
        pages.append(
            {
                "page_id": record["page_id"],
                "path": record.get("path", ""),
                "version": detail.get("version"),
                "desired_hash": desired_hash,
                "observed_hash": live_hash,
                "visible": bool(detail.get("isVisible", False)),
                "published": bool(detail.get("isPublished", False)),
                "top_level_components": len(components),
                "global_wrappers": len(wrappers),
                "duplicate_component_ids": duplicate_ids,
                "leaked_paths": leaked_paths,
                "structural_audit": structural,
                "blockers": page_blockers,
            }
        )

    global_observed_hashes: dict[str, str] = {}
    for kind, detail in global_details.items():
        live_hash = global_block_content_hash(
            _json_value(detail.get("contentJSON"), "global contentJSON"),
            _json_value(detail.get("styleJSON"), "global styleJSON"),
        )
        if bool(detail.get("isPublished", False)):
            blockers.append(f"global {kind}: desired version is already published")
        matching = next(
            record for record in global_records
            if isinstance(record, dict) and record.get("kind") == kind
        )
        if detail.get("version") != matching.get("observed_version"):
            blockers.append(f"global {kind}: version differs from the managed manifest")
        desired_hash = matching.get("desired_hash")
        if not isinstance(desired_hash, str) or live_hash != desired_hash:
            blockers.append(
                f"global {kind}: content differs from the managed desired hash"
            )
        global_observed_hashes[kind] = live_hash
        warnings.extend(matching.get("warnings", []))

    source_text = [
        str(element.value)
        for page in document.pages
        for section in page.sections
        for element in section.content
        if element.value not in (None, "")
        and element.kind in {
            ContentKind.HEADING,
            ContentKind.TEXT,
            ContentKind.BUTTON,
            ContentKind.LINK,
            ContentKind.LIST,
            ContentKind.LIST_ITEM,
            ContentKind.QUOTE,
            ContentKind.STAT,
        }
        and not _is_sample_copy(str(element.value))
    ]
    matched, missing = fuzzy_set_match(source_text, all_rendered_text)
    coverage = len(matched) / len(source_text) if source_text else 1.0
    if coverage < 0.9:
        blockers.append(
            f"source text coverage {coverage:.1%} is below the 90% publish threshold"
        )

    missing_action_urls = [
        element.id
        for page in document.pages
        for section in page.sections
        for element in section.content
        if element.kind in {ContentKind.BUTTON, ContentKind.LINK}
        and not (element.attributes.get("href") or element.attributes.get("url"))
    ]
    if missing_action_urls:
        blockers.append(
            f"{len(missing_action_urls)} source action(s) have no URL mapping"
        )

    visual_fidelity, fidelity_blockers = evaluate_project_fidelity(root, manifest)
    blockers.extend(fidelity_blockers)
    quality_counts = _quality_counts_report(root, manifest)

    return {
            "schema_version": "1.1",
            "valid": not blockers,
            "visual_fidelity": visual_fidelity,
            "quality_counts": quality_counts,
            "target": verified.as_dict(),
            "page_count": len(pages),
            "global_count": len(global_details),
            "source_text_coverage": coverage,
            "source_text_total": len(source_text),
            "source_text_matched": len(matched),
            "missing_source_text": missing,
            "missing_action_url_count": len(missing_action_urls),
            "missing_action_url_element_ids": missing_action_urls,
            "blocker_count": len(blockers),
            "blockers": blockers,
            "warning_count": len(warnings),
            "warnings": warnings,
            "pages": pages,
            "globals": [
                {
                    "kind": kind,
                    "guid": detail.get("guid"),
                    "version": detail.get("version"),
                    "desired_hash": next(
                        record.get("desired_hash")
                        for record in global_records
                        if isinstance(record, dict) and record.get("kind") == kind
                    ),
                    "observed_hash": global_observed_hashes[kind],
                    "published": bool(detail.get("isPublished", False)),
                }
                for kind, detail in sorted(global_details.items())
            ],
        }


def _quality_counts_report(root: Path, manifest: ProjectManifest) -> dict[str, Any]:
    """Compute the release quality ratios from the workspace's plan, or warn.

    Local reads only, and never fails the verify stage: a missing or invalid
    plan is unusual at verify time (planning runs first), but reporting a
    warning instead of raising keeps this read-only gate available even when
    it is. Page identity and capture coverage come from
    `resolve_workspace_capture_coverage`, the same read used by
    `vanjaro project quality`, so the two never disagree.
    """

    plan_path = root / _COMPOSITION_PLAN_PATH
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError as error:
        return {
            "status": "not_available",
            "warnings": [f"cannot read {_COMPOSITION_PLAN_PATH}: {error}"],
        }
    try:
        plan = deserialize_composition_plan(plan_text)
    except (ValueError, ValidationError) as error:
        return {
            "status": "not_available",
            "warnings": [f"invalid composition plan at {_COMPOSITION_PLAN_PATH}: {error}"],
        }
    try:
        catalog = load_template_catalog()
    except TemplateCatalogError as error:
        return {
            "status": "not_available",
            "warnings": [f"cannot read the template library: {'; '.join(error.issues)}"],
        }
    coverage = resolve_workspace_capture_coverage(root, manifest)
    report = compute_quality_counts(
        plan, catalog, coverage.capture_evidence, page_identity=coverage.page_identity
    )
    return {
        "status": "scored",
        "eligible_section_editable_coverage": report.eligible_section_editable_coverage.model_dump(mode="json"),
        "native_agency_component_ratio": report.native_agency_component_ratio.model_dump(mode="json"),
        "body_without_generic_fallback": report.body_without_generic_fallback.model_dump(mode="json"),
        "desktop_tablet_mobile_evidence": report.desktop_tablet_mobile_evidence.model_dump(mode="json"),
        "warnings": list(report.warnings) + list(coverage.warnings),
    }


def _component_text(components: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    stack: list[object] = list(components)
    while stack:
        component = stack.pop()
        if not isinstance(component, dict):
            continue
        content = component.get("content")
        if isinstance(content, str) and content.strip():
            result.append(content)
        stack.extend(component.get("components", []))
    return result


def _is_sample_copy(value: str) -> bool:
    return bool(
        re.search(
            r"(?:lorem\s+ipsum|put your actual text|placeholder(?:\s+text)?|example\.com)",
            value,
            re.IGNORECASE,
        )
    )


def _component_ids(components: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    stack: list[object] = list(components)
    while stack:
        component = stack.pop()
        if not isinstance(component, dict):
            continue
        identifier = component.get("attributes", {}).get("id")
        if isinstance(identifier, str) and identifier:
            result.append(identifier)
        stack.extend(component.get("components", []))
    return result


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _json_value(value: object, label: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProjectVerificationError(f"{label} contains invalid JSON") from exc
    if isinstance(value, (list, dict)):
        return value
    raise ProjectVerificationError(f"{label} has an unexpected type")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectVerificationError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectVerificationError(f"{label} must contain a JSON object")
    return value


def _write_json(path: Path, value: object) -> None:
    atomic_write_json(path, value)


__all__ = [
    "ProjectVerificationError",
    "preview_project_drafts",
    "verify_project_drafts",
]
