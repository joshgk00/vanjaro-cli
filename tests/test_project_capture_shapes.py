"""Regression: malformed `breakpoint` shapes must not crash `_validate_capture_entry`.

`entry.get("breakpoint")` is checked for membership in `_CANONICAL_BREAKPOINTS`
(a frozenset of strings) before its type is validated. An unhashable JSON
value (a list or dict) raises `TypeError` on that membership check instead of
producing the intended diagnostic. This must return the same
unknown-breakpoint diagnostic for every malformed shape, and canonical
breakpoints must still validate exactly as before.
"""
from pathlib import Path

import pytest

from vanjaro_cli.orchestration.project_capture_evidence import _validate_capture_entry


@pytest.mark.parametrize("value", [[], {}, None, True, 12, "unknown"])
def test_malformed_breakpoint_yields_diagnostic_not_exception(value):
    breakpoint, issues = _validate_capture_entry(
        Path("."), "home", {"breakpoint": value}, set()
    )
    assert breakpoint is None
    assert issues == [
        f"page 'home': capture entry has an unknown breakpoint {value!r}"
    ]


@pytest.mark.parametrize("value", ["desktop", "tablet", "mobile"])
def test_canonical_breakpoint_still_passes_the_membership_check(value):
    # Missing flags/paths still reject the entry, but never with the
    # unknown-breakpoint diagnostic: canonical names must clear the
    # membership check unchanged.
    breakpoint, issues = _validate_capture_entry(
        Path("."), "home", {"breakpoint": value}, set()
    )
    assert breakpoint is None
    assert all("unknown breakpoint" not in issue for issue in issues)
    assert issues
