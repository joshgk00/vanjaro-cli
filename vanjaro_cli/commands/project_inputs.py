"""Strict parsing helpers for agency project CLI inputs."""

from __future__ import annotations

import re

from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport
from vanjaro_cli.project import ProjectSource


def parse_sources(
    source_specs: tuple[str, ...],
    image_viewports: tuple[str, ...],
    *,
    source_pages: tuple[str, ...] = (),
    image_breakpoints: tuple[str, ...] = (),
    image_evidence: tuple[str, ...] = (),
) -> list[ProjectSource]:
    parsed: list[tuple[SourceKind, str]] = []
    aliases = {
        "html": SourceKind.LIVE_HTML,
        "live": SourceKind.LIVE_HTML,
        "live_html": SourceKind.LIVE_HTML,
        "figma": SourceKind.FIGMA,
        "image": SourceKind.IMAGE,
        "legacy": SourceKind.LEGACY_SECTIONS,
        "legacy_sections": SourceKind.LEGACY_SECTIONS,
    }
    for spec in source_specs:
        if "=" not in spec:
            raise ValueError(f"invalid --source {spec!r}; expected KIND=REFERENCE")
        raw_kind, reference = spec.split("=", 1)
        kind = aliases.get(raw_kind.strip().casefold())
        if kind is None:
            supported = ", ".join(sorted(aliases))
            raise ValueError(
                f"unsupported source kind {raw_kind!r}; choose one of: {supported}"
            )
        if not reference.strip():
            raise ValueError(f"source reference must not be empty: {spec!r}")
        parsed.append((kind, reference.strip()))

    image_count = sum(kind == SourceKind.IMAGE for kind, _ in parsed)
    if len(image_viewports) != image_count:
        raise ValueError(
            f"image sources require one --image-viewport each; "
            f"received {image_count} image source(s) and {len(image_viewports)} viewport(s)"
        )
    viewports = iter(_parse_viewport(value) for value in image_viewports)
    counts: dict[SourceKind, int] = {}
    pending: list[dict[str, object]] = []
    for kind, reference in parsed:
        counts[kind] = counts.get(kind, 0) + 1
        viewport = next(viewports) if kind == SourceKind.IMAGE else None
        pending.append(
            {
                "id": f"{kind.value.replace('_', '-')}-{counts[kind]}",
                "kind": kind,
                "reference": reference,
                "viewport": viewport,
            }
        )
    source_ids = {str(item["id"]) for item in pending}
    pages = _parse_assignments(source_pages, "source page", source_ids)
    breakpoints = _parse_assignments(
        image_breakpoints, "image breakpoint", source_ids
    )
    evidence = _parse_assignments(image_evidence, "image evidence", source_ids)

    sources: list[ProjectSource] = []
    for item in pending:
        source_id = str(item["id"])
        kind = item["kind"]
        assert isinstance(kind, SourceKind)
        breakpoint = None
        evidence_reference = None
        if kind == SourceKind.IMAGE:
            raw_breakpoint = breakpoints.get(source_id)
            if raw_breakpoint is None:
                raise ValueError(
                    f"image source {source_id!r} requires --image-breakpoint "
                    f"{source_id}=desktop|tablet|mobile"
                )
            try:
                breakpoint = BreakpointName(raw_breakpoint.casefold())
            except ValueError as exc:
                supported = ", ".join(value.value for value in BreakpointName)
                raise ValueError(
                    f"invalid image breakpoint {raw_breakpoint!r} for {source_id!r}; "
                    f"choose one of: {supported}"
                ) from exc
            if source_id not in pages:
                raise ValueError(
                    f"image source {source_id!r} requires --source-page "
                    f"{source_id}=PAGE_REFERENCE"
                )
            evidence_reference = evidence.get(source_id)
        elif source_id in breakpoints:
            raise ValueError(
                f"image breakpoint refers to non-image source {source_id!r}"
            )
        elif source_id in evidence:
            raise ValueError(f"image evidence refers to non-image source {source_id!r}")
        sources.append(
            ProjectSource(
                **item,
                page_reference=pages.get(source_id),
                breakpoint=breakpoint,
                evidence_reference=evidence_reference,
            )
        )
    return sources


def parse_template_overrides(values: tuple[str, ...]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(
                f"invalid template override {value!r}; expected SECTION_ID=TEMPLATE"
            )
        section_id, template = (part.strip() for part in value.split("=", 1))
        if not section_id or not template:
            raise ValueError(
                f"invalid template override {value!r}; both values are required"
            )
        if section_id in overrides:
            raise ValueError(f"duplicate template override for {section_id!r}")
        overrides[section_id] = template
    return overrides


def apply_source_pages(
    sources: list[ProjectSource], values: tuple[str, ...]
) -> list[ProjectSource]:
    assignments: dict[str, str] = {}
    source_ids = {source.id for source in sources}
    for value in values:
        if "=" not in value:
            raise ValueError(
                f"invalid source page {value!r}; expected SOURCE_ID=PAGE_REFERENCE"
            )
        source_id, page_reference = (part.strip() for part in value.split("=", 1))
        if source_id not in source_ids:
            raise ValueError(
                f"source page refers to unknown source {source_id!r}; "
                f"available IDs: {', '.join(sorted(source_ids))}"
            )
        if not page_reference:
            raise ValueError(f"source page for {source_id!r} must not be empty")
        if source_id in assignments:
            raise ValueError(f"duplicate source page assignment for {source_id!r}")
        assignments[source_id] = page_reference
    return [
        source.model_copy(update={"page_reference": assignments.get(source.id)})
        if source.id in assignments
        else source
        for source in sources
    ]


def _parse_assignments(
    values: tuple[str, ...], label: str, source_ids: set[str]
) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(
                f"invalid {label} {value!r}; expected SOURCE_ID=VALUE"
            )
        source_id, assigned = (part.strip() for part in value.split("=", 1))
        if source_id not in source_ids:
            raise ValueError(
                f"{label} refers to unknown source {source_id!r}; "
                f"available IDs: {', '.join(sorted(source_ids))}"
            )
        if not assigned:
            raise ValueError(f"{label} for {source_id!r} must not be empty")
        if source_id in assignments:
            raise ValueError(f"duplicate {label} assignment for {source_id!r}")
        assignments[source_id] = assigned
    return assignments


def _parse_viewport(value: str) -> Viewport:
    match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", value)
    if match is None:
        raise ValueError(f"invalid image viewport {value!r}; expected WIDTHxHEIGHT")
    return Viewport(width=int(match.group(1)), height=int(match.group(2)))


__all__ = ["apply_source_pages", "parse_sources", "parse_template_overrides"]
