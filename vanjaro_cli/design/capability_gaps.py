"""Attribute dropped visitor content to the template field that would have held it.

Six template capability gaps have been found so far, and every one of them was
found by a person reading one site's per-section loss list and noticing a
pattern. A plan already records what it could not hold, but it records it as a
sentence attached to a section — so a gap costing three sections on a site
nobody is currently looking at is invisible, and the order the gaps get fixed in
is the order the sites happened to be visited.

This module performs the join that was missing: warning → the template that
produced it → aggregated across every plan → ranked by how much content the gap
actually drops.

Two existing checks look like they should already cover this and do not.
`vocabulary_audit` asks whether a role can reach *any* template field, so a
field four templates declare reads as reachable while the twelve that lack it
drop it silently. `project_planning._content_losses` lists section ids and field
names for one project, with no template attribution and no way to compare two
sites.

Two kinds of source feed it. A project workspace has a composition plan; the
benchmark corpus never builds one, so its cases are read from their matches
instead — the planner copies a match's unmet requirements into an entry's
warnings verbatim, so both paths speak one vocabulary.

Not every loss is a capability gap, and ranking one that isn't would send the
next iteration to widen a template that is behaving correctly. These kinds are
held out deliberately, each recorded with its reason rather than dropped:

* A form field. A form is never rebuilt from a template, so no template should
  declare a field for one — the section gets a placeholder and Josh rebuilds it.
* An asset that resolved to nothing. The template had the slot; the picture
  never arrived. That is an acquisition defect wearing a binding warning.
* An unsupported interaction. A missing behaviour is not a missing field.
* A picture the extractor already called decoration. A mascot floated beside a
  video was deliberately kept out of the media the template holds; ranking it
  would ask for a field that undoes that decision.
* A loss on a section that matched a template the corpus says is wrong for it.
  Widening that template would bind the content and bury the routing defect,
  which is how a team grid spent three releases being built as feature cards.
* A per-item field on a template that repeats nothing. There is no item for it
  to belong to, so declaring one would not give the template anywhere to put a
  second value. The section carries a list its template family cannot hold,
  which is a larger question than a missing field.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from vanjaro_cli.design.composition import CompositionPlan
from vanjaro_cli.design.matcher import TemplateMatchResult
from vanjaro_cli.design.template_catalog import CapabilityManifest

__all__ = [
    "CapabilityGap",
    "CapabilityGapReport",
    "HeldBackLoss",
    "MatchedCase",
    "PlannedProject",
    "SectionLosses",
    "StaleGap",
    "build_capability_gap_report",
]

GapKind = Literal["no_field", "static_only", "insufficient_capacity"]

_NO_FIELD = re.compile(r"^source field '(?P<field>[^']+)' is not editable by template$")
_STATIC_ONLY = re.compile(
    r"^source field '(?P<field>[^']+)' maps only to a static template slot, "
    r"so its content cannot reach the build$"
)
# The matcher reports overflow while choosing, the planner reports it again
# while binding. Both are read, and the pair is folded into one gap below.
_MATCHER_OVERFLOW = re.compile(
    r"^(?P<field>[a-z_][a-z0-9_.]*) needs (?P<needed>\d+) slots, template owns (?P<owned>\d+)$"
)
_PLANNER_OVERFLOW = re.compile(
    r"^\S+: field '(?P<field>[^']+)' has (?P<needed>\d+) values but "
    r"owns (?P<owned>\d+) physical slots$"
)

_ASSET_UNBOUND = re.compile(r"^image \S+ was not bound: ")
_UNSUPPORTED_INTERACTION = re.compile(r"^required interaction '(?P<name>[^']+)' is unsupported$")

# A field whose name says the content belongs to a form. The plan carries the
# form's own inventory, so the check below confirms rather than assumes.
_FORM_FIELD_NAMES = frozenset({"form_field", "form_fields"})

# The extractor's own word for a picture it decided is decoration rather than
# content. Unlike a form field this needs no corroboration: nothing else ever
# assigns the role, and it is assigned only where the decision was made.
_DECORATIVE_FIELD_NAMES = frozenset({"decorative_media"})


class _GapModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SectionLosses(_GapModel):
    """One section, the template it chose, and what that template could not hold."""

    source_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    warnings: tuple[str, ...] = ()
    form_fields: tuple[dict[str, JsonValue], ...] = ()
    # The templates a source says are right for this section, where a source
    # says so at all. Only the benchmark corpus does; a project has no answer
    # key, and an empty tuple means the question was not asked.
    expected_templates: tuple[str, ...] = ()

    @property
    def matched_an_expected_template(self) -> bool:
        if not self.expected_templates:
            return True
        return self.template_id.rsplit("/", 1)[-1] in self.expected_templates


class PlannedProject(_GapModel):
    """One plan and the name to report it under."""

    project_id: str = Field(min_length=1)
    plan: CompositionPlan

    @property
    def source_id(self) -> str:
        return self.project_id

    def section_losses(self) -> tuple[SectionLosses, ...]:
        return tuple(
            SectionLosses(
                source_id=self.project_id,
                section_id=entry.source_section_id,
                template_id=entry.template_id,
                warnings=entry.warnings,
                form_fields=entry.form_fields,
            )
            for entry in self.plan.entries
        )


class MatchedCase(_GapModel):
    """One benchmark case, read from its matches rather than from a plan.

    The offline corpus never builds a composition plan, so for thirty-odd
    iterations the ranked queue covered four project workspaces and none of the
    five cases the pipeline is actually measured against. A match already knows
    which requirements its chosen template cannot meet, and the planner copies
    exactly those strings into an entry's warnings — so the two paths speak one
    vocabulary rather than two.

    What a match cannot report is the losses that only appear at binding time:
    an asset that resolved to nothing, and the planner's second word about a
    capacity overflow. Neither costs the report anything. The first is held back
    as an acquisition defect wherever it is seen, and the second repeats a
    warning the match already made.
    """

    case_id: str = Field(min_length=1)
    matches: tuple[TemplateMatchResult, ...] = ()
    # Section order, from the case's annotations: which templates each section
    # may acceptably match. The corpus is the one source that knows.
    expected_templates: tuple[tuple[str, ...], ...] = ()

    @property
    def source_id(self) -> str:
        return self.case_id

    def section_losses(self) -> tuple[SectionLosses, ...]:
        return tuple(
            SectionLosses(
                source_id=self.case_id,
                section_id=result.section_id,
                template_id=result.selected_candidate.template_id,
                warnings=result.selected_candidate.missing_requirements,
                expected_templates=(
                    self.expected_templates[index]
                    if index < len(self.expected_templates)
                    else ()
                ),
            )
            for index, result in enumerate(self.matches)
        )


class CapabilityGap(_GapModel):
    """One template field that could not hold content, and everywhere it cost."""

    template_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    kind: GapKind
    projects: tuple[str, ...] = Field(min_length=1)
    sections: tuple[str, ...] = Field(min_length=1)
    # Present only for a capacity gap: the most any one section demanded, and
    # what the template owns. A template widened to the maximum observed demand
    # closes every section the gap covers.
    demanded_slots: int | None = None
    owned_slots: int | None = None

    @property
    def dropped_field_count(self) -> int:
        """Sections that lost this field.

        One section can report the same gap twice — the matcher says it while
        choosing and the planner says it again while binding — so this counts
        sections, not warnings, and a capacity gap does not outrank a missing
        field purely by being mentioned more often.
        """

        return len(self.sections)


class HeldBackLoss(_GapModel):
    """A loss deliberately not ranked, and why it is not work."""

    template_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    warning: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class StaleGap(_GapModel):
    """A gap the plan recorded that the library no longer has."""

    gap: CapabilityGap
    reason: str = Field(min_length=1)


class CapabilityGapReport(_GapModel):
    schema_version: Literal["1.0"] = "1.0"
    projects: tuple[str, ...] = ()
    section_count: int = Field(default=0, ge=0)
    gaps: tuple[CapabilityGap, ...] = ()
    stale: tuple[StaleGap, ...] = ()
    held_back: tuple[HeldBackLoss, ...] = ()

    @property
    def dropped_field_count(self) -> int:
        return sum(gap.dropped_field_count for gap in self.gaps)


class _Accumulator:
    def __init__(self) -> None:
        self.projects: set[str] = set()
        self.sections: set[str] = set()
        self.demanded: int | None = None
        self.owned: int | None = None

    def record(self, project_id: str, section_id: str, demanded: int | None, owned: int | None) -> None:
        self.projects.add(project_id)
        self.sections.add(section_id)
        if demanded is not None:
            self.demanded = demanded if self.demanded is None else max(self.demanded, demanded)
        if owned is not None:
            self.owned = owned if self.owned is None else min(self.owned, owned)


def _held_back_reason(
    section: SectionLosses,
    warning: str,
    field: str | None,
    catalog: Mapping[str, CapabilityManifest] | None,
) -> str | None:
    """Say why a loss is not a capability gap, or None when it is one."""

    if _ASSET_UNBOUND.match(warning):
        return "the template owns the slot; the asset resolved to no usable source"
    interaction = _UNSUPPORTED_INTERACTION.match(warning)
    if interaction:
        return f"{interaction['name']!r} is a missing behaviour, not a missing field"
    if field in _FORM_FIELD_NAMES and section.form_fields:
        return "a form is never rebuilt from a template; its fields travel as a placeholder"
    if field in _DECORATIVE_FIELD_NAMES:
        return "the extractor classified this picture as decoration, not content"
    if not section.matched_an_expected_template:
        return (
            "the corpus expects "
            + " or ".join(section.expected_templates)
            + " here, so this is a routing defect rather than a missing field"
        )
    if field and field.startswith("item.") and catalog is not None:
        manifest = catalog.get(section.template_id)
        if manifest is not None and manifest.repeat_group is None:
            # The section brought a repeated list to a template that repeats
            # nothing, so there is no item for the field to belong to. Declaring
            # one would not give the template somewhere to put a second value.
            # The real question is whether this template family should repeat at
            # all, which is a bigger one than a missing field.
            return (
                "the template repeats nothing, so a per-item field has no item to "
                "attach to; the section carries a list this template family cannot hold"
            )
    return None


def _classify(warning: str) -> tuple[GapKind, str, int | None, int | None] | None:
    """Read a warning as a capability gap, or None when it is not one.

    A warning that says the *template* wants something the source does not have
    is the mirror image of a gap and is not read here: no content is dropped, so
    widening a template would not help and narrowing one is a different task.
    """

    match = _NO_FIELD.match(warning)
    if match:
        return "no_field", match["field"], None, None
    match = _STATIC_ONLY.match(warning)
    if match:
        return "static_only", match["field"], None, None
    for pattern in (_MATCHER_OVERFLOW, _PLANNER_OVERFLOW):
        match = pattern.match(warning)
        if match:
            return (
                "insufficient_capacity",
                match["field"],
                int(match["needed"]),
                int(match["owned"]),
            )
    return None


def _stale_reason(gap: CapabilityGap, catalog: Mapping[str, CapabilityManifest]) -> str | None:
    """Say why a recorded gap is no longer work, or None when it still is.

    A plan is a record of what the library could do on the day it ran. Pack
    1.6.0 gave `feature-cards-3up` a section title, and a plan written before it
    still says the heading was dropped — so a queue built from plans alone would
    send the next iteration to fix something already fixed. Some plans cannot be
    refreshed to find out: re-analysing a project invalidates approvals granted
    against it.

    So the gap is checked against the library as it stands now rather than
    against the day the plan ran.
    """

    manifest = catalog.get(gap.template_id)
    if manifest is None:
        return "the template is no longer in the library"
    if gap.kind in {"no_field", "static_only"}:
        if gap.field in manifest.fields and gap.field not in manifest.static_fields:
            return "the template now declares the field as editable"
        return None
    contract = manifest.physical_fields.get(gap.field)
    if contract and gap.demanded_slots is not None and contract.slots_per_owner >= gap.demanded_slots:
        return f"the template now owns {contract.slots_per_owner} slots for the field"
    return None


def build_capability_gap_report(
    sources: Iterable[PlannedProject | MatchedCase],
    *,
    catalog: Mapping[str, CapabilityManifest] | None = None,
) -> CapabilityGapReport:
    """Rank every template field that dropped visitor content, worst first.

    Ranking is by sections lost, because that is the measure of what a widening
    would recover. Ties break on template and field name so the same evidence
    always produces the same order — a queue that reshuffles between runs cannot
    be worked from.

    Pass the current catalog to have gaps the library has since closed reported
    as stale instead of ranked. Without it every plan is taken at its word,
    which is right for a plan written today and wrong for one written before the
    last pack release.
    """

    accumulated: dict[tuple[str, str, GapKind], _Accumulator] = defaultdict(_Accumulator)
    held_back: list[HeldBackLoss] = []
    project_ids: list[str] = []
    section_count = 0

    for source in sources:
        project_ids.append(source.source_id)
        for section in source.section_losses():
            section_count += 1
            for warning in section.warnings:
                classified = _classify(warning)
                field = classified[1] if classified else None
                reason = _held_back_reason(section, warning, field, catalog)
                if reason is not None:
                    held_back.append(
                        HeldBackLoss(
                            template_id=section.template_id,
                            project_id=source.source_id,
                            section_id=section.section_id,
                            warning=warning,
                            reason=reason,
                        )
                    )
                    continue
                if classified is None:
                    continue
                kind, name, demanded, owned = classified
                accumulated[(section.template_id, name, kind)].record(
                    source.source_id, section.section_id, demanded, owned
                )

    gaps = [
        CapabilityGap(
            template_id=template_id,
            field=field,
            kind=kind,
            projects=tuple(sorted(state.projects)),
            sections=tuple(sorted(state.sections)),
            demanded_slots=state.demanded,
            owned_slots=state.owned,
        )
        for (template_id, field, kind), state in accumulated.items()
    ]
    gaps.sort(key=lambda gap: (-gap.dropped_field_count, gap.template_id, gap.field, gap.kind))

    stale: list[StaleGap] = []
    if catalog is not None:
        live: list[CapabilityGap] = []
        for gap in gaps:
            reason = _stale_reason(gap, catalog)
            if reason is None:
                live.append(gap)
            else:
                stale.append(StaleGap(gap=gap, reason=reason))
        gaps = live

    return CapabilityGapReport(
        projects=tuple(project_ids),
        section_count=section_count,
        gaps=tuple(gaps),
        stale=tuple(stale),
        held_back=tuple(
            sorted(held_back, key=lambda loss: (loss.project_id, loss.section_id, loss.warning))
        ),
    )
