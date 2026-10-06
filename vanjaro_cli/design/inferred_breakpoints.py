"""Which tablet/mobile layouts a static design never drew.

Same rule as the fidelity gate's `not_declared_breakpoints`
(`project_fidelity._is_declared_static_only`): a Figma or image source only
carries the frames its author drew, so a canonical breakpoint with no frame is
inferred, not missing evidence an operator can supply. Live HTML pages are
never listed: every breakpoint can be rendered, so a gap there is a real
capture failure and keeps its existing handling.
"""

from __future__ import annotations

from vanjaro_cli.design.models import BreakpointName, DesignDocument, Page, SourceKind

INFERRED_BREAKPOINTS_NOTE = (
    "Tablet and mobile layouts are inferred from the desktop design, not designed. "
    "They are not missing evidence the operator can fix."
)

_CANONICAL_ORDER = (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)
_STATIC_KINDS = frozenset({SourceKind.FIGMA, SourceKind.IMAGE})


def _is_static_page(page: Page) -> bool:
    return bool(page.provenance) and all(
        item.source_kind in _STATIC_KINDS for item in page.provenance
    )


def inferred_breakpoints_by_page(document: DesignDocument) -> dict[str, list[str]]:
    """Map page id to the canonical breakpoints its static source did not declare."""

    inferred: dict[str, list[str]] = {}
    for page in document.pages:
        if not _is_static_page(page):
            continue
        undeclared = [
            breakpoint.value
            for breakpoint in _CANONICAL_ORDER
            if breakpoint not in page.breakpoints
        ]
        if undeclared:
            inferred[page.id] = undeclared
    return inferred
