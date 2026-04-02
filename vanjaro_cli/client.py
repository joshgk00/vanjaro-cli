"""HTTP client wrapper — handles cookie auth, anti-forgery tokens, and error surfacing."""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from vanjaro_cli.auth import AuthError
from vanjaro_cli.config import Config, ConfigError

__all__ = ["VanjaroClient", "ApiError"]

# Regex to extract the anti-forgery token from DNN page HTML
_ANTIFORGERY_RE = re.compile(
    r'<input[^>]+name="__RequestVerificationToken"[^>]+value="([^"]+)"'
)


class VanjaroClient:
    """Thin wrapper around requests that injects cookie auth and anti-forgery headers.

    DNN/Vanjaro API controllers use [ValidateAntiForgeryToken] which requires
    both a __RequestVerificationToken cookie (set by the server) and a matching
    token value in the RequestVerificationToken header. We obtain both by
    fetching the site homepage once per session with the auth cookies active.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._session = requests.Session()
        self._verification_token: str | None = None

        # Load stored auth cookies into the session
        if config.cookies:
            for name, value in config.cookies.items():
                self._session.cookies.set(name, value)

    # ------------------------------------------------------------------
    # Public request methods
    # ------------------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("DELETE", path, **kwargs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        if not self._config.is_authenticated:
            raise ConfigError(
                "Not authenticated. Run `vanjaro auth login` first."
            )
        self._ensure_antiforgery()
        url = self._config.base_url + path
        headers = self._build_headers()
        headers.update(kwargs.pop("headers", {}))

        response = self._session.request(
            method, url, headers=headers, timeout=30, **kwargs
        )

        if response.status_code == 401:
            raise AuthError(
                "Session expired. Run `vanjaro auth login` to re-authenticate."
            )

        self._raise_for_status(response)
        return response

    def _ensure_antiforgery(self) -> None:
        """Fetch the anti-forgery token from the site if we don't have one yet.

        Makes a single GET to the homepage (with auth cookies) which gives us:
        1. The __RequestVerificationToken cookie (captured by self._session)
        2. The token value from a hidden form field in the HTML
        """
        if self._verification_token is not None:
            return

        url = self._config.base_url + "/"
        try:
            response = self._session.get(url, timeout=15)
        except requests.RequestException:
            self._verification_token = ""
            return

        match = _ANTIFORGERY_RE.search(response.text)
        self._verification_token = match.group(1) if match else ""

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._verification_token:
            headers["RequestVerificationToken"] = self._verification_token
        if self._config.api_key:
            headers["X-Api-Key"] = self._config.api_key
        return headers

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.ok:
            return

        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type:
            raise ApiError(
                f"HTTP {response.status_code}: Server returned an HTML error page. "
                "The API endpoint may not exist on this DNN/Vanjaro installation.",
                status_code=response.status_code,
            )

        try:
            detail = response.json()
            message = (
                detail.get("Message")
                or detail.get("message")
                or detail.get("ExceptionMessage")
                or response.text
            )
        except (json.JSONDecodeError, ValueError):
            message = response.text or response.reason

        raise ApiError(
            f"HTTP {response.status_code}: {message}", status_code=response.status_code
        )


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code
