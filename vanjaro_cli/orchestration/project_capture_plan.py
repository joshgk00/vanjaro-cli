"""Pure per-page/breakpoint capture planning: metadata first, then read-only local checks.

`plan_project_capture` is the foundation the future `project capture` command
plans against before anything is rendered, downloaded, or written. It never
loads credentials, contacts a portal, launches a browser, or acquires bytes
over the network -- the only I/O it performs is reading local files that an
explicit or document-derived static reference already points at, purely to
verify they are still the bytes they claim to be.

Two concerns are kept apart on purpose:

- Pure metadata resolution (`_live_reference_from_document`,
  `_static_reference_from_image_metadata`, `_index_explicit_references`)
  never touches a filesystem. It only reads the already-parsed
  `DesignDocument` and the caller-supplied `references`.
- Read-only local file validation (`_validate_static_reference`) is the only
  place that opens a file, and it never writes one. It reuses
  `resolve_workspace_file` for containment-after-symlink-resolution and
  `image_identity` for dimension parsing, so this module never carries a
  second implementation of either.

A page's three breakpoints (desktop/tablet/mobile) are always enumerated,
regardless of what any single source declares -- a static source can leave a
breakpoint `reference_not_declared`, but it can never shrink the
three-breakpoint denominator the plan reports. Figma sources are never used
to fabricate an export path: only an explicit, already-acquired
`StaticReference` can fill a Figma breakpoint slot.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from vanjaro_cli.design.capture_references import (
    CanvasInterpretation,
    InvalidReferenceError,
    LiveReference,
    SourceReference,
    StaticReference,
    StaticSourceKind,
)
from vanjaro_cli.design.models import (
    BreakpointName,
    DesignDocument,
    EvidenceStatus,
    ObservationMethod,
    Page,
    SourceKind,
)
from vanjaro_cli.design.quality_counts import resolve_page_identity
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS
from vanjaro_cli.orchestration.image_acquisition import (
    ImageAcquisitionError,
    image_identity,
    resolve_workspace_file,
)

__all__ = [
    "REQUIRED_BREAKPOINTS",
    "BreakpointCapturePlan",
    "PageCapturePlan",
    "ProjectCapturePlan",
    "ReferenceStatus",
    "plan_project_capture",
]

REQUIRED_BREAKPOINTS: tuple[BreakpointName, ...] = (
    BreakpointName.DESKTOP,
    BreakpointName.TABLET,
    BreakpointName.MOBILE,
)


class ReferenceStatus(str, Enum):
    """Per-breakpoint planning outcome; capture/target/output outcomes are a later stage."""

    NOT_DECLARED = "reference_not_declared"
    VALID = "reference_valid"
    INVALID = "reference_invalid"


@dataclass(frozen=True, slots=True)
class BreakpointCapturePlan:
    """One page's plan for one of the three required breakpoints."""

    breakpoint: BreakpointName
    status: ReferenceStatus
    reference: SourceReference | None
    declared_viewport: tuple[int, int] | None
    is_canonical_viewport: bool
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PageCapturePlan:
    """A page's plan across exactly the three required breakpoints, in order."""

    page_id: str
    breakpoints: tuple[BreakpointCapturePlan, ...]


@dataclass(frozen=True, slots=True)
class ProjectCapturePlan:
    """The full, read-only capture plan for every page in the resolved document."""

    pages: tuple[PageCapturePlan, ...]
    diagnostics: tuple[str, ...] = field(default_factory=tuple)


def _live_reference_from_document(page: Page, breakpoint: BreakpointName) -> LiveReference | None:
    """Pure: a live reference only when the page's own URL provenance supports it."""

    if breakpoint not in page.breakpoints:
        return None
    url = page.source_reference
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    viewport = CANONICAL_VIEWPORTS[breakpoint]
    try:
        return LiveReference(
            page_id=page.id,
            breakpoint=breakpoint,
            url=url,
            viewport_width=viewport.width,
            viewport_height=viewport.height,
        )
    except InvalidReferenceError:
        return None


