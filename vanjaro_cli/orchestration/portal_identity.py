"""Read-only portal identity preflight shared by every project mutation stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import JsonValue

from vanjaro_cli.client import VanjaroClient
from vanjaro_cli.config import Config, load_config
from vanjaro_cli.models.site import HealthCheck
from vanjaro_cli.project.models import ProjectManifest


HEALTH_ENDPOINT = "/API/VanjaroAI/AIHealth/Check"


class PortalIdentityError(ValueError):
    """Raised before mutation when configured and expected portal identities differ."""


@dataclass(frozen=True, slots=True)
class VerifiedPortal:
    profile: str
    base_url: str
    portal_id: int
    health_status: str
    dnn_version: str
    vanjaro_version: str
    user_name: str

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "profile": self.profile,
            "base_url": self.base_url,
            "portal_id": self.portal_id,
            "health_status": self.health_status,
            "dnn_version": self.dnn_version,
            "vanjaro_version": self.vanjaro_version,
            "user_name": self.user_name,
        }


def verify_project_portal(
    manifest: ProjectManifest,
    *,
    config_loader: Callable[[str], Config] = load_config,
    client_factory: Callable[[Config], Any] = VanjaroClient,
) -> tuple[VanjaroClient, VerifiedPortal]:
    """Verify profile, URL, configured portal, and live health before any POST."""

    target = manifest.target
    if target.expected_base_url is None or target.expected_portal_id is None:
        raise PortalIdentityError(
            "project target must pin expected_base_url and expected_portal_id before mutation"
        )
    config = config_loader(target.profile)
    expected_url = normalize_base_url(target.expected_base_url)
    configured_url = normalize_base_url(config.base_url)
    if configured_url != expected_url:
        raise PortalIdentityError(
            f"target URL mismatch: project expects {expected_url}, profile "
            f"{target.profile!r} resolves to {configured_url}"
        )
    if config.portal_id != target.expected_portal_id:
        raise PortalIdentityError(
            f"configured portal mismatch: project expects {target.expected_portal_id}, "
            f"profile {target.profile!r} contains {config.portal_id}"
        )
    client = client_factory(config)
    response = client.get(HEALTH_ENDPOINT)
    health = HealthCheck.from_api(response.json())
    if health.portal_id != target.expected_portal_id:
        raise PortalIdentityError(
            f"live portal mismatch: project expects {target.expected_portal_id}, "
            f"health endpoint returned {health.portal_id}"
        )
    if health.status and health.status.casefold() not in {"ok", "healthy", "success"}:
        raise PortalIdentityError(
            f"target health check is not healthy: {health.status}"
        )
    return client, VerifiedPortal(
        profile=target.profile,
        base_url=configured_url,
        portal_id=health.portal_id,
        health_status=health.status,
        dnn_version=health.dnn_version,
        vanjaro_version=health.vanjaro_version,
        user_name=health.user_name,
    )


def normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold()
    if not scheme or not hostname:
        raise PortalIdentityError(f"invalid target base URL: {value!r}")
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


__all__ = [
    "HEALTH_ENDPOINT",
    "PortalIdentityError",
    "VerifiedPortal",
    "normalize_base_url",
    "verify_project_portal",
]
