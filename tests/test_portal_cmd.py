"""Contracts for the portal list and create commands."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.commands.portal_cmd import portal


BASE = "https://example.vanjaro.com"
CREATE_URL = f"{BASE}/API/PersonaBar/Sites/CreatePortal"
LIST_URL = f"{BASE}/API/PersonaBar/Sites/GetPortals"


def _created(portal_id: int = 3, name: str = "EDCA Consulting", errors=None) -> dict:
    return {
        "Portal": {
            "PortalID": portal_id,
            "PortalName": name,
            "PortalAliases": [{"url": "example.vanjaro.com/edca"}],
            "Pages": 7,
        },
        "ErrorMessage": errors or [],
    }


@responses.activate
def test_list_shows_every_portal_with_its_alias(runner, mock_config):
    responses.add(
        responses.GET,
        LIST_URL,
        json={
            "Results": [
                {
                    "PortalID": 2,
                    "PortalName": "Keys to Success",
                    "Pages": 8,
                    "PortalAliases": [{"url": "example.vanjaro.com/keys-to-success"}],
                },
                {
                    "PortalID": 0,
                    "PortalName": "Root",
                    "Pages": 46,
                    "PortalAliases": [{"url": "vanjarocli.local"}],
                },
            ]
        },
    )

    result = runner.invoke(portal, ["list"])

    assert result.exit_code == 0
    # Ordered by portal ID so the output is stable between runs.
    assert result.output.index("Root") < result.output.index("Keys to Success")
    assert "example.vanjaro.com/keys-to-success" in result.output


@responses.activate
def test_create_requests_a_child_portal_under_the_current_host(runner, mock_config):
    responses.add(responses.POST, CREATE_URL, json=_created())

    result = runner.invoke(
        portal, ["create", "--name", "EDCA Consulting", "--slug", "edca", "--no-profile"]
    )

    assert result.exit_code == 0
    sent = json.loads(responses.calls[-1].request.body)
    assert sent["SiteAlias"] == "example.vanjaro.com/edca"
    assert sent["IsChildSite"] is True
    assert sent["UseCurrentUserAsAdmin"] is True
    # The default template ships demo content that would pollute a baseline.
    assert sent["SiteTemplate"].startswith("Blank Website.template")


@responses.activate
def test_create_reports_the_new_portal_id(runner, mock_config):
    responses.add(responses.POST, CREATE_URL, json=_created(portal_id=7))

    result = runner.invoke(
        portal, ["create", "--name", "Oasis", "--slug", "oasis", "--no-profile", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["portal_id"] == 7


@responses.activate
def test_create_saves_a_profile_bound_to_the_new_portal(runner, mock_config):
    responses.add(responses.POST, CREATE_URL, json=_created(portal_id=4))

    result = runner.invoke(
        portal, ["create", "--name", "Oasis Advisors", "--slug", "oasis"]
    )

    assert result.exit_code == 0
    from vanjaro_cli.config import load_config

    saved = load_config("oasis")
    assert saved.portal_id == 4
    assert saved.base_url == "http://example.vanjaro.com/oasis"


@responses.activate
def test_creating_a_portal_does_not_move_the_active_profile(runner, mock_config):
    # Creating a site should not silently repoint an existing session.
    from vanjaro_cli.config import get_active_profile_name

    before = get_active_profile_name()
    responses.add(responses.POST, CREATE_URL, json=_created(portal_id=5))

    runner.invoke(portal, ["create", "--name", "Taylor", "--slug", "taylor"])

    assert get_active_profile_name() == before


@responses.activate
def test_a_local_instance_without_smtp_still_reports_success(runner, mock_config):
    # DNN reports the failed confirmation email as an error even though the
    # portal was created; treating that as a failure would be wrong.
    responses.add(
        responses.POST,
        CREATE_URL,
        json=_created(errors=["There was an error sending confirmation emails - SMTP Server not configured"]),
    )

    result = runner.invoke(
        portal, ["create", "--name", "EDCA", "--slug", "edca", "--no-profile"]
    )

    assert result.exit_code == 0
    assert "Created portal 3" in result.output
    assert "SMTP" in result.output


@responses.activate
def test_a_response_without_a_portal_is_a_failure(runner, mock_config):
    responses.add(responses.POST, CREATE_URL, json={"ErrorMessage": ["Alias in use"]})

    result = runner.invoke(
        portal, ["create", "--name", "EDCA", "--slug", "edca", "--no-profile"]
    )

    assert result.exit_code != 0
    assert "no portal" in result.output.lower()


def test_an_invalid_slug_is_refused_before_any_request(runner, mock_config):
    # No responses registered: a request here would raise, so passing proves
    # the slug was rejected before the network call.
    result = runner.invoke(
        portal, ["create", "--name", "EDCA", "--slug", "EDCA Consulting"]
    )

    assert result.exit_code != 0
    assert "lowercase" in result.output
