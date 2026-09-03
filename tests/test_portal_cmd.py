"""Contracts for preview-first portal commands."""

from __future__ import annotations

import json
from unittest.mock import patch

import responses

from vanjaro_cli.commands.portal_cmd import portal

BASE = "https://example.vanjaro.com"
CREATE_URL = f"{BASE}/API/PersonaBar/Sites/CreatePortal"
LIST_URL = f"{BASE}/API/PersonaBar/Sites/GetPortals"
TEMPLATE_URL = f"{BASE}/API/PersonaBar/Sites/GetPortalTemplates"
BLANK = "Blank Website.template|en-US|/"


def _preview(runner, *extra):
    result = runner.invoke(
        portal,
        ["create", "--name", "EDCA", "--slug", "edca", "--dry-run", "--json", *extra],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _register_preflight(portals=None, template=BLANK):
    responses.add(
        responses.GET,
        TEMPLATE_URL,
        json={"Results": {"Templates": [{"Value": template}]}},
    )
    _register_stable_list(portals or [])


def _register_stable_list(portals):
    for _ in range(2):
        responses.add(
            responses.GET,
            LIST_URL,
            json={"Results": portals, "TotalResults": len(portals)},
        )


def _created_portal(portal_id=3):
    return {
        "PortalID": portal_id,
        "PortalName": "EDCA",
        "PortalAliases": [{"url": "example.vanjaro.com/edca"}],
    }


def _create_args(fingerprint, *extra):
    return [
        "create", "--name", "EDCA", "--slug", "edca", "--no-profile",
        "--confirm-create", "--plan-fingerprint", fingerprint, *extra,
    ]


@responses.activate
def test_portal_preview_performs_no_http_or_config_writes(runner, mock_config):
    calls_before = len(responses.calls)
    with (
        patch("vanjaro_cli.commands.portal_cmd.save_config") as save,
        patch(
            "vanjaro_cli.commands.portal_cmd.VanjaroClient",
            side_effect=AssertionError("preview constructed an HTTP client"),
        ),
        patch(
            "vanjaro_cli.config._write_raw_config",
            side_effect=AssertionError("preview wrote config"),
        ),
        patch(
            "vanjaro_cli.config.tempfile.mkstemp",
            side_effect=AssertionError("preview created a temp file"),
        ),
    ):
        preview = _preview(runner, "--no-profile")
    assert len(responses.calls) == calls_before
    save.assert_not_called()
    assert preview["status"] == "preview"
    assert preview["portal_contacted"] is False
    assert preview["profile_written"] is False
    assert preview["required_authority"] == "Host/SuperUser"


@responses.activate
def test_create_rejects_changed_or_missing_plan_fingerprint_before_http(runner, mock_config):
    calls_before = len(responses.calls)
    missing = runner.invoke(portal, ["create", "--name", "EDCA", "--slug", "edca"])
    changed = runner.invoke(portal, _create_args("0" * 64))
    assert missing.exit_code != 0
    assert changed.exit_code != 0
    assert len(responses.calls) == calls_before


@responses.activate
def test_create_preflights_exact_blank_template_and_alias_before_post(runner, mock_config):
    fingerprint = _preview(runner, "--no-profile")["plan_fingerprint"]
    _register_preflight()
    responses.add(
        responses.POST,
        CREATE_URL,
        json={"Portal": _created_portal(), "ErrorMessage": None},
    )
    _register_stable_list([_created_portal()])
    result = runner.invoke(portal, _create_args(fingerprint))
    assert result.exit_code == 0, result.output
    methods = [
        call.request.method
        for call in responses.calls
        if "/API/PersonaBar/Sites/" in call.request.url
    ]
    assert methods == ["GET", "GET", "GET", "POST", "GET", "GET"]
    post = next(call for call in responses.calls if call.request.method == "POST")
    assert json.loads(post.request.body)["SiteTemplate"] == BLANK


@responses.activate
def test_template_absence_and_alias_collision_stop_before_post(runner, mock_config):
    fingerprint = _preview(runner, "--no-profile")["plan_fingerprint"]
    _register_preflight(template="Default.template|en-US|/")
    absent = runner.invoke(portal, _create_args(fingerprint))
    assert absent.exit_code != 0
    responses.reset()
    _register_preflight(
        portals=[
            {
                "PortalID": 2,
                "PortalAliases": [{"url": "EXAMPLE.VANJARO.COM/EDCA/"}],
            }
        ]
    )
    collision = runner.invoke(portal, _create_args(fingerprint))
    assert collision.exit_code != 0
    assert all(call.request.method != "POST" for call in responses.calls)


@responses.activate
def test_profile_save_failure_reports_recoverable_partial_success(runner, mock_config):
    fingerprint = _preview(runner)["plan_fingerprint"]
    _register_preflight()
    responses.add(
        responses.POST,
        CREATE_URL,
        json={"Portal": _created_portal(8)},
    )
    _register_stable_list([_created_portal(8)])
    with patch(
        "vanjaro_cli.commands.portal_cmd.save_config",
        side_effect=OSError("secret path"),
    ):
        result = runner.invoke(
            portal,
            [
                "create",
                "--name",
                "EDCA",
                "--slug",
                "edca",
                "--confirm-create",
                "--plan-fingerprint",
                fingerprint,
                "--json",
            ],
        )
    body = json.loads(result.output)
    assert result.exit_code != 0
    assert body["status"] == "partial_success"
    assert body["portal_id"] == 8
    assert "secret path" not in result.output


@responses.activate
def test_profile_collision_requires_bound_replace_policy(runner, mock_config):
    raw = json.loads(mock_config.read_text())
    raw["profiles"]["edca"] = {"base_url": "https://old", "portal_id": 2}
    mock_config.write_text(json.dumps(raw))
    fingerprint = _preview(runner)["plan_fingerprint"]
    calls_before = len(responses.calls)
    result = runner.invoke(
        portal,
        [
            "create",
            "--name",
            "EDCA",
            "--slug",
            "edca",
            "--confirm-create",
            "--plan-fingerprint",
            fingerprint,
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output
    assert len(responses.calls) == calls_before
    changed = runner.invoke(
        portal,
        [
            "create",
            "--name",
            "EDCA",
            "--slug",
            "edca",
            "--replace-profile",
            "--confirm-create",
            "--plan-fingerprint",
            fingerprint,
        ],
    )
    assert changed.exit_code != 0
    assert "fingerprint mismatch" in changed.output.lower()


@responses.activate
def test_success_saves_https_child_profile_without_moving_active(runner, mock_config):
    from vanjaro_cli.config import get_active_profile_name, load_config

    active_before = get_active_profile_name()
    preview = _preview(runner)
    _register_preflight()
    responses.add(
        responses.POST,
        CREATE_URL,
        json={"Portal": _created_portal(11), "ErrorMessage": []},
    )
    _register_stable_list([_created_portal(11)])
    result = runner.invoke(
        portal,
        [
            "create",
            "--name",
            "EDCA",
            "--slug",
            "edca",
            "--confirm-create",
            "--plan-fingerprint",
            preview["plan_fingerprint"],
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    saved = load_config("edca")
    assert saved.base_url == "https://example.vanjaro.com/edca"
    assert saved.portal_id == 11
    assert get_active_profile_name() == active_before
    assert json.loads(result.output)["plan_fingerprint"] == preview["plan_fingerprint"]


@responses.activate
def test_profile_created_after_preview_is_preserved_as_partial_success(runner, mock_config):
    from vanjaro_cli.config import Config, get_active_profile_name, load_config, save_config

    active_before = get_active_profile_name()
    preview = _preview(runner)
    _register_preflight()
    responses.add(
        responses.POST,
        CREATE_URL,
        json={"Portal": _created_portal(12), "ErrorMessage": None},
    )
    _register_stable_list([_created_portal(12)])

    def concurrent_profile_then_save(config, profile_name, **kwargs):
        save_config(
            Config(base_url="https://concurrent.example/edca", portal_id=77),
            profile_name,
        )
        return save_config(config, profile_name, **kwargs)

    with patch(
        "vanjaro_cli.commands.portal_cmd.save_config",
        side_effect=concurrent_profile_then_save,
    ):
        result = runner.invoke(
            portal,
            [
                "create",
                "--name",
                "EDCA",
                "--slug",
                "edca",
                "--confirm-create",
                "--plan-fingerprint",
                preview["plan_fingerprint"],
                "--json",
            ],
        )

    body = json.loads(result.output)
    assert result.exit_code != 0
    assert body["status"] == "partial_success"
    assert load_config("edca").portal_id == 77
    assert get_active_profile_name() == active_before


def test_preview_surfaces_local_profile_collision(runner, mock_config):
    raw = json.loads(mock_config.read_text())
    raw["profiles"]["edca"] = {"base_url": "https://old", "portal_id": 2}
    mock_config.write_text(json.dumps(raw))

    preview = _preview(runner)

    assert preview["profile_exists"] is True
    assert preview["ready_for_confirmation"] is False


@responses.activate
def test_ambiguous_post_reconciliation_reports_partial_success(runner, mock_config):
    fingerprint = _preview(runner, "--no-profile")["plan_fingerprint"]
    _register_preflight()
    responses.add(responses.POST, CREATE_URL, status=503, body="untrusted secret body")
    _register_stable_list([_created_portal(9)])
    result = runner.invoke(portal, [*_create_args(fingerprint), "--json"])
    body = json.loads(result.output)
    assert result.exit_code != 0
    assert body["status"] == "partial_success"
    assert body["portal_id"] == 9
    assert "untrusted secret body" not in result.output


@responses.activate
def test_list_paginates_and_sorts_portals_and_aliases(runner, mock_config):
    first = [{"PortalID": n, "PortalName": str(n), "PortalAliases": []} for n in range(200, 0, -1)]
    second = [{"PortalID": 0, "PortalName": "root", "PortalAliases": [{"url": "z"}, {"url": "A"}]}]
    responses.add(responses.GET, LIST_URL, json={"Results": first, "TotalResults": 201})
    responses.add(responses.GET, LIST_URL, json={"Results": second, "TotalResults": 201})
    responses.add(responses.GET, LIST_URL, json={"Results": first, "TotalResults": 201})
    responses.add(responses.GET, LIST_URL, json={"Results": second, "TotalResults": 201})
    result = runner.invoke(portal, ["list", "--json"])
    body = json.loads(result.output)
    assert [item["PortalID"] for item in body["results"][:2]] == [0, 1]
    assert [item["url"] for item in body["results"][0]["PortalAliases"]] == ["A", "z"]
    assert body["pagination"]["pages_fetched"] == 2
    assert body["pagination"]["stable_scans"] == 2


@responses.activate
def test_list_fails_closed_when_consecutive_scans_change(runner, mock_config):
    responses.add(
        responses.GET,
        LIST_URL,
        json={"Results": [_created_portal(1)], "TotalResults": 1},
    )
    responses.add(
        responses.GET,
        LIST_URL,
        json={"Results": [_created_portal(2)], "TotalResults": 1},
    )
    result = runner.invoke(portal, ["list", "--json"])
    assert result.exit_code != 0
    assert "changed" in result.output


@responses.activate
def test_duplicate_alias_reconciliation_stays_ambiguous(runner, mock_config):
    fingerprint = _preview(runner, "--no-profile")["plan_fingerprint"]
    _register_preflight()
    responses.add(responses.POST, CREATE_URL, status=503)
    duplicate = [_created_portal(9), _created_portal(10)]
    _register_stable_list(duplicate)
    result = runner.invoke(portal, [*_create_args(fingerprint), "--json"])
    body = json.loads(result.output)
    assert result.exit_code != 0
    assert body["status"] == "partial_success"
    assert body["portal_id"] is None
    assert "Multiple portals" in body["message"]


@responses.activate
def test_http_success_requires_unique_matching_alias_readback(runner, mock_config):
    fingerprint = _preview(runner, "--no-profile")["plan_fingerprint"]
    _register_preflight()
    responses.add(
        responses.POST,
        CREATE_URL,
        json={"Portal": {"PortalID": 3, "PortalName": "EDCA"}},
    )
    _register_stable_list([])
    result = runner.invoke(portal, [*_create_args(fingerprint), "--json"])
    body = json.loads(result.output)
    assert result.exit_code != 0
    assert body["status"] == "partial_success"
    assert body["portal_id"] is None
