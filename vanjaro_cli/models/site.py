"""Site analysis and health check data models — shaped around Vanjaro's AISiteAnalysis and AIHealth API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


__all__ = [
    "HealthCheck",
    "SiteAnalysis",
    "SiteInfo",
]


class SiteInfo(BaseModel):
    """Top-level site info from analysis."""

    name: str = ""
    description: str = ""
    theme: str = ""
    url: str = ""

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SiteInfo:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "theme": self.theme,
            "url": self.url,
        }


class SiteAnalysis(BaseModel):
    """Full site analysis result (from AISiteAnalysis/Analyze)."""

    site: dict[str, Any] = Field(default_factory=dict)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    global_blocks: list[dict[str, Any]] = Field(alias="globalBlocks", default_factory=list)
    design_summary: dict[str, Any] = Field(alias="designSummary", default_factory=dict)
    assets: dict[str, Any] = Field(default_factory=dict)
    branding: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SiteAnalysis:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "site_name": self.site.get("name", ""),
            "theme": self.site.get("theme", ""),
            "pages": len(self.pages),
            "global_blocks": len(self.global_blocks),
            "total_files": self.assets.get("totalFiles", 0),
        }


class HealthCheck(BaseModel):
    """Health check response (from AIHealth/Check)."""

    status: str = ""
    dnn_version: str = Field(alias="dnnVersion", default="")
    vanjaro_version: str = Field(alias="vanjaroVersion", default="")
    user_id: int = Field(alias="userId", default=0)
    user_name: str = Field(alias="userName", default="")
    portal_id: int = Field(alias="portalId", default=0)
    timestamp: str = ""

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> HealthCheck:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "dnn_version": self.dnn_version,
            "vanjaro_version": self.vanjaro_version,
            "user": self.user_name,
            "portal_id": self.portal_id,
        }
