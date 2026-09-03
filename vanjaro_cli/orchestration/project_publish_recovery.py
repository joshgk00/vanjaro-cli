"""Guarded local recovery operations for interrupted project publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vanjaro_cli.orchestration.project_publish_state import clear_publish_lock


def recover_project_publish_lock(
    root: Path, *, owner_token: str, confirmation: str
) -> dict[str, Any]:
    """Clear a lock only after its exact process instance is proven dead."""

    workspace = root.expanduser().resolve()
    owner = clear_publish_lock(
        workspace, owner_token=owner_token, confirmation=confirmation
    )
    return {
        "status": "stale_lock_cleared",
        "portal_mutated": False,
        "workspace_mutated": True,
        "owner": owner,
    }


__all__ = ["recover_project_publish_lock"]
