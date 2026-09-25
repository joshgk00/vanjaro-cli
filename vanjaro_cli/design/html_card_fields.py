"""Classify a blog/article card's paragraphs into category, body, and byline.

`html_ownership.enrich_section_from_static_dom` used to keep only a card's
first non-date paragraph distinctly (as `body`) and folded every other
paragraph — excerpt, byline, category label — into the same `body` list.
Existing catalog templates (`Cards/blog-post-cards-4up`) already declare
`item.tag`, `item.body`, and `item.meta` as distinct slots, but nothing ever
told them apart, so a byline collapsed into the excerpt and a category badge
collapsed into both.

Classification is deliberately conservative: a paragraph only leaves `body`
when its *whole* owned content is explicit, recognized markup for that role —
a class token, a `rel="tag"` link, or a `schema.org` `itemprop`. Style-only
classes (`text-muted`), site-specific prefixes, and mixed content (an excerpt
that happens to nest a tag link) are never evidence; they stay `body`.
"""

from __future__ import annotations

from bs4 import Tag

from vanjaro_cli.migration.sections import is_publication_date

__all__ = ["CardFieldParagraphs", "classify_card_paragraphs"]


# Exact class tokens, not substrings — "metadata" must never match "meta".
_CATEGORY_CLASS_TOKENS = frozenset({"category", "categories", "post-category", "entry-category"})
_BYLINE_CLASS_TOKENS = frozenset({"byline", "entry-meta", "post-meta"})

# schema.org microdata conventions for an article's section/category and its
# author, read only when declared on the paragraph or a descendant it wholly
# consists of.
_CATEGORY_ITEMPROP = "articlesection"
_AUTHOR_ITEMPROP = "author"

_TAG_REL_TOKEN = "tag"


class CardFieldParagraphs:
    """A card's paragraphs, sorted into category/tag, body, and byline/meta."""

    __slots__ = ("tag", "body", "meta")

    def __init__(self, tag: list[Tag], body: list[Tag], meta: list[Tag]) -> None:
        self.tag = tag
        self.body = body
        self.meta = meta


def _tokens(value: object) -> frozenset[str]:
    if isinstance(value, list):
        return frozenset(str(item).casefold() for item in value)
    if isinstance(value, str):
        return frozenset(token.casefold() for token in value.split())
    return frozenset()


def _carries_own_marker(element: Tag, class_tokens: frozenset[str], itemprop: str) -> bool:
    """Whether `element` itself — not a descendant — declares the role."""

    if _tokens(element.get("class")) & class_tokens:
        return True
    return str(element.get("itemprop") or "").casefold() == itemprop


def _is_only_marked_descendant(
    paragraph: Tag, class_tokens: frozenset[str], itemprop: str, *, rel_token: str | None = None
) -> bool:
    """Whether the paragraph's entire text comes from one marked descendant.

    A paragraph that nests a marked element alongside other prose (`Read our
    <a rel="tag">Design</a> roundup`) is not a pure category paragraph — the
    mixed content stays body, which is why this requires the descendant's
    text to account for the paragraph's whole text, the same test
    `_is_only_a_link` in `html_ownership` applies to call-to-action anchors.
    """

    text = paragraph.get_text(" ", strip=True)
    if not text:
        return False
    for descendant in paragraph.find_all(True):
        marked = _carries_own_marker(descendant, class_tokens, itemprop)
        if not marked and rel_token is not None and descendant.name == "a":
            marked = rel_token in _tokens(descendant.get("rel"))
        if marked and descendant.get_text(" ", strip=True) == text:
            return True
    return False


def _paragraph_role(paragraph: Tag) -> str | None:
    """Return 'tag', 'meta', or None (ambiguous — stays body) for one paragraph.

    A paragraph carrying both markers at once (`class="category byline"`) is
    not evidence of either role specifically — it is evidence the author
    reused a name, and guessing which one applies would misclassify the
    paragraph as confidently as it would if the classes meant nothing at all.
    """

    own_category = _carries_own_marker(paragraph, _CATEGORY_CLASS_TOKENS, _CATEGORY_ITEMPROP)
    own_meta = _carries_own_marker(paragraph, _BYLINE_CLASS_TOKENS, _AUTHOR_ITEMPROP)
    if own_category and own_meta:
        return None
    if own_category:
        return "tag"
    if own_meta:
        return "meta"
    if _is_only_marked_descendant(
        paragraph, _CATEGORY_CLASS_TOKENS, _CATEGORY_ITEMPROP, rel_token=_TAG_REL_TOKEN
    ):
        return "tag"
    if _is_only_marked_descendant(paragraph, _BYLINE_CLASS_TOKENS, _AUTHOR_ITEMPROP):
        return "meta"
    return None


def classify_card_paragraphs(paragraphs: list[Tag]) -> CardFieldParagraphs:
    """Sort a card's `<p>` elements into `tag`, `body`, and `meta`, in order.

    A paragraph's explicit role — a category class, a `rel="tag"` link, a
    byline marker — always wins. Only when a paragraph carries none of those
    does the existing publication-date reading apply, and only for the first
    such paragraph: the same "one date badge, not several" rule
    `enrich_section_from_static_dom` already applied before this helper
    existed. Everything else, including a card with no markers at all,
    reads as body copy, exactly as before.
    """

    tag: list[Tag] = []
    body: list[Tag] = []
    meta: list[Tag] = []
    date_claimed = False
    for paragraph in paragraphs:
        role = _paragraph_role(paragraph)
        if role == "tag":
            tag.append(paragraph)
            continue
        if role == "meta":
            meta.append(paragraph)
            continue
        if not date_claimed and is_publication_date(paragraph.get_text(" ", strip=True)):
            tag.append(paragraph)
            date_claimed = True
            continue
        body.append(paragraph)
    return CardFieldParagraphs(tag=tag, body=body, meta=meta)