def _image_metadata_entries(document: DesignDocument) -> list[Mapping[str, object]]:
    """Pure: the exact per-image records `image_adapter.py` embeds in `source.metadata`."""

    images = document.source.metadata.get("images")
    if not isinstance(images, list):
        return []
    return [item for item in images if isinstance(item, Mapping)]


def _static_reference_from_image_metadata(
    page: Page, breakpoint: BreakpointName, entries: Sequence[Mapping[str, object]]
) -> tuple[StaticReference | None, list[str]]:
    """Pure: resolve image-adapter-produced evidence; never reads a file.

    Returns `(reference, diagnostics)`. Non-empty `diagnostics` with no
    `reference` means metadata *was* declared for this page/breakpoint but is
    ambiguous or malformed -- the caller must report `reference_invalid`,
    never silently fall back to `reference_not_declared`, and an ambiguous
    match must never be resolved by picking the first candidate.
    """

    page_slug = page.metadata.get("image_page_slug")
    if not isinstance(page_slug, str):
        return None, []

    matches = [
        entry
        for entry in entries
        if entry.get("page_slug") == page_slug and entry.get("breakpoint") == breakpoint.value
    ]
    if not matches:
        return None, []
    if len(matches) > 1:
        return None, [
            f"page {page.id!r} {breakpoint.value}: multiple image metadata candidates "
            "declared for the same page/breakpoint; rejected as ambiguous"
        ]

    entry = matches[0]
    viewport = entry.get("viewport")
    if not isinstance(viewport, Mapping):
        return None, [
            f"page {page.id!r} {breakpoint.value}: declared image metadata is missing a viewport"
        ]
    try:
        return (
            StaticReference(
                page_id=page.id,
                breakpoint=breakpoint,
                source_kind=StaticSourceKind.IMAGE,
                local_path=str(entry.get("path", "")),
                sha256=str(entry.get("sha256", "")),
                canvas_width=viewport.get("width"),
                canvas_height=viewport.get("height"),
                viewport_width=viewport.get("width"),
                viewport_height=viewport.get("height"),
                interpretation=CanvasInterpretation.VIEWPORT,
            ),
            [],
        )
    except InvalidReferenceError as error:
        return None, [
            f"page {page.id!r} {breakpoint.value}: declared image metadata is invalid: {error}"
        ]


def _index_explicit_references(
    page_ids: frozenset[str], references: Sequence[SourceReference]
) -> tuple[
    dict[tuple[str, BreakpointName], SourceReference],
    set[tuple[str, BreakpointName]],
    list[str],
]:
    """Pure: bind caller-supplied references to page/breakpoint slots.

    Unknown pages and conflicting (duplicate) ownership are rejected
    diagnostically -- never by raising -- so a caller passing several
    explicit references always gets a reportable plan back.
    """

    owned: dict[tuple[str, BreakpointName], SourceReference] = {}
    conflicts: set[tuple[str, BreakpointName]] = set()
    diagnostics: list[str] = []
    for reference in references:
        key = (reference.page_id, reference.breakpoint)
        if reference.page_id not in page_ids:
            diagnostics.append(
                f"explicit reference for unknown page {reference.page_id!r} at "
                f"{reference.breakpoint.value}; rejected"
            )
            continue
        if key in owned or key in conflicts:
            diagnostics.append(
                f"duplicate explicit reference ownership for page {reference.page_id!r} at "
                f"{reference.breakpoint.value}; rejected"
            )
            conflicts.add(key)
            owned.pop(key, None)
            continue
        owned[key] = reference
    return owned, conflicts, diagnostics


