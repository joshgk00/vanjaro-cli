"""Small dependency-free Semantic Version 2.0 parser and comparator."""

from __future__ import annotations

import re


_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def validate_semver(value: str) -> str:
    normalized = value.strip()
    if not _SEMVER.fullmatch(normalized):
        raise ValueError(f"version must use Semantic Versioning 2.0: {value!r}")
    return normalized


def compare_semver(left: str, right: str) -> int:
    """Return -1, 0, or 1 using SemVer precedence rules."""

    left_parts = _parts(validate_semver(left))
    right_parts = _parts(validate_semver(right))
    if left_parts[:3] != right_parts[:3]:
        return -1 if left_parts[:3] < right_parts[:3] else 1
    left_pre = left_parts[3]
    right_pre = right_parts[3]
    if left_pre == right_pre:
        return 0
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    for left_id, right_id in zip(left_pre, right_pre):
        if left_id == right_id:
            continue
        left_numeric = left_id.isdigit()
        right_numeric = right_id.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_id) < int(right_id) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_id < right_id else 1
    return -1 if len(left_pre) < len(right_pre) else 1


def _parts(value: str) -> tuple[int, int, int, tuple[str, ...]]:
    match = _SEMVER.fullmatch(value)
    assert match is not None
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease


__all__ = ["compare_semver", "validate_semver"]
