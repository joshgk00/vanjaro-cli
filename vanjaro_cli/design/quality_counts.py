"""Compute the release-gate quality ratios straight from a composition plan.

`vanjaro_cli/release/gates.py` requires four project quality measures
(`eligible_section_editable_coverage`, `native_agency_component_ratio`,
`body_without_generic_fallback`, `desktop_tablet_mobile_evidence`), but until
now the only source for those numbers was an operator-typed worksheet
(`vanjaro_cli/release/scaffolding.py`'s `quality-counts.template.json`).
Nothing in the tool computed them. This module does, deterministically, from
the same `CompositionPlan` and template catalog the planner already produced.

Rules, applied exactly:

(a) eligible_section_editable_coverage
    Denominator: body entries (`block.type != BlockType.GLOBAL`) that have at
    least one binding.
    Numerator: of those, entries whose bindings are all `editable=True`.
    An empty denominator records 0/1 with a warning; it is never divided.

(b) native_agency_component_ratio
    Denominator: all plan entries.
    Numerator: entries whose resolved template capability manifest has
    `native_component_ratio >= 0.90` and whose `scoped_css` rule count is
    within the plan's own `policy.css_rule_budget`. Every section carries a
    few scoped rules from style translation, so "no scoped CSS" would never
    be met; the budget is the line the plan itself drew.
    The template is looked up by `entry.template_id` in the catalog the plan
    was made against. An entry whose template is not in that catalog counts
    as not native and adds a warning naming the missing template.

(c) body_without_generic_fallback
    Denominator: body entries (`block.type != BlockType.GLOBAL`).
    Numerator: of those, entries whose `template_id` is not in
    `GENERIC_FALLBACK_TEMPLATE_IDS` and whose `match.blocking` is `False`.

(d) desktop_tablet_mobile_evidence
    Denominator: the number of pages the *resolved design document* actually
    has, including pages with no sections — but only when an authoritative,
    non-empty `page_identity` (built by `resolve_page_identity` from that
    document) is supplied. Page identity for a plan entry comes from
    `page_identity.section_page_ids[entry.source_section_id]` — the section's
    real owning page, not a string heuristic. An entry whose section is
    absent from that map (or whose mapped page id is not one of
    `page_identity.page_ids`) is warned about and contributes to no page,
    rather than being guessed from ID punctuation. `page_identity.page_ids`
    is de-duplicated before counting, so a malformed identity map can never
    inflate the denominator.
    When no usable `page_identity` is supplied — either none at all, or one
    that resolves to zero pages (legacy callers, or a workspace with no
    resolved design document) — this metric is recorded 0/1 with an explicit
    warning. It never falls back to guessing page identity from
    `source_section_id` punctuation: that heuristic mis-identifies pages for
    source adapters (such as the image adapter) whose section ids are opaque
    hashes with no ".", so a missing authoritative mapping must earn zero
    capture credit rather than an unearned one.
    Numerator: pages for which `capture_evidence` reports all three of
    "desktop", "tablet", and "mobile". `capture_evidence` is a plain mapping
    of `{page_id: set of breakpoint names}` supplied by the caller; when the
    caller has none, it passes an empty mapping and the count is 0/N. This
    module never invents captures.

Every denominator that would otherwise be 0 is recorded as 0/1 with a
warning instead of dividing, so a caller can always trust the counts without
first checking for a `ZeroDivisionError`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.composition import BlockType, CompositionPlan, CompositionPlanEntry
from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.template_catalog import TemplateCatalogEntry

__all__ = [
    "GENERIC_FALLBACK_TEMPLATE_IDS",
    "PageIdentityMap",
    "QualityCount",
    "QualityCountsReport",
    "QualityEntryRow",
    "compute_quality_counts",
    "resolve_page_identity",
]

GENERIC_FALLBACK_TEMPLATE_IDS = frozenset({"Content/rich-text"})

_NATIVE_COMPONENT_RATIO_THRESHOLD = 0.90


class _QualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class QualityCount(_QualityModel):
    """One gate's raw numerator/denominator, never a bare ratio."""

    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)

    @property
    def ratio(self) -> float:
        return self.numerator / self.denominator


class QualityEntryRow(_QualityModel):
    """Per-entry detail so a reader can see which section cost which point."""

    entry_id: str
    template_id: str
    is_body: bool
    is_editable: bool
    is_native: bool
    is_generic_fallback: bool


class QualityCountsReport(_QualityModel):
    eligible_section_editable_coverage: QualityCount
    native_agency_component_ratio: QualityCount
    body_without_generic_fallback: QualityCount
    desktop_tablet_mobile_evidence: QualityCount
    rows: tuple[QualityEntryRow, ...]
    warnings: tuple[str, ...]


class PageIdentityMap(_QualityModel):
    """Authoritative page identity from a resolved `DesignDocument`.

    `page_ids` lists every page exactly once, including pages with no
    sections. `section_page_ids` maps each section id to its owning page id,
    so a plan entry's real page never has to be guessed from ID punctuation.
    """

    page_ids: tuple[str, ...] = Field(default_factory=tuple)
    section_page_ids: dict[str, str] = Field(default_factory=dict)


def resolve_page_identity(document: DesignDocument) -> PageIdentityMap:
    """Build the section->page map and complete page id list from a document.

    Pure: takes an already-parsed `DesignDocument`, does no I/O. Reading the
    document off disk is the caller's job (an orchestration concern); this is
    just the data transformation.
    """

    page_ids = tuple(page.id for page in document.pages)
    section_page_ids = {
        section.id: page.id for page in document.pages for section in page.sections
    }
    return PageIdentityMap(page_ids=page_ids, section_page_ids=section_page_ids)


