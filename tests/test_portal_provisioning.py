"""Pure portal provisioning plan contracts."""

from __future__ import annotations

import pytest

from vanjaro_cli.portal.provisioning import (
    BLANK_TEMPLATE,
    PlanError,
    build_creation_plan,
    normalize_portals,
    normalize_warnings,
)


def test_https_child_profile_preserves_scheme_port_and_parent_path():
    plan = build_creation_plan(
        "https://Example.COM:8443/parent/path/",
        name="Child",
        slug="child",
    )
    assert plan.alias == "example.com:8443/parent/path/child"
    assert plan.child_base_url == "https://example.com:8443/parent/path/child"
    assert plan.payload_dict()["SiteTemplate"] == BLANK_TEMPLATE


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "https://user@example.com",
        "https://example.com?secret=x",
        "https://example.com#fragment",
        "https:///missing",
        "https://example.com:bad",
        "https://example.com:99999",
        "https://example.com/a/../b",
        "https://example.com/a/%2e%2e/b",
        "https://example.com/a/%252e%252e/b",
        "https://example.com/a/%252fadmin",
        "https://example.com/a/%255cadmin",
        "https://example.com/a/%2500",
        "https://example.com/a/%257f",
        "https://example.com/a/%25c2%2585",
        "https://example.com/a%2fb",
        "https://example.com/has space",
    ],
)
def test_unsafe_urls_are_rejected(url):
    with pytest.raises(PlanError):
        build_creation_plan(url, name="Child", slug="child")


def test_fingerprint_binds_profile_and_replace_policy():
    plain = build_creation_plan("https://host/root", name="Child", slug="child")
    replaced = build_creation_plan(
        "https://host/root", name="Child", slug="child", replace_profile=True
    )
    assert plain.fingerprint != replaced.fingerprint
    assert plain.fingerprint == build_creation_plan(
        "https://host/root", name="Child", slug="child"
    ).fingerprint


def test_warning_normalization_handles_string_list_and_null():
    assert normalize_warnings(None) == []
    assert normalize_warnings("<b> SMTP </b>  failed") == ["SMTP failed"]
    assert normalize_warnings([" one ", None, "<i>two</i>"]) == ["one", "two"]


def test_warning_normalization_removes_controls_redacts_and_caps_items():
    warnings = normalize_warnings(
        ["\x1b[31m token=super-secret", "Authorization: Bearer abc", *range(20)]
    )
    assert "\x1b" not in "".join(warnings)
    assert "super-secret" not in "".join(warnings)
    assert "Bearer abc" not in "".join(warnings)
    assert len(warnings) == 10


@pytest.mark.parametrize(
    "warning",
    [
        "password=two words",
        "Authorization: Basic dXNlcjpwYXNz",
        'cookie="abc def" tail',
        "API key: first second; unrelated detail",
        "token=one password=two",
    ],
)
def test_warning_normalization_suppresses_the_whole_sensitive_message(warning):
    assert normalize_warnings(warning) == [
        "Server warning contained redacted sensitive data."
    ]


def test_portal_normalization_rejects_duplicate_and_boolean_ids():
    with pytest.raises(PlanError):
        normalize_portals([{"PortalID": 1}, {"PortalID": 1}])
    with pytest.raises(PlanError):
        normalize_portals([{"PortalID": True}])


def test_no_profile_is_coherent_with_profile_options():
    with pytest.raises(PlanError):
        build_creation_plan(
            "https://host", name="Child", slug="child", no_profile=True, profile_name="x"
        )
