"""DNN/Vanjaro cookie-based authentication helpers.

Vanjaro's login module uses a JavaScript AJAX call to its own API endpoint,
not the standard DNN JWT auth or ASP.NET form postback. We replicate that
AJAX call: POST credentials to /API/Login/Login/UserLogin with the
anti-forgery token and DNN Services Framework headers (TabId, ModuleId).
The server sets auth cookies on success.
"""

from __future__ import annotations

import re

import requests

from vanjaro_cli.config import Config, derive_profile_name, save_config

__all__ = ["AuthError", "login", "logout"]

# Vanjaro login API endpoint (DNN Services Framework route)
LOGIN_API_PATH = "/API/Login/Login/UserLogin"

# Regex to extract the anti-forgery token from DNN page HTML
_ANTIFORGERY_RE = re.compile(
    r'<input[^>]+name="__RequestVerificationToken"[^>]+value="([^"]+)"'
)

# Regex to extract sf_tabId from DNN's __dnnVariable hidden field
_TAB_ID_RE = re.compile(r'sf_tabId`:`(\d+)`')

# Known DNN auth cookie names
_AUTH_COOKIE_NAMES = {".dotnetnuke", ".aspxauth", "authentication"}


def login(base_url: str, username: str, password: str, profile_name: str | None = None) -> Config:
    """Authenticate via Vanjaro's login API and return a Config with session cookies."""
    base_url = base_url.rstrip("/")
    session = requests.Session()

    # Step 1: GET the login page to get anti-forgery token, tabId, and cookies
    login_page_url = base_url + "/Login"
    try:
        page_resp = session.get(login_page_url, timeout=30)
    except requests.RequestException as exc:
        raise AuthError(f"Cannot reach {login_page_url}: {exc}") from exc

    if page_resp.status_code == 404:
        raise AuthError(
            f"Login page not found at {login_page_url}. "
            "Verify the site URL is correct."
        )

    # Extract anti-forgery token from the page
    antiforgery_match = _ANTIFORGERY_RE.search(page_resp.text)
    if not antiforgery_match:
        raise AuthError(
            "Could not find anti-forgery token on login page. "
            "The site may use a custom login module."
        )
    antiforgery_token = antiforgery_match.group(1)

    # Extract tabId from __dnnVariable
    tab_id_match = _TAB_ID_RE.search(page_resp.text)
    tab_id = tab_id_match.group(1) if tab_id_match else "-1"

    # Step 2: POST credentials to the Vanjaro login API
    login_url = base_url + LOGIN_API_PATH
    response = session.post(
        login_url,
        json={"Username": username, "Password": password, "Remember": False},
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "RequestVerificationToken": antiforgery_token,
            "TabId": tab_id,
            "ModuleId": "-1",
        },
        timeout=30,
    )

    if response.status_code == 401:
        raise AuthError("Invalid username or password.")
    if response.status_code == 404:
        raise AuthError(
            f"Login API not found at {login_url}. "
            "Verify Vanjaro is installed on this DNN site."
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise AuthError(f"Login request failed: {exc}") from exc

    # Step 3: Check the API response
    try:
        data = response.json()
    except ValueError:
        raise AuthError(f"Unexpected login response (not JSON): {response.text[:200]}")

    if data.get("HasErrors"):
        error_msg = data.get("Message", "Login failed.")
        raise AuthError(error_msg)

    if not data.get("IsSuccess"):
        raise AuthError(data.get("Message", "Login was not successful."))

    # Step 4: Capture auth cookies
    all_cookies = {c.name: c.value for c in session.cookies}
    has_auth_cookie = any(
        name.lower() in _AUTH_COOKIE_NAMES
        or "auth" in name.lower()
        or "dotnetnuke" in name.lower()
        for name in all_cookies
    )

    if not has_auth_cookie:
        raise AuthError(
            "Login succeeded but no auth cookies were returned. "
            "This may be a server configuration issue."
        )

    config = Config(base_url=base_url, cookies=all_cookies)
    resolved_profile = profile_name or derive_profile_name(base_url)
    save_config(config, resolved_profile)
    return config


def logout(config: Config) -> None:
    """Best-effort logout by hitting the DNN logoff endpoint."""
    if not config.cookies:
        return
    try:
        session = requests.Session()
        for name, value in config.cookies.items():
            session.cookies.set(name, value)
        session.get(config.base_url + "/Logoff", timeout=10)
    except requests.RequestException:
        pass  # Best-effort; local config is cleared regardless


class AuthError(Exception):
    pass
