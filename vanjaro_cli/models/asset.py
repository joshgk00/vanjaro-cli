"""Asset and branding data models — shaped around Vanjaro's AIAsset and AIBranding API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


__all__ = [
    "AssetFile",
    "AssetFolder",
    "Branding",
]


class AssetFolder(BaseModel):
    """A folder in the asset library."""

    folder_id: int = Field(alias="folderId", default=0)
    folder_path: str = Field(alias="folderPath", default="")
    display_name: str = Field(alias="displayName", default="")

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AssetFolder:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "folder_id": self.folder_id,
            "path": self.folder_path,
            "name": self.display_name,
        }


class AssetFile(BaseModel):
    """A file in the asset library."""

    file_id: int = Field(alias="fileId", default=0)
    file_name: str = Field(alias="fileName", default="")
    folder_path: str = Field(alias="folderPath", default="")
    relative_path: str = Field(alias="relativePath", default="")
    url: str = ""
    extension: str = ""
    size: int = 0
    width: int | None = None
    height: int | None = None
    content_type: str = Field(alias="contentType", default="")
    last_modified: str | None = Field(alias="lastModified", default=None)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AssetFile:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "folder_path": self.folder_path,
            "size": self.size,
            "content_type": self.content_type,
        }


class Branding(BaseModel):
    """Site branding info (from AIBranding/GetBranding)."""

    site_name: str = Field(alias="siteName", default="")
    description: str = ""
    keywords: str = ""
    footer_text: str = Field(alias="footerText", default="")
    logo: dict[str, Any] | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Branding:
        return cls.model_validate(data)

    def to_row(self) -> dict[str, Any]:
        return {
            "site_name": self.site_name,
            "description": self.description,
            "footer_text": self.footer_text,
            "has_logo": self.logo is not None,
        }
