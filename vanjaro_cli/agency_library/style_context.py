"""Pure resolution of one resolved agency pack's executable style context.

This is W1 only: it turns an already digest/version-verified
``AgencyStylePayload`` into a deterministic, immutable, in-memory context --
class name to declaration mapping, and a rendered stylesheet -- for later
orchestration stages to bind. A definition existing here is *not* evidence
that any target has it: there is no network access, no stylesheet
installation, and no target verification anywhere in this module, which is
why ``AgencyStyleContext.target_verified`` is always ``False``. Proving a
target actually received the stylesheet is explicit, still-outstanding W2/W3
work; nothing in this module should be read as completing that.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from vanjaro_cli.agency_library.registry import ResolvedAgencyPack
from vanjaro_cli.agency_library.style_payload import style_utility_key
from vanjaro_cli.design.style_transport import _validate_value
from vanjaro_cli.design.style_translation import _CSS_PROPERTY_NAMES

__all__ = ["AgencyStyleContext", "resolve_style_context"]


@dataclass(frozen=True, slots=True)
class AgencyStyleContext:
    """Immutable, non-installing view of a resolved pack's executable styles.

    ``agency_utility_items`` is the frozen, hashable source of truth; the
    ``agency_utilities`` property below returns a fresh ``dict`` copy on
    every access so a caller mutating what it read can never reach back into
    this context's own state.
    """

    pack_name: str
    pack_version: str
    pack_digest: str
    style_version: str | None
    style_digest: str | None
    agency_utility_items: tuple[tuple[str, str], ...]
    stylesheet: str
    stylesheet_sha256: str
    target_verified: bool = False

    @property
    def agency_utilities(self) -> dict[str, str]:
        return dict(self.agency_utility_items)


def resolve_style_context(resolved: ResolvedAgencyPack) -> AgencyStyleContext:
    """Build the executable style context for one resolved agency pack.

    Pure and read-only. Every rendered declaration is re-derived from the
    ``StyleProperty``/``source_value`` pair using the same canonical CSS
    property mapping and safety validator the payload itself was already
    validated against at load time (``style_payload.AgencyStyleUtility``);
    nothing here interpolates unchecked source syntax. A pack with no
    ``styles`` payload (legacy or opted-out) resolves to an empty mapping and
    an empty stylesheet.
    """

    if resolved.styles is None:
        empty_stylesheet = ""
        return AgencyStyleContext(
            pack_name=resolved.manifest.name,
            pack_version=resolved.manifest.version,
            pack_digest=resolved.digest,
            style_version=None,
            style_digest=None,
            agency_utility_items=(),
            stylesheet=empty_stylesheet,
            stylesheet_sha256=hashlib.sha256(empty_stylesheet.encode("utf-8")).hexdigest(),
        )

    mapping: dict[str, str] = {}
    declarations: dict[str, str] = {}
    for utility in resolved.styles.utilities:
        css_property = _CSS_PROPERTY_NAMES[utility.property]
        raw_value = utility.source_value.strip()
        candidate = f"{raw_value} !important" if utility.important else raw_value
        safe_value = _validate_value(css_property, candidate)
        mapping[style_utility_key(utility)] = utility.class_name
        declarations[utility.class_name] = f"{css_property}: {safe_value};"

    # Ordered by class name so the rendered stylesheet -- and therefore its
    # digest -- is independent of the source payload's declaration order.
    stylesheet = "\n".join(
        f".{class_name} {{ {declarations[class_name]} }}"
        for class_name in sorted(declarations)
    )
    style_reference = resolved.manifest.styles
    assert style_reference is not None  # invariant: registry only sets both together
    return AgencyStyleContext(
        pack_name=resolved.manifest.name,
        pack_version=resolved.manifest.version,
        pack_digest=resolved.digest,
        style_version=style_reference.version,
        style_digest=style_reference.sha256,
        agency_utility_items=tuple(sorted(mapping.items())),
        stylesheet=stylesheet,
        stylesheet_sha256=hashlib.sha256(stylesheet.encode("utf-8")).hexdigest(),
    )
