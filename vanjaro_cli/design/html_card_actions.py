"""Standalone visible action selection for repeated card items.

``html_ownership.enrich_section_from_static_dom``'s card branch (feature
cards, service cards, galleries, ...) built each repeated item from its media,
heading, and paragraphs, but never looked for a standalone call-to-action
anchor inside the card. A `<a class="btn" href="/learn-more">Learn more</a>`
sitting beside a card's description disappeared from the document entirely --
the card's *image* destination survived (recorded as the media element's own
``href`` attribute), but a separate, distinct control a visitor can see and
click did not.

This module centralizes *which* anchors inside one repeat item count as that
card's own actions, so ``html_ownership`` stays a small integration point.
Selection is deliberately conservative: several anchors already have another,
more specific ownership, and reading them as a second action would either
double-count content that already reached the document (the image's own
destination) or invent a control a reader would not recognize as a distinct
button (a linked heading, a whole-card wrapper, a category/byline label, an
inline link inside real prose).

Safety of a selected href (unsafe scheme, disguised control characters, ...)
is deliberately *not* checked here -- that is a planning-time concern shared
with every other button/link binding (`planner.is_safe_link_href`), not an
HTML-only special case.
"""

from __future__ import annotations

from bs4 import Tag

__all__ = ["CardAction", "extract_card_actions"]


# Mirrors the small class-hint vocabulary `html_ownership._has_action` already
# uses to tell a styled call-to-action from plain prose; kept local rather
# than imported since it's the same three tokens judged the same way, not a
# shared contract between the modules.
_ACTION_CLASS_HINTS = ("btn", "button", "cta")

# Exact class tokens (not substrings, so "metadata" never matches "meta") that
# mark an anchor as editorial metadata -- a category badge or byline credit --
# rather than a call to action, even when it is otherwise a bare, unstyled
# link sitting directly in the card. Mirrors the vocabulary
# `html_card_fields` already applies to paragraphs; card actions can carry the
# same markers directly on the anchor.
_METADATA_CLASS_TOKENS = frozenset(
    {
        "category", "categories", "post-category", "entry-category",
        "byline", "entry-meta", "post-meta", "tag", "tags",
    }
)

# The same `rel="tag"` convention `html_card_fields.classify_card_paragraphs`
# already reads on a paragraph's marked descendant, plus the `rel="author"`
# byline microformat. A card action is selected before that classification
# runs, so a category anchor spelled `<p><a rel="tag" href="...">Topic</a></p>`
# must be recognized as metadata here too, or it is consumed as an
# action-only paragraph before `classify_card_paragraphs` ever sees it --
# silently turning a blog card's category label into a button. A bare byline
# credit (`<a rel="author" href="/staff/jane">Jane Doe</a>`) is the same
# shape: metadata a reader recognizes as a name, not a call to action.
_METADATA_ITEMPROPS = frozenset({"articlesection", "author"})
_METADATA_REL_TOKENS = frozenset({"tag", "author"})

# Any level the source might spell a card's own title or a secondary heading
# at -- `h5`/`h6` included, matching the card-title search this module's
# caller already widened for the same reason (a card's title is whatever
# heading level the builder used).
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


class CardAction:
    """One standalone visible action a repeat item owns, in document order."""

    __slots__ = ("kind", "label", "href", "source")

    def __init__(self, kind: str, label: str, href: str, source: Tag) -> None:
        self.kind = kind
        self.label = label
        self.href = href
        self.source = source


def _classes(tag: Tag) -> frozenset[str]:
    return frozenset(value.casefold() for value in tag.get("class", []) or [])


def _rel_tokens(anchor: Tag) -> frozenset[str]:
    rel = anchor.get("rel") or []
    if isinstance(rel, str):
        rel = rel.split()
    return frozenset(str(value).casefold() for value in rel)


def _has_metadata_marker(tag: Tag) -> bool:
    """Whether `tag` itself declares a category/byline role.

    Applied both to the anchor (`<a rel="tag" href="...">Topic</a>`) and,
    for an action-only paragraph, to its owning `<p>`
    (`<p class="category"><a href="...">Topic</a></p>`) -- the marker is
    just as often on the wrapper as on the link itself.
    """

    if _classes(tag) & _METADATA_CLASS_TOKENS:
        return True
    if _rel_tokens(tag) & _METADATA_REL_TOKENS:
        return True
    return str(tag.get("itemprop") or "").casefold() in _METADATA_ITEMPROPS


def _is_image_only(anchor: Tag) -> bool:
    """An anchor whose whole content is a picture: a destination, not a label.

    Its destination already travels on the image itself (see
    `html_ownership.image`); reading it again here would count the same
    content twice and produce a control with no visible label.
    """

    return anchor.find("img") is not None and not anchor.get_text(strip=True)