def _figma_observed_ownership(page: Page) -> dict[BreakpointName, set[tuple[str, str]]]:
    """Pure: the (file_key, frame_node_id) pairs actually observed per breakpoint.

    `page.provenance` and each section's own `provenance` record the page's
    base frame -- real ownership only when `method` is `ObservationMethod.API`,
    since a caller-mutated or otherwise-inferred base record is no more
    trustworthy than the adapter's fabricated responsive fallback. A
    section's `responsive` observation records a real paired frame only when
    its `status` is `EvidenceStatus.OBSERVED`; when the adapter has no real
    frame for a breakpoint it fabricates an `EvidenceStatus.INFERRED`
    observation that repeats the base frame's id, and that must never
    satisfy ownership here.
    """

    owned: dict[BreakpointName, set[tuple[str, str]]] = defaultdict(set)
    for provenance in page.provenance:
        if (
            provenance.source_kind == SourceKind.FIGMA
            and provenance.method == ObservationMethod.API
            and provenance.viewport is not None
            and provenance.file_key
            and provenance.frame_node_id
        ):
            owned[provenance.viewport].add((provenance.file_key, provenance.frame_node_id))
    for section in page.sections:
        for provenance in section.provenance:
            if (
                provenance.source_kind == SourceKind.FIGMA
                and provenance.method == ObservationMethod.API
                and provenance.viewport is not None
                and provenance.file_key
                and provenance.frame_node_id
            ):
                owned[provenance.viewport].add((provenance.file_key, provenance.frame_node_id))
        for observation in section.responsive:
            if observation.status != EvidenceStatus.OBSERVED:
                continue
            for provenance in observation.provenance:
                if provenance.source_kind == SourceKind.FIGMA:
                    if provenance.file_key and provenance.frame_node_id:
                        owned[observation.breakpoint].add(
                            (provenance.file_key, provenance.frame_node_id)
                        )
    return owned


def _validate_figma_ownership(page: Page, reference: StaticReference) -> list[str]:
    """Pure: reject a Figma export whose identity isn't backed by real ownership.

    Missing ownership -- an unrecognized file/frame, a frame real for a
    different breakpoint, or a breakpoint only ever inferred -- is always
    `reference_invalid`, never a silent acceptance.
    """

    owned = _figma_observed_ownership(page).get(reference.breakpoint, set())
    if (reference.file_key, reference.frame_node_id) in owned:
        return []
    return [
        f"page {reference.page_id!r} {reference.breakpoint.value}: figma reference "
        f"file_key={reference.file_key!r} frame_node_id={reference.frame_node_id!r} is not "
        "backed by an observed frame for this page/breakpoint"
    ]


def _figma_observed_frame_bounds(page: Page) -> dict[tuple[str, str], set[tuple[int, int]]]:
    """Pure: real (width, height) pairs directly observed per Figma frame.

    Only frame-level `page.provenance` entries qualify as evidence of a real
    frame's own dimensions -- a section's bounds are section-local (a hero
    section is routinely shorter than the frame it lives in) and a
    `ResponsiveObservation.viewport` is a fixed canonical default, not an
    observed measurement, so neither is read here.
    """

    bounds: dict[tuple[str, str], set[tuple[int, int]]] = defaultdict(set)
    for provenance in page.provenance:
        if (
            provenance.source_kind == SourceKind.FIGMA
            and provenance.method == ObservationMethod.API
            and provenance.file_key
            and provenance.frame_node_id
            and provenance.bounds is not None
        ):
            key = (provenance.file_key, provenance.frame_node_id)
            bounds[key].add((round(provenance.bounds.width), round(provenance.bounds.height)))
    return bounds


