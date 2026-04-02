"""Content/component data models — shaped around Vanjaro's GrapesJS storage."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ContentBlock(BaseModel):
    """A single GrapesJS component block within a page."""

    id: str = ""
    type: str = ""
    content: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    styles: list[dict[str, Any]] = Field(default_factory=list)
    components: list["ContentBlock"] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class PageContent(BaseModel):
    """Full GrapesJS page content as returned by Vanjaro."""

    page_id: int = 0
    locale: str = "en-US"
    # Raw GrapesJS JSON structures
    components: list[dict[str, Any]] = Field(default_factory=list)
    styles: list[dict[str, Any]] = Field(default_factory=list)
    # Vanjaro wraps these in a container object
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, page_id: int, data: dict[str, Any], locale: str = "en-US") -> "PageContent":
        components = data.get("components", data.get("Components", []))
        styles = data.get("styles", data.get("Styles", []))
        # Some Vanjaro versions wrap everything under a "BlockData" key
        if "BlockData" in data:
            block = data["BlockData"]
            if isinstance(block, dict):
                components = block.get("components", components)
                styles = block.get("styles", styles)
        return cls(
            page_id=page_id,
            locale=locale,
            components=components,
            styles=styles,
            raw=data,
        )

    def to_api_payload(self) -> dict[str, Any]:
        return {
            "pageId": self.page_id,
            "locale": self.locale,
            "components": self.components,
            "styles": self.styles,
        }
