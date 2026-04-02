"""HTTP client wrapper — handles auth headers, CSRF tokens, and error surfacing."""

from __future__ import annotations

from typing import Any, Optional

import requests

from vanjaro_cli.auth import AuthError, is_token_expired, reissue_token
from vanjaro_cli.config import Config, ConfigError

# DNN PersonaBar calls require this anti-forgery token in the header.
# We retrieve it once per session from the antiforgery endpoint.
ANTIFORGERY_PATH = "/API/PersonaBar/Security/GetAntiForgeryToken"


class VanjaroClient:
    """Thin wrapper around requests that injects auth and CSRF headers."""

    def __init__(self, config: Config):
        self._config = config
        self._session = requests.Session()
        self._csrf_token: Optional[str] = None

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
        self._ensure_token()
        url = self._config.base_url + path
        headers = self._build_headers(method)
        headers.update(kwargs.pop("headers", {}))

        response = self._session.request(
            method, url, headers=headers, timeout=30, **kwargs
        )

        if response.status_code == 401:
            # Try one token refresh before giving up
            try:
                self._config = reissue_token(self._config)
                headers = self._build_headers(method)
                response = self._session.request(
                    method, url, headers=headers, timeout=30, **kwargs
                )
            except AuthError:
                raise AuthError(
                    "Authentication failed. Run `vanjaro auth login` to re-authenticate."
                )

        self._raise_for_status(response)
        return response

    def _ensure_token(self) -> None:
        if not self._config.token:
            raise ConfigError(
                "Not authenticated. Run `vanjaro auth login` first."
            )
        if is_token_expired(self._config.token):
            try:
                self._config = reissue_token(self._config)
            except AuthError:
                raise AuthError(
                    "Session expired. Run `vanjaro auth login` to re-authenticate."
                )

    def _fetch_csrf_token(self) -> str:
        url = self._config.base_url + ANTIFORGERY_PATH
        response = self._session.get(
            url,
            headers={"Authorization": f"Bearer {self._config.token}"},
            timeout=10,
        )
        if not response.ok:
            return ""
        data = response.json()
        return data.get("token", data.get("Token", ""))

    def _build_headers(self, method: str) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"

        # PersonaBar mutating requests need CSRF
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            if self._csrf_token is None:
                self._csrf_token = self._fetch_csrf_token()
            if self._csrf_token:
                headers["RequestVerificationToken"] = self._csrf_token

        return headers

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            detail = response.json()
            message = (
                detail.get("Message")
                or detail.get("message")
                or detail.get("ExceptionMessage")
                or response.text
            )
        except Exception:
            message = response.text or response.reason

        raise ApiError(
            f"HTTP {response.status_code}: {message}", status_code=response.status_code
        )


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code
