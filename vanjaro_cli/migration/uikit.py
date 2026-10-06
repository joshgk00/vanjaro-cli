"""UIkit page-builder vocabulary: authored sections, desktop visibility, headings.

YOOtheme Pro writes a page as plain `<div>` elements carrying UIkit classes, so
none of the tag-based boundary rules apply to it. The class names here are
UIkit's own documented API, shared by every UIkit theme, not any one site's.
"""

from __future__ import annotations

import copy
import re
from typing import NamedTuple

from bs4 import NavigableString, Tag

__all__ = [
    "AuthoredSection",
    "authored_sections",
    "is_hidden_at_desktop",
    "is_hidden_class",
    "is_uikit_section",
    "normalize_accordions",
    "uikit_heading_tag",
]

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# `uk-hidden@m` hides an element from the medium breakpoint (960px) up, so it
# is absent from the desktop layout that extraction describes.
_HIDDEN_AT_DESKTOP = frozenset({"uk-hidden@s", "uk-hidden@m", "uk-hidden@l"})

_HEADING_CLASS = re.compile(r"uk-h([1-6])")

_AUTHORED_TEXT_SHARE = 0.9
_BAND_MINIMUM_BODY_CHARACTERS = 40


def is_uikit_section(element: Tag) -> bool:
    """Whether the page builder marked this element as one of its page sections.

    YOOtheme writes every page section as a `<div>` carrying `uk-section` or a
    `uk-section-<variant>` class, with no `<section>` tag, no id and no pane.
    Whole class tokens only, so an unrelated class that merely contains the
    word does not match.
    """

    return any(
        str(name) == "uk-section" or str(name).startswith("uk-section-")
        for name in element.get("class") or []
    )


def is_hidden_class(element: Tag) -> bool:
    return any(str(name) in _HIDDEN_AT_DESKTOP for name in element.get("class") or [])


def is_hidden_at_desktop(element: Tag) -> bool:
    """Whether a UIkit visibility class hides this element, or an ancestor, on a desktop.

    YOOtheme writes a mobile twin of a section (its own hero, call bar, header)
    beside the desktop one with `uk-hidden@m`. Read as ordinary content the twin
    arrives as a second section repeating the first.
    """

    return any(
        isinstance(node, Tag) and is_hidden_class(node) for node in (element, *element.parents)
    )


def uikit_heading_tag(element: Tag) -> str | None:
    """Return the heading tag a `uk-h1`..`uk-h6` class names, if the element has one.

    UIkit styles any element as a heading through a class, and YOOtheme writes
    item and section titles as `<div class="uk-h3">` freely. Read as a plain
    block it became body copy, so a card's title was indistinguishable from its
    description.
    """

    for name in element.get("class") or []:
        match = _HEADING_CLASS.fullmatch(str(name))
        if match:
            return f"h{match.group(1)}"
    return None


def normalize_accordions(root: Tag) -> None:
    """Rewrite UIkit accordions as the `<details>`/`<summary>` they stand in for.

    A UIkit accordion is a `[uk-accordion]` container of items, each holding an
    `.uk-accordion-title` and an `.uk-accordion-content`. Everything downstream
    that recognises a question-and-answer list reads native `<details>`, so the
    accordion is spelled that way once, here, instead of teaching each reader a
    second markup.
    """

    for accordion in root.find_all(attrs={"uk-accordion": True}):
        for item in accordion.find_all(recursive=False):
            title = item.find(class_="uk-accordion-title")
            if title is not None and item.find(class_="uk-accordion-content") is not None:
                item.name = "details"
                title.name = "summary"


def _is_authored_heading(tag: Tag) -> bool:
    """A heading element the author wrote, not a `div.uk-hN` rewritten into one.

    Extraction rewrites those divs into heading tags, the boundary rules read
    the page before it does, and both must see the same headings. A rewritten
    div always carries the class that matches its new tag.
    """

    return tag.name in _HEADING_TAGS and uikit_heading_tag(tag) != tag.name


def _authored_heading_count(element: Tag) -> int:
    return sum(1 for tag in element.find_all(_HEADING_TAGS) if _is_authored_heading(tag))


def _signature(element: Tag) -> tuple[str, tuple[str, ...]]:
    return element.name, tuple(sorted(str(name) for name in element.get("class") or []))


def _is_item_heading(heading: Tag, section: Tag) -> bool:
    """Whether the heading titles one of several repeated items.

    A card or a list entry carries its own heading, and a section of six of
    them has six headings that are not six sections. Items repeat one shape, so
    the test is an ancestor with siblings of the same signature that each hold
    the same number of headings; stacked rows of a page share a class but not
    a count.
    """

    node = heading.parent
    while isinstance(node, Tag) and node is not section:
        parent = node.parent
        if isinstance(parent, Tag):
            twins = [
                sibling
                for sibling in parent.find_all(node.name, recursive=False)
                if _signature(sibling) == _signature(node)
            ]
            if len(twins) >= 2 and len({_authored_heading_count(twin) for twin in twins}) == 1:
                return True
        node = parent
    return False