def _contains(ancestor: Tag, node: Tag) -> bool:
    return any(descendant is node for descendant in ancestor.descendants)


def _overlaps_any_heading(anchor: Tag, headings: list[Tag]) -> bool:
    """Whether `anchor` shares ownership with any heading in the card.

    Covers a linked title (`<h3><a>...</a></h3>`), a linked secondary
    heading (`<h4><a>...</a></h4>`), and a whole-card anchor that wraps a
    heading along with everything else -- in every case the anchor is not a
    distinct, separately-recognizable action. Every heading level is
    checked, not just the one chosen as the card's title: a reader does not
    recognize a linked subheading as a button either.
    """

    return any(
        anchor is heading or _contains(heading, anchor) or _contains(anchor, heading)
        for heading in headings
    )


def _is_metadata_marked(anchor: Tag, item: Tag) -> bool:
    """Whether `anchor` or an enclosing pure wrapper around it is marked.

    A category/byline marker is as often on a wrapping element
    (`<div class="byline"><p><a>...</a></p></div>`, `<span class="category">
    <a>...</a></span>`) as on the anchor itself (`<a rel="tag">`). The walk
    climbs past an ancestor only while that ancestor's whole text is still
    exactly the anchor's own text -- i.e. only while the ancestor exists
    purely to wrap this one anchor and nothing else -- so a marker on some
    unrelated container elsewhere in the card is never picked up.
    """

    label_text = anchor.get_text(" ", strip=True)
    node: Tag = anchor
    while True:
        if _has_metadata_marker(node):
            return True
        parent = node.parent
        if not isinstance(parent, Tag) or parent is item:
            return False
        if parent.get_text(" ", strip=True) != label_text:
            return False
        node = parent


def _is_action_only_paragraph(paragraph: Tag) -> bool:
    """Whether `paragraph`'s entire content is one or more link labels.

    Two actions grouped in one shared paragraph
    (`<p><a>Explore</a><a>Compare</a></p>`) are still an action-only
    paragraph -- neither individual anchor's text matches the paragraph's
    combined text, but the concatenation of every anchor's text does, with
    nothing else contributing a word. A paragraph is never action-only with
    zero anchors.
    """

    anchors = paragraph.find_all("a", href=True)
    if not anchors:
        return False
    combined = " ".join(anchor.get_text(" ", strip=True) for anchor in anchors)
    return combined == paragraph.get_text(" ", strip=True)


def _label(anchor: Tag) -> str:
    return anchor.get_text(" ", strip=True) or str(
        anchor.get("aria-label") or anchor.get("title") or ""
    ).strip()


def _kind_for(anchor: Tag) -> str:
    return "button" if _classes(anchor) & frozenset(_ACTION_CLASS_HINTS) else "link"


def extract_card_actions(item: Tag) -> tuple[list[CardAction], frozenset[int]]:
    """Return one card's standalone actions, and the paragraphs they consumed.

    Every heading level inside the card (whichever one the caller later
    reads as the card's title, and any other) is found here directly, so a
    linked title or a linked secondary heading is excluded without the
    caller needing to share its own title choice.

    The second return value is the ``id()`` of every `<p>` whose entire owned
    content turned out to be one of the returned actions -- callers must drop
    those paragraphs from body-copy consideration, or the same label reaches
    the document twice: once with a destination (the action) and once
    without (as body text). A paragraph that mixes real prose with an inline
    link is never in this set: its whole text is not the link's text, so it
    keeps its prose and the inline link is not promoted to an action.
    """

    headings = item.find_all(_HEADING_TAGS)
    actions: list[CardAction] = []
    consumed_paragraph_ids: set[int] = set()
    for anchor in item.find_all("a", href=True):
        if _is_image_only(anchor):
            continue
        if _overlaps_any_heading(anchor, headings):
            continue
        if _is_metadata_marked(anchor, item):
            continue
        parent_paragraph = anchor.find_parent("p")
        action_only_paragraph = parent_paragraph is not None and _is_action_only_paragraph(
            parent_paragraph
        )
        label = _label(anchor)
        if not label:
            continue
        if parent_paragraph is not None:
            if not action_only_paragraph:
                # Mixed prose: an inline link beside other words is not a
                # standalone action, and the paragraph keeps its prose.
                continue
            consumed_paragraph_ids.add(id(parent_paragraph))
        actions.append(
            CardAction(kind=_kind_for(anchor), label=label, href=str(anchor.get("href") or ""), source=anchor)
        )
    return actions, frozenset(consumed_paragraph_ids)
