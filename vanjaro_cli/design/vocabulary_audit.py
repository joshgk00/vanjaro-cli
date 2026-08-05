"""Audit whether observed roles can reach declared template fields (VF-208).

VF-206 surfaced a failure mode with no detector: a section can match a template
on every subscore and still bind nothing, because the roles the adapters emit
have no alias reaching the fields the template declares. Matching still scores,
so the gap is invisible until a build comes out empty.

This module compares the two vocabularies directly:

* **Observed** — the roles and repeat-item field names that adapters actually
  produce, read from real Design Documents rather than a hand-maintained list.
* **Declared** — the fields catalog templates say they can fill.

It reports unreachable pairs in both directions. A role no template field can
accept is content the pipeline can see but never place; a required field no
observed role can satisfy is a template nothing can bind.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.semantics import (
    item_capability_aliases,
    section_capability_aliases,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogEntry

__all__ = [
    "ObservedVocabulary",
    "VocabularyAudit",
    "audit_vocabulary",
    "declared_fields",
    "observed_vocabulary",
]


class ObservedVocabulary(BaseModel):
    """Roles and item fields the adapters emitted, with where each came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    section_roles: tuple[str, ...] = ()
    item_fields: tuple[str, ...] = ()
    item_roles: tuple[str, ...] = ()


class VocabularyAudit(BaseModel):
    """Roles that cannot bind, and declared fields nothing can satisfy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unreachable_section_roles: tuple[str, ...] = ()
    unreachable_item_fields: tuple[str, ...] = ()
    unsatisfiable_required_fields: tuple[tuple[str, str], ...] = Field(default=())

    @property
    def clean(self) -> bool:
        return not (
            self.unreachable_section_roles
            or self.unreachable_item_fields
            or self.unsatisfiable_required_fields
        )


def observed_vocabulary(documents: Iterable[DesignDocument]) -> ObservedVocabulary:
    """Collect every role and item-field name the given documents contain."""

    section_roles: set[str] = set()
    item_fields: set[str] = set()
    item_roles: set[str] = set()

    for document in documents:
        for page in document.pages:
            for section in page.sections:
                grouped = {
                    element.id
                    for element in section.content
                    if element.group_id is not None
                }
                for element in section.content:
                    if element.id in grouped:
                        item_roles.add(element.role)
                    else:
                        section_roles.add(element.role)
                for group in section.groups:
                    for item in group.items:
                        item_fields.update(item.fields)

    return ObservedVocabulary(
        section_roles=tuple(sorted(section_roles)),
        item_fields=tuple(sorted(item_fields)),
        item_roles=tuple(sorted(item_roles)),
    )


def declared_fields(catalog: Iterable[TemplateCatalogEntry]) -> frozenset[str]:
    """Every field name the catalog can fill, editable or static."""

    declared: set[str] = set()
    for entry in catalog:
        declared.update(entry.capabilities.fields)
        declared.update(entry.capabilities.static_fields)
    return frozenset(declared)


def audit_vocabulary(
    documents: Iterable[DesignDocument],
    catalog: Iterable[TemplateCatalogEntry],
) -> VocabularyAudit:
    """Report vocabulary that cannot bind, in both directions."""

    entries = tuple(catalog)
    declared = declared_fields(entries)
    observed = observed_vocabulary(documents)

    unreachable_sections = tuple(
        role
        for role in observed.section_roles
        if not declared.intersection(section_capability_aliases(role))
    )
    unreachable_items = tuple(
        sorted(
            {
                name
                for name in (*observed.item_fields, *observed.item_roles)
                if not declared.intersection(item_capability_aliases(name))
            }
        )
    )

    satisfiable = {
        alias
        for role in observed.section_roles
        for alias in section_capability_aliases(role)
    }
    satisfiable.update(
        alias
        for name in (*observed.item_fields, *observed.item_roles)
        for alias in item_capability_aliases(name)
    )
    unsatisfiable = tuple(
        sorted(
            (entry.template_id, field)
            for entry in entries
            for field, requirement in entry.capabilities.fields.items()
            if requirement == "required" and field not in satisfiable
        )
    )

    return VocabularyAudit(
        unreachable_section_roles=unreachable_sections,
        unreachable_item_fields=unreachable_items,
        unsatisfiable_required_fields=unsatisfiable,
    )
