"""Tests for zero-mutation target identity preflight."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vanjaro_cli.config import Config
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.orchestration.portal_identity import (
    PortalIdentityError,
    normalize_base_url,
    verify_project_portal,
)
from vanjaro_cli.project import ProjectSource, create_manifest


class Response:
    def __init__(self, portal_id: int, status: str = "ok") -> None:
        self.portal_id = portal_id
        self.status = status

    def json(self):
        return {
            "status": self.status,
            "portalId": self.portal_id,
            "userName": "Host",
            "dnnVersion": "9",
            "vanjaroVersion": "1",
        }


class FakeClient:
    def __init__(self, config: Config, *, live_portal: int) -> None:
        self.config = config
        self.live_portal = live_portal
        self.gets: list[str] = []
        self.posts: list[str] = []

    def get(self, path: str):
        self.gets.append(path)
        return Response(self.live_portal)


def _manifest(base_url: str = "https://Agency.Example/site/", portal_id: int = 7):
    return create_manifest(
        name="Identity",
        target_profile="client-a",
        expected_base_url=base_url,
        expected_portal_id=portal_id,
        sources=[
            ProjectSource(
                id="html-1",
                kind=SourceKind.LIVE_HTML,
                reference="https://source.example/",
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1",
        clock=lambda: datetime(2026, 7, 16, tzinfo=timezone.utc),
    )


def test_verify_project_portal_requires_matching_url_config_and_live_portal() -> None:
    client: FakeClient | None = None

    def make_client(config: Config):
        nonlocal client
        client = FakeClient(config, live_portal=7)
        return client

    result_client, verified = verify_project_portal(
        _manifest(),
        config_loader=lambda profile: Config(
            base_url="https://agency.example/site",
            portal_id=7,
        ),
        client_factory=make_client,
    )

    assert result_client is client
    assert verified.base_url == "https://agency.example/site"
    assert verified.portal_id == 7
    assert client is not None and client.gets == ["/API/VanjaroAI/AIHealth/Check"]
    assert client.posts == []


@pytest.mark.parametrize(
    ("configured_url", "configured_portal", "live_portal", "message"),
    [
        ("https://other.example/site", 7, 7, "target URL mismatch"),
        ("https://agency.example/site", 8, 7, "configured portal mismatch"),
        ("https://agency.example/site", 7, 8, "live portal mismatch"),
    ],
)
def test_verify_project_portal_fails_closed_before_mutation(
    configured_url: str,
    configured_portal: int,
    live_portal: int,
    message: str,
) -> None:
    clients: list[FakeClient] = []

    def make_client(config: Config):
        client = FakeClient(config, live_portal=live_portal)
        clients.append(client)
        return client

    with pytest.raises(PortalIdentityError, match=message):
        verify_project_portal(
            _manifest(),
            config_loader=lambda profile: Config(
                base_url=configured_url,
                portal_id=configured_portal,
            ),
            client_factory=make_client,
        )
    assert all(client.posts == [] for client in clients)


def test_normalize_base_url_removes_default_port_and_trailing_slash() -> None:
    assert normalize_base_url("HTTPS://Example.COM:443/site/") == "https://example.com/site"
