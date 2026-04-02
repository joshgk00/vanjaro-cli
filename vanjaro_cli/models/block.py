"""Block and template data models — shaped around Vanjaro's AIBlock, AIGlobalBlock, and AITemplate API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


__all__ = [
    "GlobalBlock",
    "GlobalBlockDetail",
    "PageBlock",
    "PageBlockDetail",
    "Template",
    "TemplateDetail",
]


class PageBlock(BaseModel):
    """A block/component within a page (from AIBlock/List)."""

    component_id: str = Field(alias="componentId", default="")
    guid: str = ""
    block_type_guid: str = Field(alias="blockTypeGuid", default="")
    type: str = ""
    name: str = ""
    child_count: int = Field(alias="childCount", default=0)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PageBlock:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "type": self.type,
            "name": self.name,
            "children": self.child_count,
        }


class PageBlockDetail(BaseModel):
    """Detailed block with content (from AIBlock/Get)."""

    page_id: int = Field(alias="pageId", default=0)
    version: int = 0
    component_id: str = Field(alias="componentId", default="")
    guid: str = ""
    block_type_guid: str = Field(alias="blockTypeGuid", default="")
    type: str = ""
    name: str = ""
    content_json: dict[str, Any] | list[Any] = Field(alias="contentJSON", default_factory=dict)
    style_json: list[Any] = Field(alias="styleJSON", default_factory=list)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PageBlockDetail:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "type": self.type,
            "name": self.name,
            "page_id": self.page_id,
            "version": self.version,
        }


class GlobalBlock(BaseModel):
    """A global reusable block (from AIGlobalBlock/List)."""

    id: int = 0
    guid: str = ""
    name: str = ""
    category: str = ""
    is_published: bool = Field(alias="isPublished", default=False)
    version: int = 0
    updated_on: str | None = Field(alias="updatedOn", default=None)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> GlobalBlock:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "published": self.is_published,
            "version": self.version,
        }


class GlobalBlockDetail(BaseModel):
    """Global block with full content (from AIGlobalBlock/Get)."""

    id: int = 0
    guid: str = ""
    name: str = ""
    category: str = ""
    version: int = 0
    is_published: bool = Field(alias="isPublished", default=False)
    content_json: list[Any] = Field(alias="contentJSON", default_factory=list)
    style_json: list[Any] = Field(alias="styleJSON", default_factory=list)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> GlobalBlockDetail:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "published": self.is_published,
            "version": self.version,
        }


class Template(BaseModel):
    """A page template (from AITemplate/List)."""

    name: str = ""
    type: str = ""
    is_system: bool = Field(alias="isSystem", default=False)
    has_svg: bool = Field(alias="hasSvg", default=False)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Template:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "system": self.is_system,
        }


class TemplateDetail(BaseModel):
    """Template with content (from AITemplate/Get)."""

    name: str = ""
    type: str = ""
    is_system: bool = Field(alias="isSystem", default=False)
    svg: str = ""
    content_json: list[Any] = Field(alias="contentJSON", default_factory=list)
    style_json: list[Any] = Field(alias="styleJSON", default_factory=list)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> TemplateDetail:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "system": self.is_system,
            "has_svg": bool(self.svg),
        }
