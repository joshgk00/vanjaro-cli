"""Scoped, deterministic scanning for high-confidence secret disclosures."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json
from vanjaro_cli.reliability.contracts import SECRET_SCAN_SCHEMA


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:access[_-]?token|api[_-]?key|authorization|cookie|credentials?|jwt|passwd|password|private[_-]?key|secret|signature|token)(?:$|[_-])",
    re.IGNORECASE,
)
_SENSITIVE_QUERY_KEY = re.compile(
    r"(?:^|[_-])(?:access[_-]?token|api[_-]?key|auth|authorization|code|credential|jwt|password|secret|signature|sig|token)(?:$|[_-])",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(
    r"(?im)^\s*authorization\s*[:=]\s*(?:bearer|basic)\s+\S+"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
_URL = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_TEXT_SUFFIXES = {".css", ".html", ".log", ".md", ".txt", ".yaml", ".yml"}
_JSON_SUFFIXES = {".json"}
_FORBIDDEN_NAMES = {".env", "config.json"}


class _ScanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScannedFile(_ScanModel):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SecretFinding(_ScanModel):
    rule_id: Literal[
        "authorization-value",
        "private-key-header",
        "sensitive-json-key",
        "sensitive-url-query",
        "sensitive-url-fragment",
        "url-userinfo",
    ]
    path: str
    location: str
    kind: Literal["json", "text"]


class SecretScanError(_ScanModel):
    path: str
    code: Literal[
        "forbidden-scope",
        "invalid-json",
        "path-escape",
        "symlink",
        "unreadable",
        "unsupported-media-type",
    ]


class SecretScanReport(_ScanModel):
    schema_version: Literal["secret-scan-v1"] = SECRET_SCAN_SCHEMA
    status: Literal["passed", "failed"]
    scanned_file_count: int = Field(ge=0)
    files: tuple[ScannedFile, ...]
    findings: tuple[SecretFinding, ...]
    errors: tuple[SecretScanError, ...]


def scan_declared_files(root: Path, relative_paths: list[str] | tuple[str, ...]) -> SecretScanReport:
    """Scan exactly the declared release files without walking credential roots."""

    root = root.expanduser().resolve()
    findings: list[SecretFinding] = []
    errors: list[SecretScanError] = []
    files: list[ScannedFile] = []
    normalized_paths: set[str] = set()

    for requested in sorted(relative_paths):
        normalized = requested.replace("\\", "/")
        if (
            not normalized
            or normalized.startswith("/")
            or re.match(r"^[A-Za-z]:/", normalized)
            or ".." in Path(normalized).parts
        ):
            errors.append(SecretScanError(path=normalized, code="path-escape"))
            continue
        if normalized in normalized_paths:
            continue
        normalized_paths.add(normalized)
        unresolved = root / normalized
        if _contains_link_or_reparse(root, unresolved):
            errors.append(SecretScanError(path=normalized, code="symlink"))
            continue
        path = (root / normalized).resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            errors.append(SecretScanError(path=normalized, code="path-escape"))
            continue
        if _is_forbidden_scope(relative):
            errors.append(SecretScanError(path=relative, code="forbidden-scope"))
            continue
        suffix = path.suffix.casefold()
        if suffix not in _JSON_SUFFIXES | _TEXT_SUFFIXES:
            errors.append(SecretScanError(path=relative, code="unsupported-media-type"))
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError):
            errors.append(SecretScanError(path=relative, code="unreadable"))
            continue
        files.append(
            ScannedFile(path=relative, sha256=hashlib.sha256(raw).hexdigest())
        )
        if suffix in _JSON_SUFFIXES:
            try:
                payload = load_strict_json(path)
            except ArtifactContractError:
                errors.append(SecretScanError(path=relative, code="invalid-json"))
                continue
            _scan_json(payload, path=relative, pointer="$", findings=findings)
        else:
            _scan_text(text, path=relative, findings=findings)

    ordered_files = tuple(sorted(files, key=lambda item: item.path))
    ordered_findings = tuple(
        sorted(findings, key=lambda item: (item.path, item.location, item.rule_id))
    )
    ordered_errors = tuple(sorted(errors, key=lambda item: (item.path, item.code)))
    return SecretScanReport(
        status="failed" if ordered_findings or ordered_errors else "passed",
        scanned_file_count=len(ordered_files),
        files=ordered_files,
        findings=ordered_findings,
        errors=ordered_errors,
    )


def _scan_json(
    value: object,
    *,
    path: str,
    pointer: str,
    findings: list[SecretFinding],
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            child_pointer = f"{pointer}/{escaped}"
            if _SENSITIVE_KEY.search(str(key)) and child not in (None, "", False, [], {}):
                findings.append(
                    SecretFinding(
                        rule_id="sensitive-json-key",
                        path=path,
                        location=child_pointer,
                        kind="json",
                    )
                )
            _scan_json(child, path=path, pointer=child_pointer, findings=findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_json(
                child,
                path=path,
                pointer=f"{pointer}/{index}",
                findings=findings,
            )
    elif isinstance(value, str):
        _scan_string(value, path=path, location=pointer, kind="json", findings=findings)


def _scan_text(text: str, *, path: str, findings: list[SecretFinding]) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        location = f"line:{line_number}"
        if _AUTHORIZATION.search(line):
            findings.append(
                SecretFinding(
                    rule_id="authorization-value",
                    path=path,
                    location=location,
                    kind="text",
                )
            )
        if _PRIVATE_KEY.search(line):
            findings.append(
                SecretFinding(
                    rule_id="private-key-header",
                    path=path,
                    location=location,
                    kind="text",
                )
            )
        _scan_string(line, path=path, location=location, kind="text", findings=findings)


def _scan_string(
    value: str,
    *,
    path: str,
    location: str,
    kind: Literal["json", "text"],
    findings: list[SecretFinding],
) -> None:
    for match in _URL.finditer(value):
        try:
            parsed = urlsplit(match.group(0))
        except ValueError:
            continue
        if parsed.username or parsed.password:
            findings.append(
                SecretFinding(
                    rule_id="url-userinfo",
                    path=path,
                    location=location,
                    kind=kind,
                )
            )
        if any(_SENSITIVE_QUERY_KEY.search(key) for key, _ in parse_qsl(parsed.query)):
            findings.append(
                SecretFinding(
                    rule_id="sensitive-url-query",
                    path=path,
                    location=location,
                    kind=kind,
                )
            )
        if parsed.fragment and any(
            _SENSITIVE_QUERY_KEY.search(key)
            for key, _ in parse_qsl(parsed.fragment, keep_blank_values=True)
        ):
            findings.append(
                SecretFinding(
                    rule_id="sensitive-url-fragment",
                    path=path,
                    location=location,
                    kind=kind,
                )
            )


def _is_forbidden_scope(relative: str) -> bool:
    parts = tuple(part.casefold() for part in Path(relative).parts)
    name = parts[-1] if parts else ""
    return (
        name in _FORBIDDEN_NAMES
        or name.startswith(".env")
        or "credentials" in parts
        or "profiles" in parts
        or "sources" in parts
    )


def _contains_link_or_reparse(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError:
            return False
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (reparse_flag and attributes & reparse_flag):
            return True
    return False


__all__ = [
    "ScannedFile",
    "SecretFinding",
    "SecretScanError",
    "SecretScanReport",
    "scan_declared_files",
]
