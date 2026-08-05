"""Record the fidelity evidence `project verify` scores (VF-009).

`project_fidelity` reads `qa/fidelity-evidence.json` and gates on it; until now
nothing wrote that file, so every verification reported `not_scored`. This
module closes the loop: capture the three canonical viewports, measure the built
page at each, pair each measurement with the design's own expectation, and write
the result where the gate already looks for it.

Both the renderer and the measurer are injected. Producing real evidence needs a
built page on a portal, but the sequencing, pairing, and partial-failure rules
are decided here and are fully testable without one.

A breakpoint is recorded only when both sides exist. Half a comparison is not
evidence, and writing it would let the gate score a build against nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from vanjaro_cli.design.fidelity_capture import (
    CaptureRequest,
    PageRenderer,
    capture_three_breakpoints,
)
from vanjaro_cli.design.fidelity_extraction import observe_expected_page
from vanjaro_cli.design.fidelity_observation import PageMeasurer, observe_built_page
from vanjaro_cli.design.models import BreakpointName, DesignDocument
from vanjaro_cli.orchestration.project_fidelity import (
    FIDELITY_EVIDENCE_PATH,
    ProjectFidelityError,
)

__all__ = [
    "CAPTURE_DIRECTORY",
    "record_project_fidelity_evidence",
]

CAPTURE_DIRECTORY = "qa/captures"


def record_project_fidelity_evidence(
    root: Path,
    document: DesignDocument,
    *,
    page_id: str,
    source_url: str,
    built_url: str,
    renderer: PageRenderer,
    measurer: PageMeasurer,
    breakpoints: Iterable[BreakpointName] | None = None,
) -> dict[str, Any]:
    """Capture, measure, and write the evidence the fidelity gate consumes.

    Returns the payload as written. Raises `ProjectFidelityError` when the
    design has no such page — scoring a page the design never described would
    compare a build against nothing.
    """

    page = next((item for item in document.pages if item.id == page_id), None)
    if page is None:
        raise ProjectFidelityError(f"design document has no page {page_id!r}")

    capture_dir = root / CAPTURE_DIRECTORY
    outcome = capture_three_breakpoints(
        CaptureRequest(
            page_id=page_id,
            source_url=source_url,
            output_url=built_url,
            output_dir=capture_dir,
        ),
        renderer,
        breakpoints=breakpoints,
    )

    warnings = list(outcome.warnings)
    expected: dict[str, Any] = {}
    observed: dict[str, Any] = {}

    for pair in outcome.pairs:
        breakpoint = pair.breakpoint
        design = observe_expected_page(page, document, breakpoint)
        if design is None:
            warnings.append(
                f"{breakpoint.value}: design page {page_id} has no sections to expect"
            )
            continue
        try:
            measured = measurer.measure(built_url, breakpoint)
        except Exception as error:  # noqa: BLE001 - recorded, never silently dropped
            warnings.append(f"{breakpoint.value}: measurement failed: {error}")
            continue
        build = observe_built_page(measured)
        if build is None:
            warnings.append(
                f"{breakpoint.value}: the built page reported no measurable sections"
            )
            continue
        expected[breakpoint.value] = design.model_dump(mode="json")
        observed[breakpoint.value] = build.model_dump(mode="json")

    payload = {
        "page_id": page_id,
        "source_url": source_url,
        "built_url": built_url,
        "expected": expected,
        "observed": observed,
        "captures": [
            _capture_entry(pair, root)
            for pair in outcome.pairs
            if pair.breakpoint.value in observed
        ],
        "warnings": warnings,
    }

    destination = root / FIDELITY_EVIDENCE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def _capture_entry(pair: Any, root: Path) -> dict[str, Any]:
    """Record capture paths relative to the workspace so evidence stays portable."""

    return {
        "breakpoint": pair.breakpoint.value,
        "source_path": _relative(pair.source.path, root),
        "output_path": _relative(pair.output.path, root),
        "lazy_load_triggered": pair.source.stability.lazy_load_triggered,
        "fonts_settled": pair.source.stability.fonts_settled,
        "animations_disabled": pair.source.stability.animations_disabled,
    }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
