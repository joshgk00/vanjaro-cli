"""Versioned, redacted diagnostics for automation-facing commands."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from vanjaro_cli.reliability.contracts import DIAGNOSTIC_SCHEMA


_SENSITIVE_QUERY_KEY = re.compile(
    r"(?:^|[_-])(?:access[_-]?token|api[_-]?key|auth|authorization|code|credential|jwt|password|secret|signature|sig|token)(?:$|[_-])",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_AUTHORIZATION = re.compile(
    r"(?im)(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+"
)
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:\\)[^\r\n\"']+")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9.])/(?:home|Users|mnt|tmp|var)/[^\s\"']+")


class _DiagnosticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiagnosticContext(_DiagnosticModel):
    artifact_path: str | None = None
    gate_id: str | None = None
    rule_id: str | None = None
    case_id: str | None = None
    metric: str | None = None
    source_kind: str | None = None

    @field_validator("artifact_path")
    @classmethod
    def require_relative_artifact_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
            raise ValueError("diagnostic artifact_path must be relative")
        if ".." in normalized.split("/"):
            raise ValueError("diagnostic artifact_path must not escape its root")
        return normalized


class Diagnostic(_DiagnosticModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    category: Literal[
        "configuration",
        "contract",
        "evidence",
        "integrity",
        "performance",
        "security",
        "unsupported",
    ]
    message: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    stage: str | None = None
    retryable: bool = False
    context: DiagnosticContext = Field(default_factory=DiagnosticContext)

    @field_validator("message", "recommended_action")
    @classmethod
    def redact_text(cls, value: str) -> str:
        return redact_diagnostic_text(value)


class DiagnosticEnvelope(_DiagnosticModel):
    schema_version: Literal["diagnostic-v1"] = DIAGNOSTIC_SCHEMA
    status: Literal["error"] = "error"
    diagnostic: Diagnostic


def build_diagnostic(
    *,
    code: str,
    category: str,
    message: str,
    recommended_action: str,
    stage: str | None = None,
    retryable: bool = False,
    context: DiagnosticContext | None = None,
) -> DiagnosticEnvelope:
    """Build a strict diagnostic envelope and redact its human-safe strings."""

    return DiagnosticEnvelope(
        diagnostic=Diagnostic(
            code=code,
            category=category,
            message=message,
            recommended_action=recommended_action,
            stage=stage,
            retryable=retryable,
            context=context or DiagnosticContext(),
        )
    )


def redact_diagnostic_text(value: str) -> str:
    """Remove structural credentials and machine-local absolute paths."""

    sanitized = _AUTHORIZATION.sub(r"\1[REDACTED]", value)
    sanitized = _URL.sub(lambda match: _redact_url(match.group(0)), sanitized)
    sanitized = _WINDOWS_PATH.sub("[LOCAL_PATH]", sanitized)
    sanitized = _POSIX_PATH.sub("[LOCAL_PATH]", sanitized)
    return sanitized


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return "[REDACTED_URL]"
    hostname = parsed.hostname or ""
    if not hostname:
        return "[REDACTED_URL]"
    netloc = hostname + port
    query = urlencode(
        [
            (key, "[REDACTED]" if _SENSITIVE_QUERY_KEY.search(key) else item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    fragment = "[REDACTED]" if parsed.fragment else ""
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment))


__all__ = [
    "Diagnostic",
    "DiagnosticContext",
    "DiagnosticEnvelope",
    "build_diagnostic",
    "redact_diagnostic_text",
]