def _validate_figma_frame_dimensions(page: Page, reference: StaticReference) -> list[str]:
    """Pure: a Figma export's declared dimensions must match the real frame exactly.

    Exports are 1x evidence only: a scaled thumbnail is rejected rather than
    resized or inferred back to full scale. A frame with no recorded bounds,
    or with two directly-observed records that disagree, is always
    `reference_invalid` -- never guessed valid by picking one.
    """

    key = (reference.file_key, reference.frame_node_id)
    observed = _figma_observed_frame_bounds(page).get(key, set())
    if not observed:
        return [
            f"page {reference.page_id!r} {reference.breakpoint.value}: no observed frame "
            f"dimensions for figma frame_node_id={reference.frame_node_id!r}; rejected"
        ]
    if len(observed) > 1:
        return [
            f"page {reference.page_id!r} {reference.breakpoint.value}: conflicting observed "
            f"frame dimensions for figma frame_node_id={reference.frame_node_id!r}; rejected as "
            "ambiguous"
        ]
    frame_width, frame_height = next(iter(observed))
    declared = (
        (reference.viewport_width, reference.viewport_height)
        if reference.interpretation == CanvasInterpretation.VIEWPORT
        else (reference.canvas_width, reference.canvas_height)
    )
    if declared != (frame_width, frame_height):
        interpretation_name = reference.interpretation.name
        declared_label = "viewport" if reference.interpretation == CanvasInterpretation.VIEWPORT else "canvas"
        return [
            f"figma reference declares CanvasInterpretation.{interpretation_name} but "
            f"{declared_label} {declared[0]}x{declared[1]} does not equal the observed frame "
            f"dimensions {frame_width}x{frame_height}; exports are 1x evidence only, a scaled "
            "thumbnail is rejected rather than resized"
        ]
    return []


def _validate_canvas_interpretation(reference: StaticReference) -> list[str]:
    """Pure: a declared CanvasInterpretation must match the declared numbers.

    `VIEWPORT` means the canvas *is* the viewport frame: the dimensions must
    match exactly. `FULL_PAGE` means a scrolled capture at the same width but
    taller (or equal); this module never resizes to reconcile a mismatch, it
    only rejects one.
    """

    if reference.interpretation == CanvasInterpretation.VIEWPORT:
        if (reference.canvas_width, reference.canvas_height) != (
            reference.viewport_width,
            reference.viewport_height,
        ):
            return [
                "static reference declares CanvasInterpretation.VIEWPORT but canvas "
                f"{reference.canvas_width}x{reference.canvas_height} does not equal viewport "
                f"{reference.viewport_width}x{reference.viewport_height}"
            ]
        return []

    issues: list[str] = []
    if reference.canvas_width != reference.viewport_width:
        issues.append(
            "static reference declares CanvasInterpretation.FULL_PAGE but canvas width "
            f"{reference.canvas_width} does not equal viewport width {reference.viewport_width}"
        )
    if reference.canvas_height < reference.viewport_height:
        issues.append(
            "static reference declares CanvasInterpretation.FULL_PAGE but canvas height "
            f"{reference.canvas_height} is shorter than viewport height {reference.viewport_height}"
        )
    return issues


def _validate_static_reference(root: Path, reference: StaticReference) -> tuple[bool, list[str]]:
    """Read-only: containment-after-symlink-resolution, hash, and actual dimensions.

    Never writes. Rejects malformed, missing, changed, or escaping local
    files diagnostically instead of raising, so one bad reference never
    stops the rest of the plan from being reported.
    """

    try:
        absolute, _relative = resolve_workspace_file(
            root,
            reference.local_path,
            source_id=f"{reference.page_id}:{reference.breakpoint.value}",
            label="static_reference",
        )
    except ImageAcquisitionError as error:
        return False, [str(error)]
    try:
        payload = absolute.read_bytes()
    except OSError as error:
        return False, [f"static reference file unreadable: {error}"]

    issues: list[str] = []
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    if observed_sha256 != reference.sha256:
        issues.append(
            "static reference bytes changed since declaration: expected sha256 "
            f"{reference.sha256}, found {observed_sha256}"
        )
    try:
        _mime_type, width, height = image_identity(payload)
    except ValueError as error:
        issues.append(f"static reference is not a decodable PNG, JPEG, or WebP: {error}")
    else:
        if (width, height) != (reference.canvas_width, reference.canvas_height):
            issues.append(
                "static reference canvas dimensions changed since declaration: declared "
                f"{reference.canvas_width}x{reference.canvas_height}, actual {width}x{height}"
            )
    return (not issues), issues


