"""DNN JWT authentication helpers."""

from __future__ import annotations

import time
from typing import Optional

import requests

from vanjaro_cli.config import Config, ConfigError, save_config

# DNN JWT auth endpoints
LOGIN_PATH = "/API/JwtAuth/Login"
REISSUE_PATH = "/API/JwtAuth/ReIssueToken"
LOGOUT_PATH = "/API/JwtAuth/LogOut"


def login(base_url: str, username: str, password: str) -> Config:
    """Authenticate against DNN JWT endpoint and return a populated Config."""
    url = base_url.rstrip("/") + LOGIN_PATH
    response = requests.post(
        url,
        json={"u": username, "p": password},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code == 401:
        raise AuthError("Invalid username or password.")
    response.raise_for_status()

    data = response.json()
    token = data.get("Token") or data.get("token")
    refresh_token = data.get("RenewToken") or data.get("renewToken")

    if not token:
        raise AuthError(f"Unexpected login response: {data}")

    config = Config(base_url=base_url, token=token, refresh_token=refresh_token)
    save_config(config)
    return config


def reissue_token(config: Config) -> Config:
    """Refresh an expiring token using the renew endpoint."""
    if not config.refresh_token:
        raise AuthError("No refresh token available. Please log in again.")

    url = config.base_url + REISSUE_PATH
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {config.token}",
        },
        timeout=30,
    )
    if response.status_code in (401, 403):
        raise AuthError("Session expired. Please log in again.")
    response.raise_for_status()

    data = response.json()
    new_token = data.get("Token") or data.get("token")
    new_refresh = data.get("RenewToken") or data.get("renewToken")

    if not new_token:
        raise AuthError(f"Unexpected reissue response: {data}")

    config = config.model_copy(
        update={"token": new_token, "refresh_token": new_refresh or config.refresh_token}
    )
    save_config(config)
    return config


def logout(config: Config) -> None:
    """Invalidate the token server-side."""
    if not config.token:
        return
    url = config.base_url + LOGOUT_PATH
    try:
        requests.get(
            url,
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=10,
        )
    except requests.RequestException:
        pass  # Best-effort; local config is cleared regardless


def is_token_expired(token: str) -> bool:
    """Decode JWT expiry claim without a full validation library."""
    try:
        import base64

        parts = token.split(".")
        if len(parts) != 3:
            return True
        # JWT payload is base64url — pad to multiple of 4
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json_loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp", 0)
        # Treat as expired if within 60 s of expiry
        return time.time() >= (exp - 60)
    except Exception:
        return False


def json_loads(data: bytes) -> dict:
    import json

    return json.loads(data)


class AuthError(Exception):
    pass