def _is_body(entry: CompositionPlanEntry) -> bool:
    return entry.block.type != BlockType.GLOBAL


def _count(numerator: int, denominator: int, *, empty_note: str, warnings: list[str]) -> QualityCount:
    if denominator == 0:
        warnings.append(empty_note)
        return QualityCount(numerator=0, denominator=1)
    return QualityCount(numerator=numerator, denominator=denominator)


def _is_native(
    entry: CompositionPlanEntry,
    catalog_by_id: Mapping[str, TemplateCatalogEntry],
    unknown_templates: set[str],
    css_rule_budget: int,
) -> bool:
    template = catalog_by_id.get(entry.template_id.casefold())
    if template is None:
        unknown_templates.add(entry.template_id)
        return False
    return (
        template.capabilities.native_component_ratio >= _NATIVE_COMPONENT_RATIO_THRESHOLD
        and len(entry.scoped_css) <= css_rule_budget
    )


def _is_generic_fallback(entry: CompositionPlanEntry) -> bool:
    return entry.template_id in GENERIC_FALLBACK_TEMPLATE_IDS or entry.match.blocking


def compute_quality_counts(
    plan: CompositionPlan,
    catalog: Sequence[TemplateCatalogEntry],
    capture_evidence: Mapping[str, Iterable[str]],
    *,
    page_identity: PageIdentityMap | None = None,
) -> QualityCountsReport:
    """Derive the four release quality ratios from a plan and its catalog.

    Pure and deterministic: no network access, no filesystem writes, and no
    timestamps. `capture_evidence` is caller-supplied and never invented here.

    `page_identity`, built by `resolve_page_identity` from the workspace's
    resolved design document, is the authoritative source for what pages
    exist and which page each plan entry's section belongs to.
    `desktop_tablet_mobile_evidence` is recorded 0/1 with an explicit
    warning whenever no such authoritative, non-empty `page_identity` is
    supplied -- it is never inferred by guessing page identity from
    `source_section_id` punctuation.
    """

    warnings: list[str] = []
    catalog_by_id = {entry.template_id.casefold(): entry for entry in catalog}
    unknown_templates: set[str] = set()

    rows: list[QualityEntryRow] = []
    editable_denominator = 0
    editable_numerator = 0
    native_numerator = 0
    fallback_denominator = 0
    fallback_numerator = 0

    for entry in plan.entries:
        is_body = _is_body(entry)
        has_bindings = bool(entry.bindings)
        is_editable = has_bindings and all(binding.editable for binding in entry.bindings)
        is_native = _is_native(
            entry, catalog_by_id, unknown_templates, plan.policy.css_rule_budget
        )
        is_fallback = _is_generic_fallback(entry)

        if is_body and has_bindings:
            editable_denominator += 1
            if is_editable:
                editable_numerator += 1
        if is_native:
            native_numerator += 1
        if is_body:
            fallback_denominator += 1
            if not is_fallback:
                fallback_numerator += 1

        rows.append(
            QualityEntryRow(
                entry_id=entry.id,
                template_id=entry.template_id,
                is_body=is_body,
                is_editable=is_editable,
                is_native=is_native,
                is_generic_fallback=is_fallback,
            )
        )

    warnings.extend(
        f"entry template {template_id!r} is not in the template catalog; "
        "counted as not native"
        for template_id in sorted(unknown_templates)
    )

    page_ids = list(dict.fromkeys(page_identity.page_ids)) if page_identity is not None else []

    if page_ids:
        valid_page_ids = set(page_ids)
        section_page_ids = page_identity.section_page_ids
        unmapped_sections = sorted(
            {
                entry.source_section_id
                for entry in plan.entries
                if section_page_ids.get(entry.source_section_id) not in valid_page_ids
            }
        )
        warnings.extend(
            f"source section {section_id!r} has no page mapping in the resolved "
            "design document; its capture evidence cannot be attributed to a page"
            for section_id in unmapped_sections
        )
        evidence_pages = 0
        for page_id in page_ids:
            breakpoints = set(capture_evidence.get(page_id, ()))
            if {"desktop", "tablet", "mobile"} <= breakpoints:
                evidence_pages += 1
        desktop_tablet_mobile_evidence = QualityCount(
            numerator=evidence_pages, denominator=len(page_ids)
        )
    else:
        if page_identity is not None:
            warnings.append(
                "resolved design document supplied no authoritative pages; "
                "desktop_tablet_mobile_evidence cannot be attributed to real "
                "pages and is recorded 0/1"
            )
        else:
            warnings.append(
                "no resolved design document page mapping was supplied; "
                "desktop_tablet_mobile_evidence is never inferred from "
                "source_section_id punctuation, so it is recorded 0/1"
            )
        desktop_tablet_mobile_evidence = QualityCount(numerator=0, denominator=1)

    rows.sort(key=lambda row: row.entry_id)

    return QualityCountsReport(
        eligible_section_editable_coverage=_count(
            editable_numerator,
            editable_denominator,
            empty_note=(
                "eligible_section_editable_coverage: no body entries with bindings; "
                "recorded 0/1"
            ),
            warnings=warnings,
        ),
        native_agency_component_ratio=_count(
            native_numerator,
            len(plan.entries),
            empty_note="native_agency_component_ratio: plan has no entries; recorded 0/1",
            warnings=warnings,
        ),
        body_without_generic_fallback=_count(
            fallback_numerator,
            fallback_denominator,
            empty_note="body_without_generic_fallback: no body entries; recorded 0/1",
            warnings=warnings,
        ),
        desktop_tablet_mobile_evidence=desktop_tablet_mobile_evidence,
        rows=tuple(rows),
        warnings=tuple(sorted(set(warnings))),
    )