def _resolve_reference_validity(
    root: Path, page: Page, reference: SourceReference
) -> tuple[ReferenceStatus, list[str]]:
    if isinstance(reference, LiveReference):
        return ReferenceStatus.VALID, []
    metadata_issues = _validate_canvas_interpretation(reference)
    if reference.source_kind == StaticSourceKind.FIGMA:
        metadata_issues = metadata_issues + _validate_figma_ownership(page, reference)
        metadata_issues = metadata_issues + _validate_figma_frame_dimensions(page, reference)
    file_valid, file_issues = _validate_static_reference(root, reference)
    valid = file_valid and not metadata_issues
    return (ReferenceStatus.VALID if valid else ReferenceStatus.INVALID), (
        metadata_issues + file_issues
    )


def plan_project_capture(
    root: Path,
    document: DesignDocument,
    *,
    references: Sequence[SourceReference] = (),
) -> ProjectCapturePlan:
    """Plan every page's three required breakpoints against real evidence only.

    `root` bounds the read-only local file checks for any static reference
    (explicit or document-derived) that carries a `local_path`; it is never
    written to. `document` supplies authoritative page identity
    (`resolve_page_identity`) and, for an image-sourced document, the
    image-adapter evidence embedded in `document.source.metadata`. `Figma`
    documents never synthesize an export: only an explicit `StaticReference`
    in `references` can fill a Figma breakpoint slot, and a missing one
    stays `reference_not_declared`.
    """

    root = Path(root)
    identity = resolve_page_identity(document)
    pages_by_id = {page.id: page for page in document.pages}
    image_entries = (
        _image_metadata_entries(document) if document.source.kind == SourceKind.IMAGE else []
    )

    owned, conflicts, project_diagnostics = _index_explicit_references(
        frozenset(identity.page_ids), references
    )

    page_plans: list[PageCapturePlan] = []
    for page_id in identity.page_ids:
        page = pages_by_id[page_id]
        breakpoint_plans: list[BreakpointCapturePlan] = []
        for breakpoint in REQUIRED_BREAKPOINTS:
            key = (page_id, breakpoint)
            reference: SourceReference | None = None
            diagnostics: list[str] = []

            if key in conflicts:
                status = ReferenceStatus.INVALID
                diagnostics = [
                    f"page {page_id!r} {breakpoint.value}: conflicting explicit reference "
                    "ownership; no reference used"
                ]
            elif key in owned:
                reference = owned[key]
                status, diagnostics = _resolve_reference_validity(root, page, reference)
            else:
                declared_invalid_diagnostics: list[str] = []
                if document.source.kind == SourceKind.LIVE_HTML:
                    reference = _live_reference_from_document(page, breakpoint)
                elif document.source.kind == SourceKind.IMAGE:
                    reference, declared_invalid_diagnostics = _static_reference_from_image_metadata(
                        page, breakpoint, image_entries
                    )
                # SourceKind.FIGMA (and anything else) never synthesizes a
                # reference here: only an explicit StaticReference can fill
                # the slot, so `reference` stays None and the breakpoint
                # reports reference_not_declared below.

                if reference is None:
                    if declared_invalid_diagnostics:
                        status = ReferenceStatus.INVALID
                        diagnostics = declared_invalid_diagnostics
                    else:
                        status = ReferenceStatus.NOT_DECLARED
                        diagnostics = [
                            f"page {page_id!r} {breakpoint.value}: no reference declared"
                        ]
                else:
                    status, diagnostics = _resolve_reference_validity(root, page, reference)

            declared_viewport = (
                (reference.viewport_width, reference.viewport_height)
                if reference is not None
                else None
            )
            canonical = CANONICAL_VIEWPORTS[breakpoint]
            is_canonical = declared_viewport == (canonical.width, canonical.height)

            breakpoint_plans.append(
                BreakpointCapturePlan(
                    breakpoint=breakpoint,
                    status=status,
                    reference=reference,
                    declared_viewport=declared_viewport,
                    is_canonical_viewport=is_canonical,
                    diagnostics=tuple(diagnostics),
                )
            )
        page_plans.append(PageCapturePlan(page_id=page_id, breakpoints=tuple(breakpoint_plans)))

    return ProjectCapturePlan(pages=tuple(page_plans), diagnostics=tuple(project_diagnostics))