def _sits_side_by_side(first: Tag, second: Tag, section: Tag) -> bool:
    """Whether two headings are columns of one grid row rather than stacked parts.

    Splitting side-by-side columns into stacked sections would change the
    layout, so a pair that shares a grid row is left whole.
    """

    ancestors = {id(node) for node in first.parents}
    common = next((node for node in second.parents if id(node) in ancestors), None)
    if not isinstance(common, Tag) or common is section:
        return False
    return "uk-grid" in (common.get("class") or [])


def _band_starts(section: Tag) -> list[Tag]:
    eligible = [
        heading
        for heading in section.find_all(_HEADING_TAGS)
        if _is_authored_heading(heading) and not _is_item_heading(heading, section)
    ]
    if not eligible:
        return []
    level = min(int(heading.name[1]) for heading in eligible)
    if level > 2:
        return []
    starts = [heading for heading in eligible if int(heading.name[1]) == level]
    if len(starts) < 2:
        return []
    if any(_sits_side_by_side(first, second, section) for first, second in zip(starts, starts[1:])):
        return []
    return starts


def _prune_to_range(clone: Tag, low: int, high: int) -> None:
    nodes = list(clone.descendants)
    for index in range(len(nodes) - 1, -1, -1):
        node = nodes[index]
        if low <= index < high:
            continue
        if isinstance(node, NavigableString) or not node.contents:
            node.extract()


def _has_body(band: Tag) -> bool:
    headings = sum(
        len(tag.get_text(" ", strip=True)) for tag in band.find_all(_HEADING_TAGS)
    )
    body = len(band.get_text(" ", strip=True)) - headings
    return body >= _BAND_MINIMUM_BODY_CHARACTERS or band.find("img") is not None


def section_bands(section: Tag) -> list[Tag]:
    """Split one authored section where its page-level headings start new parts.

    The YOOtheme editor lets an author stack any number of elements in one
    section, and a real page put a reviews band, a services list and an FAQ in
    one: three `<h2>` at the same level, each opening a part with its own body.
    Left whole they arrive as one section holding three sections' content, and
    no template holds that.

    Conservative on purpose: it splits only on authored `<h1>`/`<h2>` headings
    that title the section's parts rather than repeated items, never across
    columns of one grid row, and only when every resulting part has body copy or
    a picture of its own. Anything else leaves the section as the author made it.

    Each band is a pruned copy detached from the page. It carries no id, so
    nothing mistakes it for the section it came from.
    """

    starts = _band_starts(section)
    if not starts:
        return [section]
    order = {id(node): index for index, node in enumerate(section.descendants)}
    total = len(order)
    bounds = [0, *(order[id(heading)] for heading in starts[1:]), total]
    bands: list[Tag] = []
    for low, high in zip(bounds, bounds[1:]):
        clone = copy.copy(section)
        clone.attrs.pop("id", None)
        clone.attrs.pop("data-id", None)
        _prune_to_range(clone, low, high)
        bands.append(clone)
    if not all(_has_body(band) for band in bands):
        return [section]
    return bands


class AuthoredSection(NamedTuple):
    """One section the builder authored, or one band of such a section."""

    element: Tag
    source: Tag
    band_index: int


def authored_sections(
    container: Tag, *, require_page_share: bool = False
) -> list[AuthoredSection]:
    """Return the page's UIkit sections, split into bands, in document order.

    Header, footer, nav and desktop-hidden sections are left out: the first two
    are page chrome handled on their own, and the last are the mobile twin of a
    section the page already shows.

    ``require_page_share`` is for extraction, where using these as the page's
    sections replaces the generic wrapper descent. It then applies only when the
    sections hold nearly all of the container's text, because a page that kept
    most of its content outside them is not laid out by sections and would lose
    the rest.
    """

    found = [
        element
        for element in container.find_all(is_uikit_section)
        if element.find_parent(["header", "footer", "nav"]) is None
        and not is_hidden_at_desktop(element)
    ]
    outermost = [
        element
        for element in found
        if not any(other is not element and other in element.parents for other in found)
    ]
    visible = [
        element
        for element in outermost
        if element.get_text(" ", strip=True) or element.find(["img", "video"]) is not None
    ]
    if require_page_share:
        if len(visible) < 2:
            return []
        page_text = len(container.get_text(" ", strip=True)) or 1
        section_text = sum(len(element.get_text(" ", strip=True)) for element in visible)
        if section_text / page_text < _AUTHORED_TEXT_SHARE:
            return []
    return [
        AuthoredSection(band, element, index)
        for element in visible
        for index, band in enumerate(section_bands(element))
    ]
