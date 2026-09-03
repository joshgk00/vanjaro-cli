"""Pure, deterministic launch-intent contracts for managed project pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.models import DesignDocument, NavigationVisibility
from vanjaro_cli.project.launch_receipt import (
    fingerprint_launch_payload,
    finalize_launch_payload,
)
from vanjaro_cli.reliability.contracts import LAUNCH_PLAN_SCHEMA


class LaunchPlanError(ValueError):
    """Raised when source evidence cannot produce explicit launch intent."""


class _LaunchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LaunchPlanPage(_LaunchModel):
    page_key: str = Field(min_length=1)
    page_id: int = Field(ge=0)
    source_slug: str
    desired_name: str = Field(min_length=1, max_length=200)
    desired_title: str = Field(min_length=1, max_length=200)
    parent_key: str | None = None
    parent_id: int | None = Field(default=None, ge=0)
    navigation_visible: bool
    navigation_order: int = Field(ge=0)


class LaunchPlan(_LaunchModel):
    schema_version: Literal["agency-launch-plan-v1"] = LAUNCH_PLAN_SCHEMA
    project_id: str = Field(min_length=1)
    design_document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    preserve_current_home: bool
    home_page_key: str | None = None
    pages: list[LaunchPlanPage] = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_contract(self) -> "LaunchPlan":
        if self.preserve_current_home == (self.home_page_key is not None):
            raise ValueError(
                "choose exactly one of preserve_current_home or home_page_key"
            )
        keys = [page.page_key for page in self.pages]
        ids = [page.page_id for page in self.pages]
        if len(keys) != len(set(keys)) or len(ids) != len(set(ids)):
            raise ValueError("launch plan page keys and IDs must be unique")
        by_key = {page.page_key: page for page in self.pages}
        for page in self.pages:
            if page.parent_key is None:
                if page.parent_id is not None:
                    raise ValueError("root launch pages must not declare parent_id")
            else:
                parent = by_key.get(page.parent_key)
                if parent is None or page.parent_id != parent.page_id:
                    raise ValueError("launch page parent ownership is inconsistent")
        if self.home_page_key is not None:
            home = by_key.get(self.home_page_key)
            if home is None:
                raise ValueError("launch home_page_key does not identify a managed page")
            if not home.navigation_visible:
                raise ValueError("launch home page must be visible in navigation")
        unsigned = self.model_dump(mode="json", exclude={"fingerprint"})
        if self.fingerprint != fingerprint_launch_payload(unsigned):
            raise ValueError("launch plan fingerprint does not match its payload")
        return self


def build_launch_plan(
    document: DesignDocument,
    page_records: Sequence[Mapping[str, Any]],
    *,
    project_id: str,
    design_document_sha256: str,
    page_manifest_sha256: str,
    home_page_key: str | None,
    preserve_current_home: bool,
    visibility_overrides: Mapping[str, bool] | None = None,
    name_overrides: Mapping[str, str] | None = None,
    title_overrides: Mapping[str, str] | None = None,
) -> LaunchPlan:
    """Create explicit editor-facing intent without portal or filesystem access."""

    visibility = dict(visibility_overrides or {})
    names = dict(name_overrides or {})
    titles = dict(title_overrides or {})
    records = _page_records(page_records)
    document_keys = {page.id for page in document.pages}
    for label, values in (
        ("visibility", visibility),
        ("name", names),
        ("title", titles),
    ):
        unknown = sorted(set(values) - document_keys)
        if unknown:
            raise LaunchPlanError(f"unknown page key in {label} override: {unknown[0]}")
    if set(records) != document_keys:
        missing = sorted(document_keys - set(records))
        extra = sorted(set(records) - document_keys)
        raise LaunchPlanError(
            f"managed page manifest does not match the resolved design; missing={missing}, extra={extra}"
        )

    sibling_orders: dict[str | None, int] = {}
    pages: list[dict[str, Any]] = []
    for source in document.pages:
        record = records[source.id]
        page_id = record["page_id"]
        parent_id = (
            records[source.parent_page_id]["page_id"]
            if source.parent_page_id is not None
            else None
        )
        if source.id in visibility:
            is_visible = visibility[source.id]
        elif source.navigation_visibility == NavigationVisibility.UNKNOWN:
            raise LaunchPlanError(
                f"page {source.id!r} has unknown navigation visibility; provide an explicit override"
            )
        else:
            is_visible = source.navigation_visibility == NavigationVisibility.VISIBLE
        order = sibling_orders.get(source.parent_page_id, 0)
        sibling_orders[source.parent_page_id] = order + 1
        desired_name = _nonempty(names.get(source.id, source.title), "name", source.id)
        desired_title = _nonempty(
            titles.get(source.id, source.seo.title if source.seo and source.seo.title else source.title),
            "title",
            source.id,
        )
        pages.append(
            {
                "page_key": source.id,
                "page_id": page_id,
                "source_slug": source.slug,
                "desired_name": desired_name,
                "desired_title": desired_title,
                "parent_key": source.parent_page_id,
                "parent_id": parent_id,
                "navigation_visible": is_visible,
                "navigation_order": order,
            }
        )

    unsigned = {
        "schema_version": LAUNCH_PLAN_SCHEMA,
        "project_id": project_id,
        "design_document_sha256": design_document_sha256,
        "page_manifest_sha256": page_manifest_sha256,
        "preserve_current_home": preserve_current_home,
        "home_page_key": home_page_key,
        "pages": pages,
    }
    return LaunchPlan.model_validate(finalize_launch_payload(unsigned))


def _page_records(values: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        key = value.get("key")
        page_id = value.get("page_id")
        if not isinstance(key, str) or not key:
            raise LaunchPlanError("managed page record has no page key")
        if isinstance(page_id, bool) or not isinstance(page_id, int) or page_id < 0:
            raise LaunchPlanError(f"managed page {key!r} has no valid page ID")
        if key in result:
            raise LaunchPlanError(f"duplicate managed page key: {key!r}")
        result[key] = {"page_id": page_id}
    return result


def _nonempty(value: str, label: str, page_key: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise LaunchPlanError(f"page {page_key!r} has an empty launch {label}")
    return normalized


__all__ = [
    "LaunchPlan",
    "LaunchPlanError",
    "LaunchPlanPage",
    "build_launch_plan",
]
