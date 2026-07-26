"""Reusable portal operations with no Click presentation dependencies."""

from vanjaro_cli.portal.assets import upload_project_assets
from vanjaro_cli.portal.block_library import (
    BlockLibraryError,
    compose_project_library,
    preview_project_library,
    register_project_library,
)
from vanjaro_cli.portal.pages import (
    ProjectPageError,
    attach_global_wrappers,
    compose_project_pages,
    preview_project_pages,
    reconcile_project_pages,
)
from vanjaro_cli.portal.global_blocks import (
    ProjectGlobalBlockError,
    compose_project_global_blocks,
    preview_project_global_blocks,
    reconcile_project_global_blocks,
)
from vanjaro_cli.portal.global_header import (
    HEADER_COMPOSER_CONTRACT_VERSION,
    build_project_header,
)

__all__ = [
    "BlockLibraryError",
    "HEADER_COMPOSER_CONTRACT_VERSION",
    "ProjectPageError",
    "ProjectGlobalBlockError",
    "attach_global_wrappers",
    "build_project_header",
    "compose_project_global_blocks",
    "compose_project_library",
    "preview_project_library",
    "preview_project_pages",
    "preview_project_global_blocks",
    "register_project_library",
    "reconcile_project_pages",
    "reconcile_project_global_blocks",
    "compose_project_pages",
    "upload_project_assets",
]
