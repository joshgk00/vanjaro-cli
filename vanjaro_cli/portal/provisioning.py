"""Pure, credential-free planning helpers for safe portal provisioning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import html
import json
import re
from typing import Any
import unicodedata
from urllib.parse import unquote, urlsplit, urlunsplit

BLANK_TEMPLATE = "Blank Website.template|en-US|/"
MAX_WARNING_LENGTH = 500
MAX_WARNINGS = 10
MAX_URL_DECODE_PASSES = 8

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROFILE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")
_SENSITIVE_LABEL = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|cookie|password|secret|token)\b"
)
_REDACTED_WARNING = "Server warning contained redacted sensitive data."


class PlanError(ValueError):
    """A portal plan cannot safely be constructed."""


def _safe_text(value: str, label: str, *, required: bool, maximum: int) -> str:
    if not isinstance(value, str):
        raise PlanError(f"{label} must be text.")
    value = value.strip()
    if required and not value:
        raise PlanError(f"{label} must not be empty.")
    if len(value) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PlanError(f"{label} contains unsafe characters or is too long.")
    return value


def normalize_base_url(value: str) -> str:
    """Validate and normalize an HTTP(S) base URL without discarding its path."""
    value = _safe_text(value, "Base URL", required=True, maximum=2048)
    if "\\" in value or any(char.isspace() for char in value):
        raise PlanError("Base URL contains unsafe whitespace or a backslash.")
    try:
        parsed = urlsplit(value)
        port = parsed.port  # Forces malformed/out-of-range port validation.
    except ValueError as exc:
        raise PlanError("Base URL has a malformed host or port.") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise PlanError("Base URL must use http or https.")
    if not parsed.hostname:
        raise PlanError("Base URL must include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise PlanError("Base URL must not contain user information.")
    if parsed.query or parsed.fragment:
        raise PlanError("Base URL must not contain a query or fragment.")
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname + (f":{port}" if port is not None else "")
    path = parsed.path.rstrip("/")
    candidate = path
    for _ in range(MAX_URL_DECODE_PASSES):
        lowered = candidate.lower()
        decoded = unquote(candidate)
        if (
            "%2f" in lowered
            or "%5c" in lowered
            or "\\" in decoded
            or "//" in decoded
            or any(char.isspace() for char in decoded)
            or any(unicodedata.category(char).startswith("C") for char in decoded)
            or any(segment in {".", ".."} for segment in decoded.split("/"))
        ):
            raise PlanError("Base URL contains an unsafe path.")
        if decoded == candidate:
            break
        candidate = decoded
    else:
        raise PlanError("Base URL contains excessive recursive encoding.")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def normalize_alias(value: str) -> str:
    """Normalize a scheme-free DNN SiteAlias for exact comparisons."""
    value = _SPACE.sub("", str(value or "")).strip().strip("/").lower()
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class CreationPlan:
    authority: str
    template: str
    payload: tuple[tuple[str, Any], ...]
    alias: str
    child_base_url: str
    target_profile: str | None
    write_profile: bool
    replace_profile: bool

    def payload_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    def canonical_data(self) -> dict[str, Any]:
        data = asdict(self)
        data["payload"] = self.payload_dict()
        return data

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.canonical_data()).encode("utf-8")).hexdigest()

    def preview(self) -> dict[str, Any]:
        return {
            "status": "preview",
            "portal_contacted": False,
            "profile_written": False,
            "required_authority": self.authority,
            "template": self.template,
            "payload": self.payload_dict(),
            "alias": self.alias,
            "child_base_url": self.child_base_url,
            "target_profile": self.target_profile,
            "replace_profile": self.replace_profile,
            "plan_fingerprint": self.fingerprint,
        }


def build_creation_plan(
    base_url: str,
    *,
    name: str,
    slug: str,
    description: str = "",
    profile_name: str | None = None,
    no_profile: bool = False,
    replace_profile: bool = False,
) -> CreationPlan:
    base = normalize_base_url(base_url)
    name = _safe_text(name, "Name", required=True, maximum=200)
    description = _safe_text(description, "Description", required=False, maximum=500)
    if not _SLUG.fullmatch(slug or ""):
        raise PlanError("Slug must be lowercase letters, digits, and single hyphens.")
    if no_profile and profile_name is not None:
        raise PlanError("--profile-name cannot be used with --no-profile.")
    if no_profile and replace_profile:
        raise PlanError("--replace-profile cannot be used with --no-profile.")
    target = None if no_profile else (profile_name or slug)
    if target is not None and not _PROFILE.fullmatch(target):
        raise PlanError("Profile name contains unsafe characters.")
    parts = urlsplit(base)
    child_path = f"{parts.path.rstrip('/')}/{slug}"
    child = urlunsplit((parts.scheme, parts.netloc, child_path, "", ""))
    alias = normalize_alias(f"{parts.netloc}{child_path}")
    payload = {
        "SiteTemplate": BLANK_TEMPLATE,
        "SiteName": name,
        "SiteAlias": alias,
        "SiteDescription": description,
        "SiteKeywords": "",
        "IsChildSite": True,
        "HomeDirectory": "",
        "UseCurrentUserAsAdmin": True,
    }
    return CreationPlan(
        authority="Host/SuperUser",
        template=BLANK_TEMPLATE,
        payload=tuple(payload.items()),
        alias=alias,
        child_base_url=child,
        target_profile=target,
        write_profile=not no_profile,
        replace_profile=replace_profile,
    )


def normalize_warnings(value: Any) -> list[str]:
    """Normalize DNN's null/string/list warning shapes into sanitized strings."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    warnings: list[str] = []
    for item in items[:MAX_WARNINGS]:
        if item is None:
            continue
        text = html.unescape(_TAG.sub(" ", str(item)))
        text = "".join(
            " " if unicodedata.category(char).startswith("C") else char
            for char in text
        )
        if _SENSITIVE_LABEL.search(text):
            text = _REDACTED_WARNING
        text = _SPACE.sub(" ", text).strip()
        if text:
            warnings.append(text[:MAX_WARNING_LENGTH])
    return warnings


def normalize_portals(value: Any) -> list[dict[str, Any]]:
    """Validate and deterministically sort a DNN portal-list response."""
    if not isinstance(value, list):
        raise PlanError("Portal results must be a list.")
    portals: list[dict[str, Any]] = []
    portal_ids: set[int] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise PlanError("Portal results contain a non-object entry.")
        item = dict(raw)
        portal_id = item.get("PortalID")
        if isinstance(portal_id, bool):
            raise PlanError("Portal results contain an invalid portal ID.")
        try:
            item["PortalID"] = int(portal_id)
        except (TypeError, ValueError) as exc:
            raise PlanError("Portal results contain an invalid portal ID.") from exc
        if item["PortalID"] < 0 or item["PortalID"] in portal_ids:
            raise PlanError("Portal results contain a duplicate or invalid portal ID.")
        portal_ids.add(item["PortalID"])
        raw_aliases = item.get("PortalAliases", [])
        if not isinstance(raw_aliases, list):
            raise PlanError("Portal results contain invalid aliases.")
        aliases: list[dict[str, Any]] = []
        for alias in raw_aliases:
            if not isinstance(alias, dict) or not isinstance(alias.get("url"), str):
                raise PlanError("Portal results contain an invalid alias.")
            aliases.append(dict(alias))
        aliases.sort(key=lambda alias: normalize_alias(alias.get("url", "")))
        item["PortalAliases"] = aliases
        portals.append(item)
    portals.sort(key=lambda item: item["PortalID"])
    return portals
