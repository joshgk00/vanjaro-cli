"""Immutable, explicit source-reference contracts for agency capture planning.

These objects are pure data: constructing one validates its own shape (page
ownership, http(s) URL form, positive-integer dimensions, a real sha256) but
never touches a filesystem or the network. Read-only local file validation
and plan assembly live in
``vanjaro_cli.orchestration.project_capture_plan``, which is the only place
that is allowed to open a file these references point at.

`LiveReference` and `StaticReference` are deliberately distinct types rather
than one flexible record: a live reference is an http(s) render at an
explicit viewport, while a static reference is already-acquired bytes (an
image export or a Figma frame export) identified by a file hash, with its
canvas dimensions, its declared viewport, and an explicit statement of
whether the canvas *is* that viewport or is a full scrolled page. Nothing
here ever derives one of those from another by resizing or inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from urllib.parse import urlsplit

from vanjaro_cli.design.models import BreakpointName

__all__ = [
    "CanvasInterpretation",
    "InvalidReferenceError",
    "LiveReference",
    "SourceReference",
    "StaticReference",
    "StaticSourceKind",
]

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_DRIVE_PATH = re.compile(r"^[A-Za-z]:/")


class InvalidReferenceError(ValueError):
    """Raised by a reference contract's own construction-time validation."""


class CanvasInterpretation(str, Enum):
    """Whether a static capture's canvas is one viewport frame or a full page.

    Required on every `StaticReference`, with no default: a full-page
    (scrolled) capture and a single-viewport capture are never conflated,
    and this module never infers one from the other by resizing.
    """

    VIEWPORT = "viewport"
    FULL_PAGE = "full_page"


class StaticSourceKind(str, Enum):
    """Which acquisition path produced a static reference's bytes."""

    IMAGE = "image"
    FIGMA = "figma"


def _require_page_id(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidReferenceError(f"page_id must be a string, not {value!r}")
    normalized = value.strip()
    if not normalized:
        raise InvalidReferenceError("page_id must not be empty")
    return normalized


def _require_breakpoint(value: object) -> BreakpointName:
    if not isinstance(value, BreakpointName):
        raise InvalidReferenceError(f"breakpoint must be a BreakpointName, not {value!r}")
    return value


def _require_positive_int(value: object, label: str) -> int:
    # bool is a subclass of int in Python; reject it explicitly so a stray
    # `True`/`False` can never pass itself off as width/height 1/0.
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidReferenceError(f"{label} must be a positive int, not {value!r}")
    if value <= 0:
        raise InvalidReferenceError(f"{label} must be positive, not {value!r}")
    return value


def _require_sha256(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidReferenceError(f"sha256 must be a string, not {value!r}")
    normalized = value.strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise InvalidReferenceError(f"sha256 must be a lowercase 64-hex digest, not {value!r}")
    return normalized


def _require_live_url(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidReferenceError(f"url must be a string, not {value!r}")
    normalized = value.strip()
    try:
        parsed = urlsplit(normalized)
        parsed.port
    except ValueError as error:
        # Never echo `normalized` here: a URL that fails validation can carry
        # embedded userinfo, and the parser error text itself never does.
        raise InvalidReferenceError(f"live reference url could not be parsed: {error}") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        # Deliberately excludes `normalized`/`value`: a rejected URL is the
        # one most likely to carry embedded credentials, and this diagnostic
        # must stay credential-safe even when the caller logs it verbatim.
        raise InvalidReferenceError(
            "live reference url must be a plain http(s) URL with no embedded credentials"
        )
    return normalized


def _require_workspace_relative_path(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise InvalidReferenceError(f"{label} must be a string, not {value!r}")
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        raise InvalidReferenceError(f"{label} must not be empty")
    if normalized.startswith("/") or _DRIVE_PATH.match(normalized):
        raise InvalidReferenceError(f"{label} must be workspace-relative, not {value!r}")
    if ".." in normalized.split("/"):
        raise InvalidReferenceError(f"{label} must not contain '..': {value!r}")
    return normalized


@dataclass(frozen=True, slots=True)
class LiveReference:
    """An explicit http(s) live render bound to one page and breakpoint."""

    page_id: str
    breakpoint: BreakpointName
    url: str
    viewport_width: int
    viewport_height: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "page_id", _require_page_id(self.page_id))
        object.__setattr__(self, "breakpoint", _require_breakpoint(self.breakpoint))
        object.__setattr__(self, "url", _require_live_url(self.url))
        object.__setattr__(
            self, "viewport_width", _require_positive_int(self.viewport_width, "viewport_width")
        )
        object.__setattr__(
            self, "viewport_height", _require_positive_int(self.viewport_height, "viewport_height")
        )


@dataclass(frozen=True, slots=True)
class StaticReference:
    """An already-acquired static export bound to one page and breakpoint.

    `sha256` and `local_path` identify the exact acquired bytes on disk
    (workspace-relative; containment and currency are checked read-only by
    the planning layer, not here). `canvas_width`/`canvas_height` are the
    artifact's actual pixel dimensions; `viewport_width`/`viewport_height`
    are the breakpoint this artifact is declared to represent -- the two
    stay distinct even when equal. `interpretation` states explicitly
    whether the canvas is one viewport frame or a full scrolled page.
    Figma exports additionally carry `file_key` (source design identity)
    and `frame_node_id` (frame identity), each distinct from the file hash;
    image exports must not carry either.
    """

    page_id: str
    breakpoint: BreakpointName
    source_kind: StaticSourceKind
    local_path: str
    sha256: str
    canvas_width: int
    canvas_height: int
    viewport_width: int
    viewport_height: int
    interpretation: CanvasInterpretation
    file_key: str | None = None
    frame_node_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "page_id", _require_page_id(self.page_id))
        object.__setattr__(self, "breakpoint", _require_breakpoint(self.breakpoint))
        if not isinstance(self.source_kind, StaticSourceKind):
            raise InvalidReferenceError(
                f"source_kind must be a StaticSourceKind, not {self.source_kind!r}"
            )
        object.__setattr__(
            self, "local_path", _require_workspace_relative_path(self.local_path, "local_path")
        )
        object.__setattr__(self, "sha256", _require_sha256(self.sha256))
        object.__setattr__(
            self, "canvas_width", _require_positive_int(self.canvas_width, "canvas_width")
        )
        object.__setattr__(
            self, "canvas_height", _require_positive_int(self.canvas_height, "canvas_height")
        )
        object.__setattr__(
            self, "viewport_width", _require_positive_int(self.viewport_width, "viewport_width")
        )
        object.__setattr__(
            self, "viewport_height", _require_positive_int(self.viewport_height, "viewport_height")
        )
        if not isinstance(self.interpretation, CanvasInterpretation):
            raise InvalidReferenceError(
                f"interpretation must be an explicit CanvasInterpretation, not {self.interpretation!r}"
            )
        if self.source_kind == StaticSourceKind.FIGMA:
            if not isinstance(self.file_key, str) or not self.file_key.strip():
                raise InvalidReferenceError("figma static references require a non-empty file_key")
            if not isinstance(self.frame_node_id, str) or not self.frame_node_id.strip():
                raise InvalidReferenceError(
                    "figma static references require a non-empty frame_node_id"
                )
            object.__setattr__(self, "file_key", self.file_key.strip())
            object.__setattr__(self, "frame_node_id", self.frame_node_id.strip())
        else:
            if self.file_key is not None or self.frame_node_id is not None:
                raise InvalidReferenceError(
                    "image static references must not carry Figma frame/source-design identity"
                )


SourceReference = LiveReference | StaticReference
