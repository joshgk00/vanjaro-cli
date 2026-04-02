"""Page data models — shaped around DNN PersonaBar API responses."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Page(BaseModel):
    """Represents a DNN/Vanjaro page (tab)."""

    id: int = Field(alias="tabId", default=0)
    name: str = Field(alias="name", default="")
    title: str = Field(alias="title", default="")
    url: str = Field(alias="url", default="")
    parent_id: Optional[int] = Field(alias="parentId", default=None)
    is_deleted: bool = Field(alias="isDeleted", default=False)
    include_in_menu: bool = Field(alias="includeInMenu", default=True)
    start_date: Optional[str] = Field(alias="startDate", default=None)
    end_date: Optional[str] = Field(alias="endDate", default=None)
    status: str = Field(alias="status", default="")
    level: int = Field(alias="level", default=0)
    has_children: bool = Field(alias="hasChildren", default=False)
    portal_id: int = Field(alias="portalId", default=0)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Page":
        # Vanjaro GetPages returns {Text, Value, Url} instead of {tabId, name, url}
        if "Value" in data and "tabId" not in data:
            text = data.get("Text", "")
            # Text uses "-  " prefix to indicate child page nesting
            level = 0
            while text.startswith("-  "):
                text = text[3:]
                level += 1
            data = {
                **data,
                "tabId": data["Value"],
                "name": text.strip(),
                "title": text.strip(),
                "url": data.get("Url") or "",
                "level": level,
            }
        # PersonaBar returns camelCase; handle both id spellings
        elif "tabId" not in data and "id" in data:
            data = {**data, "tabId": data["id"]}
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        indent = "  " * self.level
        return {
            "id": self.id,
            "name": f"{indent}{self.name}",
            "url": self.url,
            "status": self.status,
            "in_menu": self.include_in_menu,
        }


class PageSettings(BaseModel):
    """Mutable page settings for create/update calls."""

    name: str
    title: str = ""
    description: str = ""
    keywords: str = ""
    url: str = ""
    parent_id: Optional[int] = None
    include_in_menu: bool = True
    is_visible: bool = True
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    portal_id: int = 0

    def to_api_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "keywords": self.keywords,
            "url": self.url,
            "parentId": self.parent_id,
            "includeInMenu": self.include_in_menu,
            "isVisible": self.is_visible,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "portalId": self.portal_id,
        }
