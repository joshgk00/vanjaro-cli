"""Recover source-faithful semantic ownership from static HTML subtrees."""

from __future__ import annotations

from collections.abc import Mapping
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pydantic import JsonValue

from vanjaro_cli.design.html_primitives import (
    content_element as _element,
    layout_for_section as _layout_for_section,
    register_asset as _register_asset,
)
from vanjaro_cli.design.html_boundaries import media_text_split
from vanjaro_cli.design.models import BreakpointName, Viewport
from vanjaro_cli.migration.sections import (
    extract_form_fields,
    has_form_fields,
    is_publication_date,
    is_stat_value,
    normalize_text_blocks,
)


CANONICAL_VIEWPORTS: dict[BreakpointName, Viewport] = {
    BreakpointName.DESKTOP: Viewport(width=1440, height=900),
    BreakpointName.TABLET: Viewport(width=768, height=1024),
    BreakpointName.MOBILE: Viewport(width=390, height=844),
}


_INLINE_TAGS = frozenset(
    {
        "a", "abbr", "b", "br", "button", "cite", "code", "em", "i", "img",
        "input", "label", "p", "picture", "path", "small", "source", "span",
        "strong", "svg", "time", "h1", "h2", "h3", "h4", "h5", "h6",
    }
)


def _signature(element: Tag) -> tuple[str, tuple[str, ...]]:
    classes = element.get("class") or []
    return element.name, tuple(sorted(str(value) for value in classes))


def _depth(element: Tag, root: Tag) -> int:
    depth = 0
    parent = element.parent
    while isinstance(parent, Tag) and parent is not root:
        depth += 1
        parent = parent.parent
    return depth


# Sections that are a grid of repeated cards, and what each grid's cards are.
# They are read identically — picture, heading, line of text — and differ only
# in the kind of thing repeated, which decides the templates they can reach.
_CARD_GRID_REPEAT_KIND = {
    "feature_cards": "card",
    "gallery": "card",
    "project_gallery": "card",
    "team_grid": "team_member",
    "blog_cards": "blog_post",
}


def repeating_subtrees(root: Tag, *, minimum: int = 2) -> list[Tag]:
    """Find repeated card-shaped subtrees when no card vocabulary applies.

    Discovery by `<article>` or `.card` only finds cards in builders that
    happen to use those names. A Vanjaro page emits Bootstrap columns and has
    neither, so a four-card section produced no groups at all and every
    `item.*` field went unbound. What survives every builder is the repetition
    itself.

    Grouping by tag and class signature rather than by parent is deliberate:
    the cards on a real page were split across two `.row` containers, and a
    single-parent scan would have found two groups of two.

    The most repeated signature wins, and outermost only breaks a tie. Ranking
    by depth first took whatever shallow wrapper happened to repeat: a services
    grid had two `div.White` bands holding one picture and six, which is not a
    repetition of anything, and six `div.col-sm-4` cards one level down. Reading
    the bands as the cards kept two items and discarded the rest of the section.
    A tie on count still prefers the outermost, so the card is still the card
    rather than the rounded box inside it.
    """

    by_signature: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
    for element in root.find_all(True):
        if element.name in _INLINE_TAGS:
            continue
        if element.find(["h1", "h2", "h3", "h4", "h5", "h6"]) is None and element.find("img") is None:
            continue
        by_signature.setdefault(_signature(element), []).append(element)

    ranked: list[tuple[int, int, list[Tag]]] = []
    for group in by_signature.values():
        if len(group) < minimum:
            continue
        if any(item is not other and item in other.parents for item in group for other in group):
            continue
        ranked.append((-len(group), _depth(group[0], root), group))
    if not ranked:
        return []
    return min(ranked, key=lambda entry: entry[:2])[2]


# A photo band has no words, so its picture is the band, not an
# illustration beside one — and only `background_media` reaches the slot
# that fills a full-bleed band.
_IMAGE_ROLE_BY_SECTION = {"hero": "hero_media", "photo_band": "background_media"}

_TITLE_MAXIMUM_CHARACTERS = 80

# A repeated item's title is whatever heading the builder used for it.
_HEADING_LEVELS = ["h2", "h3", "h4", "h5", "h6"]

# Narrower than _INLINE_TAGS, which exists to keep card discovery off leaf
# nodes. A paragraph is a text block even though it is never a card.
_PHRASING_TAGS = frozenset(
    {
        "a", "abbr", "b", "br", "button", "cite", "code", "em", "i", "img",
        "input", "label", "picture", "path", "small", "source", "span",
        "strong", "svg", "time",
    }
)


def _text_blocks(root: Tag) -> list[Tag]:
    """Return the innermost block-level elements that carry text."""

    blocks = [
        element
        for element in root.find_all(True)
        if element.name not in _PHRASING_TAGS and element.get_text(strip=True)
    ]
    return [
        element
        for element in blocks
        if not any(other is not element and other in element.descendants for other in blocks)
    ]


def implied_title(root: Tag) -> Tag | None:
    """Find the block a reader would take as the title when no heading exists.

    A builder can style a plain div to look like a heading, and often does — a
    real hero band carried `MUSIC FOR EVERYONE` in a div of two spans, so the
    section reported body copy, no title, and blocked on a required field.

    The rule is positional rather than a guess at class names: the first
    text-bearing block in the section, short enough to be a title, with more
    text after it. A section that is only one block has no title to promote,
    and a long first block is prose.
    """

    blocks = _text_blocks(root)
    if len(blocks) < 2:
        return None
    first = blocks[0]
    if len(first.get_text(" ", strip=True)) > _TITLE_MAXIMUM_CHARACTERS:
        return None
    return first


def _is_only_a_link(paragraph: Tag) -> bool:
    """Report whether a block's whole content is one link.

    `<p><a href="/post">Read More</a></p>` is a link, and a page of blog cards
    has six of them. Reading the paragraph as body copy and the anchor as a call
    to action put the same six words in the document twice, once with the
    destination and once without.

    The action keeps it, because the action carries where it goes.
    """

    link = paragraph.find("a", href=True)
    if link is None:
        return False
    text = paragraph.get_text(" ", strip=True)
    return bool(text) and text == link.get_text(" ", strip=True)


def _text_leaves(item: Tag) -> list[Tag]:
    return [
        element
        for element in item.find_all(True)
        if element.get_text(strip=True)
        and not any(child.get_text(strip=True) for child in element.find_all(True))
    ]


def _carries_stat_value(item: Tag) -> bool:
    """Report whether a block holds something that reads as a stat's value.

    A structural group on its own is not evidence of a stats band, and
    claiming a richer block here would drop every part of it that is neither
    value nor label.
    """

    return any(is_stat_value(leaf.get_text(" ", strip=True)) for leaf in _text_leaves(item))


def _stat_parts(item: Tag) -> tuple[Tag | None, Tag | None]:
    """Split a stat block into its value and its label.

    Looking for `<strong>` and `<span>` found neither on a real page, whose
    band carries the number in a heading and the label in a styled div. The
    value is the block that reads as a value; the label is the next text block
    that is not it.
    """

    leaves = _text_leaves(item)
    value = next(
        (leaf for leaf in leaves if is_stat_value(leaf.get_text(" ", strip=True))),
        None,
    )
    if value is None:
        # The block reached here because something already judged it a stat, so
        # its first text is the value even when it does not read like one on
        # its own. Returning nothing would drop it.
        value = leaves[0] if leaves else None
    label = next((leaf for leaf in leaves if leaf is not value), None)
    return value, label


_DECK_MAXIMUM_CHARACTERS = 80


def _deck_paragraph(title: Tag | None, paragraphs: list[Tag]) -> Tag | None:
    """Return the short line under a headline that is a deck, not body copy.

    A section read `JOIN US AT KEYS TO SUCCESS MUSIC STUDIO` over
    `and give your child the gift of music.` and then a real paragraph. Calling
    both of them body copy makes a section that needs two body slots where its
    templates own one, and loses a distinction a reader can see: the first line
    finishes the headline, the second is the copy.

    Deliberately narrow. The deck must directly follow the title, be short, and
    have real body copy after it — a lone short paragraph is body copy.
    """

    if title is None or len(paragraphs) < 2:
        return None
    first = paragraphs[0]
    if len(first.get_text(" ", strip=True)) > _DECK_MAXIMUM_CHARACTERS:
        return None
    return first if title in first.find_all_previous() else None


def _eyebrow_paragraph(title: Tag | None, paragraphs: list[Tag]) -> Tag | None:
    """Return the short line *above* a headline that is a kicker, not body copy.

    `_eyebrow_for` already recognises this part, but only when the source spells
    it as a heading. A Vanjaro page spells it `div.vj-text`, which
    `normalize_text_blocks` rewrites to a paragraph, so `Our Classes` above
    `MOST POPULAR CLASSES` arrived as body copy — and a card template that
    rightly has no body field was asked for one.

    Where the deck needs real copy after it to tell a deck from a lone short
    paragraph, position carries this on its own: body copy does not open above
    the headline it belongs to.
    """

    if title is None or not paragraphs:
        return None
    first = paragraphs[0]
    if len(first.get_text(" ", strip=True)) > _DECK_MAXIMUM_CHARACTERS:
        return None
    return first if first in title.find_all_previous() else None


def _media_side(columns: tuple[Tag, Tag] | None) -> str:
    if columns is None:
        return "left"
    media, worded = columns
    return "left" if media in worded.find_all_previous() else "right"


def _feature_media(root: Tag) -> Tag | None:
    """Return the picture a media feature is actually featuring."""

    for anchor in root.find_all("a", href=True):
        picture = anchor.find("img")
        if picture is not None and not anchor.get_text(" ", strip=True):
            return picture
    return None


def _most_prominent(headings: list[Tag]) -> Tag | None:
    """Return the heading a reader would take as the section's title.

    Document order was the whole rule, so a section led by a small eyebrow —
    `OUR MEDIA` in an `h5` above `See what our students can do` in an `h2` —
    titled itself with the eyebrow and **dropped the real heading entirely**.
    Widening the query to `h6` in VF-219 is what exposed this: before that an
    `h5` could not win, and the `h2` was picked by accident.

    Prominence is the level, and document order only breaks a tie.
    """

    if not headings:
        return None
    return min(headings, key=lambda heading: (int(heading.name[1]), headings.index(heading)))


def _eyebrow_for(title: Tag | None, headings: list[Tag]) -> Tag | None:
    """Return the smaller heading sitting above the title, if there is one.

    A kicker above a headline is a distinct editorial part, and several
    templates have a field for it. Recording it as a second `section_title`
    would make two titles; dropping it loses a line the visitor reads.
    """

    if title is None:
        return None
    for heading in headings:
        if heading is title:
            return None
        if int(heading.name[1]) > int(title.name[1]):
            return heading
    return None


def enrich_section_from_static_dom(
    section: dict[str, JsonValue],
    static_html: str,
    *,
    source_url: str,
    assets: dict[str, dict[str, JsonValue]],
    provenance: dict[str, JsonValue],
) -> None:
    """Replace lossy flat arrays with source-DOM element relationships."""

    soup = BeautifulSoup(static_html, "html.parser")
    # This pass parses the source subtree itself rather than extraction output,
    # so it needs the same normalization extraction applies to the whole page.
    normalize_text_blocks(soup)
    root = soup.find(True)
    if not isinstance(root, Tag):
        return
    section_id = str(section["id"])
    role = str(section["semantic_role"])
    if role == "faq":
        return
    elements: list[dict[str, JsonValue]] = []
    groups: list[dict[str, JsonValue]] = []
    counters: dict[str, int] = {}

    def add(
        kind: str,
        element_role: str,
        value: JsonValue,
        *,
        group_id: str | None = None,
        attributes: Mapping[str, JsonValue] | None = None,
        asset_id: str | None = None,
    ) -> str:
        key = re.sub(r"[^a-z0-9]+", "-", element_role.casefold()).strip("-") or kind
        counters[key] = counters.get(key, 0) + 1
        element_id = f"{section_id}.{key}.{counters[key]}"
        elements.append(
            _element(
                element_id,
                kind,
                element_role,
                len(elements),
                provenance,
                value=value,
                attributes=attributes,
                asset_id=asset_id,
                group_id=group_id,
                confidence=0.95,
            )
        )
        return element_id

    def image(tag: Tag, image_role: str, group_id: str | None = None) -> str | None:
        source = tag.get("src") or tag.get("data-src")
        if not isinstance(source, str) or not source:
            return None
        absolute = urljoin(source_url, source)
        asset_id = _register_asset(
            assets,
            source_url=absolute,
            alt_text=str(tag.get("alt") or ""),
            role="editorial",
            provenance=[provenance],
        )
        attributes: dict[str, JsonValue] = {"alt": str(tag.get("alt") or "")}
        # Where the picture leads, recorded on the picture. A thumbnail wrapped
        # in a link used to arrive twice — once as media and once as a call to
        # action with no text — and the anchor is not a second piece of content,
        # it is this one's destination.
        anchor = tag.find_parent("a", href=True)
        if anchor is not None:
            attributes["href"] = str(anchor.get("href"))
        return add(
            "image",
            image_role,
            absolute,
            group_id=group_id,
            attributes=attributes,
            asset_id=asset_id,
        )

    if role == "navigation":
        links = root.find_all("a", href=True)
        nav = root.find("nav")
        nav_links = nav.find_all("a", href=True) if isinstance(nav, Tag) else links
        nav_ids = {id(link) for link in nav_links}
        brand = next((link for link in links if id(link) not in nav_ids), None)
        if brand is None:
            brand = next((link for link in links if "brand" in " ".join(link.get("class", [])).casefold()), None)
        if isinstance(brand, Tag):
            add("link", "brand", brand.get_text(" ", strip=True), attributes={"href": brand.get("href")})
        group_id = f"{section_id}.navigation-items"
        items: list[dict[str, JsonValue]] = []
        for link in nav_links:
            if link is brand:
                continue
            label_id = add(
                "link",
                "navigation_item",
                link.get_text(" ", strip=True),
                group_id=group_id,
                attributes={"href": link.get("href")},
            )
            items.append({"id": f"{group_id}.{len(items) + 1}", "fields": {"label": label_id}, "provenance": [provenance]})
        if items:
            groups.append({"id": group_id, "kind": "navigation_item", "items": items, "provenance": [provenance]})
        section["layout"] = _layout_for_section("navigation", "", len(items))
        section["layout"]["kind"] = "flex"  # type: ignore[index]
    else:
        repeat_kind: str | None = None
        repeat_items: list[Tag] = []
        if role == "testimonials":
            repeat_kind = "testimonial"
            repeat_items = list(root.find_all("figure", recursive=True)) or list(root.find_all("blockquote", recursive=True))
        elif role == "stats":
            repeat_kind = "stat"
            repeat_items = [
                tag for tag in root.find_all("li") if tag.find("strong") is not None
            ] or [
                # Only blocks that actually carry a value. A structural group
                # alone is not evidence of a stat, and claiming a richer block
                # here drops every part of it that is neither value nor label.
                block
                for block in repeating_subtrees(root)
                if _carries_stat_value(block)
            ]
        elif role == "process_steps":
            repeat_kind = "other"
            repeat_items = list(root.select(".elementor-column, [class*='step']"))
        elif role in _CARD_GRID_REPEAT_KIND:
            repeat_kind = _CARD_GRID_REPEAT_KIND[role]
            repeat_items = (
                list(root.find_all("article"))
                or list(root.select(".card, .e-loop-item, .service-list > *"))
                or repeating_subtrees(root)
            )
        elif role == "split_feature":
            repeat_kind = "other"
            repeat_items = list(root.find_all("li"))

        repeated_nodes = {id(node) for item in repeat_items for node in [item, *item.find_all(True)]}
        headings = [
            heading
            for heading in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            if id(heading) not in repeated_nodes
        ]
        title = _most_prominent(headings)
        eyebrow = _eyebrow_for(title, headings)
        inferred_title = implied_title(root) if title is None else None
        if isinstance(inferred_title, Tag) and id(inferred_title) not in repeated_nodes:
            title = inferred_title
        else:
            inferred_title = None
        # `<address>` reads as body copy: it is prose a visitor reads, and
        # nothing else here looks at the tag, so contact-page's postal address
        # reached no element at all.
        body_paragraphs = [
            paragraph
            for paragraph in root.find_all(["p", "address"])
            if id(paragraph) not in repeated_nodes
            and paragraph is not inferred_title
            and not _is_only_a_link(paragraph)
        ]
        paragraph_eyebrow = _eyebrow_paragraph(title, body_paragraphs) if eyebrow is None else None
        if isinstance(title, Tag):
            attributes: dict[str, JsonValue] = {
                "level": int(title.name[1]) if title.name[0] == "h" else 2
            }
            if inferred_title is not None:
                attributes["implied"] = True
            if isinstance(eyebrow, Tag):
                add(
                    "heading",
                    "eyebrow",
                    eyebrow.get_text(" ", strip=True),
                    attributes={"level": int(eyebrow.name[1])},
                )
            elif isinstance(paragraph_eyebrow, Tag):
                # The source spelled it as copy, so there is no heading level to
                # report — the same admission `implied_title` makes.
                add(
                    "heading",
                    "eyebrow",
                    paragraph_eyebrow.get_text(" ", strip=True),
                    attributes={"implied": True},
                )
            add("heading", "section_title", title.get_text(" ", strip=True), attributes=attributes)

        # Every other heading the section owns. Only the title and one eyebrow
        # were emitted, so a subsection label — `Branding Package`, `Tags`,
        # `Gallery` — and a pull-quote written as a heading left the document
        # entirely. Nothing reported it: no plan warning names content that was
        # never extracted, and coverage cannot count what did not arrive.
        #
        # A loss the report can see is worth more than one it cannot. These bind
        # where a template offers a place for them and are named as dropped
        # where it does not, which is a question someone can answer.
        for heading in headings:
            if heading is title or heading is eyebrow:
                continue
            add(
                "heading",
                "subheading",
                heading.get_text(" ", strip=True),
                attributes={"level": int(heading.name[1])},
            )

        group_id = f"{section_id}.items"
        group_items: list[dict[str, JsonValue]] = []
        for item in repeat_items:
            fields: dict[str, JsonValue] = {}
            if role == "testimonials":
                quote = item.find("blockquote") if item.name != "blockquote" else item
                author = item.find(["cite", "figcaption"])
                if isinstance(quote, Tag):
                    quote_text = " ".join(
                        text.strip() for text in quote.stripped_strings
                        if not isinstance(author, Tag) or text.strip() != author.get_text(" ", strip=True)
                    )
                    fields["quote"] = add("quote", "testimonial_quote", quote_text, group_id=group_id)
                if isinstance(author, Tag):
                    fields["author"] = add("text", "author", author.get_text(" ", strip=True), group_id=group_id)
            elif role == "stats":
                value_tag, label_tag = _stat_parts(item)
                if isinstance(value_tag, Tag):
                    fields["value"] = add("stat", "stat_value", value_tag.get_text(" ", strip=True), group_id=group_id)
                if isinstance(label_tag, Tag):
                    fields["label"] = add("text", "stat_label", label_tag.get_text(" ", strip=True), group_id=group_id)
            elif role == "process_steps":
                heading = item.find(["h2", "h3", "h4"])
                number = next((tag for tag in item.find_all(["span", "strong"]) if re.fullmatch(r"\d+[.)]?", tag.get_text(" ", strip=True))), None)
                if isinstance(number, Tag):
                    fields["number"] = add("stat", "step_number", number.get_text(" ", strip=True), group_id=group_id)
                if isinstance(heading, Tag):
                    fields["title"] = add("heading", "step_title", heading.get_text(" ", strip=True), group_id=group_id)
            elif role in _CARD_GRID_REPEAT_KIND:
                media = item.find("img")
                # h5 and h6 included: a card's title is whatever heading the
                # builder gave it, and rendered-home writes its feature cards
                # with `<h5>`. The section-level search has read h1 through h6
                # since h5/h6 extraction was fixed for sections; the card branch
                # was never widened with it, so three card titles reached
                # nothing.
                heading = item.find(_HEADING_LEVELS)
                # The first paragraph is not the body. `normalize_text_blocks`
                # rewrites a text-bearing leaf div into a `<p>`, so a blog
                # card's date badge becomes its first paragraph — and every
                # card in cmw-blog's listing arrived carrying `Nov 13, 2017`
                # as its body while the excerpt beneath was discarded.
                paragraphs = item.find_all("p")
                published = next(
                    (
                        paragraph
                        for paragraph in paragraphs
                        if is_publication_date(paragraph.get_text(" ", strip=True))
                    ),
                    None,
                )
                body = next(
                    (paragraph for paragraph in paragraphs if paragraph is not published), None
                )
                if isinstance(media, Tag):
                    media_id = image(media, "card_media", group_id)
                    if media_id:
                        fields["media"] = media_id
                if isinstance(heading, Tag):
                    fields["title"] = add("heading", "card_title", heading.get_text(" ", strip=True), group_id=group_id)
                if isinstance(published, Tag):
                    fields["tag"] = add("text", "tag", published.get_text(" ", strip=True), group_id=group_id)
                # A card is allowed more than one paragraph. Keeping only the
                # first dropped a class card's whole description and a blog
                # card's byline.
                #
                # Every one of them is named in the item's field, which already
                # accepts a list: the planner binds as many as the template owns
                # slots for and reports the rest as `field 'X' has N values but
                # owns M physical slots`, the same string the capability report
                # ranks a section-level overflow by. Left out of the field they
                # arrived in the document and were invisible to the plan — no
                # warning, no loss, nothing for the queue to rank.
                field = "type" if role == "project_gallery" else "body"
                element_role = "eyebrow" if field == "type" else "card_body"
                body_ids = [
                    add("text", element_role, paragraph.get_text(" ", strip=True), group_id=group_id)
                    for paragraph in ([body] if isinstance(body, Tag) else [])
                    + [extra for extra in paragraphs if extra is not published and extra is not body]
                ]
                if body_ids:
                    fields[field] = body_ids[0] if len(body_ids) == 1 else body_ids
            else:
                fields["text"] = add("list_item", "benefit", item.get_text(" ", strip=True), group_id=group_id)
            if fields:
                group_items.append({"id": f"{group_id}.{len(group_items) + 1}", "fields": fields, "provenance": [provenance]})
        if repeat_kind and group_items:
            groups.append({"id": group_id, "kind": repeat_kind, "items": group_items, "provenance": [provenance]})

        feature_media = _feature_media(root) if role == "video_feature" else None
        for img in root.find_all("img"):
            if id(img) in repeated_nodes:
                continue
            if feature_media is not None and img is not feature_media:
                # The feature's picture is the one the link points at. A mascot
                # floated beside it is decoration, and counting it as editorial
                # media made a section overflow a template that holds one.
                image(img, "decorative_media")
                continue
            image(img, _IMAGE_ROLE_BY_SECTION.get(role, "section_media"))
        background_match = re.search(
            r"background(?:-image)?\s*:\s*(?:[^;]*?)url\((['\"]?)([^)'\"]+)\1\)",
            str(root.get("style") or ""),
            re.IGNORECASE,
        )
        if background_match:
            source = background_match.group(2).strip()
            absolute = urljoin(source_url, source)
            asset_id = _register_asset(
                assets,
                source_url=absolute,
                role="decorative",
                provenance=[provenance],
            )
            add(
                "image",
                "background_media",
                absolute,
                attributes={"alt": "", "decorative": True},
                asset_id=asset_id,
            )
        deck = _deck_paragraph(title, body_paragraphs)
        for paragraph in body_paragraphs:
            if paragraph is paragraph_eyebrow:
                continue
            element_role = "subtitle" if paragraph is deck else "body"
            add("text", element_role, paragraph.get_text(" ", strip=True))
        # A list item no repeat group claimed. Only the `stats` and
        # `split_feature` branches ever read an `<li>`, so a contact block's
        # telephone, email and handle survived solely because the section had
        # been misread as a stats band — and correcting that classification
        # took the list with it. A list is content whatever the section is.
        for item in root.find_all("li"):
            if id(item) in repeated_nodes or _is_only_a_link(item):
                # `<li><a href="mailto:…">info@…</a></li>` is a link, and a
                # footer contact list is several of them. The action keeps it,
                # because the action carries where it goes — the same rule the
                # paragraph sweep applies, which this list emission was added
                # beside without inheriting.
                continue
            listed = item.get_text(" ", strip=True)
            if listed:
                add("list_item", "benefit", listed)
        # Who a quote is credited to. Only the testimonials branch read a `<cite>`,
        # so the moment a section holding a pull-quote stopped being testimonials
        # its attribution left the document — "Walt Whitman" under a line of
        # Whitman. The quote itself survives as a heading; the name it belongs to
        # should not need a particular section role to be kept.
        for attribution in root.find_all(["cite", "figcaption"]):
            if id(attribution) in repeated_nodes:
                continue
            credited = attribution.get_text(" ", strip=True)
            if credited:
                add("text", "author", credited)
        # Enrichment replaces the content list wholesale, so a form inventoried
        # by extraction is lost here unless it is re-emitted. The placeholder
        # that stands in for a form is built from these, and a form nobody
        # listed is a form rebuilt as a lookalike.
        for field in extract_form_fields(root) if has_form_fields(root) else []:
            add("form_placeholder", "form_field", field.get("label") or field.get("name") or "", attributes=field)
        for link in root.find_all("a", href=True):
            if id(link) in repeated_nodes:
                continue
            # A picture wrapped in a link is one thing, not two. Its destination
            # now travels on the image, so emitting an action here as well
            # counted the same content twice and produced a call with nothing to
            # read on it.
            if link.find("img") is not None:
                continue
            # An action with no label is not the call — the rule both measurement
            # scripts have applied since iteration 55, and which the extractor
            # was never given. A social icon says what it is in `aria-label`; a
            # menu's `mm-next` says nothing anywhere, and is chrome.
            label = link.get_text(" ", strip=True) or str(
                link.get("aria-label") or link.get("title") or ""
            ).strip()
            if not label:
                continue
            kind = "button" if role in {"hero", "call_to_action"} or any("btn" in value.casefold() for value in link.get("class", [])) else "link"
            add(kind, "primary_action", label, attributes={"href": link.get("href")})

    if elements:
        section["content"] = elements
        section["groups"] = groups
    item_count = len(groups[0]["items"]) if groups else 0
    if role in _CARD_GRID_REPEAT_KIND or role == "testimonials":
        section["layout"] = {
            "kind": "grid",
            "contained": True,
            "columns": max(1, min(item_count or 3, 4)),
            "media_position": "top" if role in _CARD_GRID_REPEAT_KIND else "none",
            "alignment": "left",
            "full_bleed": False,
        }
    elif role == "stats":
        section["layout"] = {
            "kind": "stack", "contained": False, "columns": max(1, item_count),
            "media_position": "none", "alignment": "center", "full_bleed": True,
        }
    elif role == "process_steps":
        section["layout"] = {
            "kind": "stack", "contained": True, "columns": max(1, item_count),
            "media_position": "none", "alignment": "center", "full_bleed": False,
        }
    elif role in {"split_feature", "split_media"} or (role == "hero" and root.find("img") is not None):
        columns = media_text_split(root)
        section["layout"] = {
            "kind": "split", "contained": True, "columns": 2,
            # Which side the picture is on is in the source order, and a
            # mirrored build reads as a different design.
            "media_position": _media_side(columns),
            "alignment": "left", "full_bleed": False,
        }
    add_inferred_static_responsive(section, root, provenance)


_CENTERING_CLASSES = ("text-center", "text-md-center", "has-text-centered", "align-center")
_END_CLASSES = ("text-end", "text-right")
_ACTION_CLASS_HINTS = ("btn", "button", "cta")


def _static_alignment(root: Tag) -> str:
    """Derive a section's text alignment from explicit utility classes.

    Absence of a centering utility is itself evidence: the section inherits the
    document default, which is left in every supported source. Mobile keeps the
    desktop alignment unless a breakpoint rule overrides it.
    """

    classes = " ".join(root.get("class", []) or [])
    for descendant in [root, *root.find_all(True, recursive=False)]:
        classes += " " + " ".join(descendant.get("class", []) or [])
    if any(token in classes for token in _CENTERING_CLASSES):
        return "center"
    if any(token in classes for token in _END_CLASSES):
        return "right"
    return "left"


_ACTION_ROLES = {"cta", "call_to_action", "contact", "contact_cta", "hero"}


def _has_action(root: Tag, role: str) -> bool:
    """Report whether the section contains a call-to-action control.

    A styled button is unambiguous. In a section whose whole purpose is a call
    to action, an unstyled anchor is the call to action too — several builders
    emit a bare link and carry the styling on an ancestor ID.
    """

    anchors = root.find_all(["a", "button"])
    if role in _ACTION_ROLES and anchors:
        return True
    for anchor in anchors:
        classes = " ".join(anchor.get("class", []) or [])
        if any(hint in classes for hint in _ACTION_CLASS_HINTS):
            return True
        parent_classes = " ".join((anchor.parent.get("class", []) or []) if anchor.parent else [])
        if any(hint in parent_classes for hint in _ACTION_CLASS_HINTS):
            return True
    return False


def add_inferred_static_responsive(
    section: dict[str, JsonValue], root: Tag, provenance: dict[str, JsonValue]
) -> None:
    """Record conservative responsive inferences from explicit structure."""

    if section.get("responsive"):
        return
    role = str(section.get("semantic_role") or "")
    groups = section.get("groups")
    item_count = 0
    if isinstance(groups, list) and groups and isinstance(groups[0], dict):
        items = groups[0].get("items")
        item_count = len(items) if isinstance(items, list) else 0
    changes: dict[BreakpointName, dict[str, JsonValue]] = {}

    def record(breakpoint: BreakpointName, **values: JsonValue) -> None:
        changes.setdefault(breakpoint, {}).update(values)

    if role == "navigation" and any("navbar-expand" in value for value in root.get("class", [])):
        record(BreakpointName.MOBILE, navigation="collapsed", direction="vertical")
    elif role == "process_steps" and item_count > 1:
        record(BreakpointName.MOBILE, direction="vertical")
    elif item_count > 1 and (role in _CARD_GRID_REPEAT_KIND or role in {"testimonials", "stats"}):
        record(BreakpointName.MOBILE, columns=1)
        if item_count >= 3:
            record(BreakpointName.TABLET, columns=2)
    elif role in {"hero", "split_feature"} and root.find("img") is not None:
        record(BreakpointName.MOBILE, columns=1, media_position="top")

    # Alignment and button width are independent of the structural rules above,
    # so they are recorded additively rather than as another exclusive branch.
    # A hero can both stack its media and keep its left-aligned copy.
    if role != "navigation":
        record(BreakpointName.MOBILE, alignment=_static_alignment(root))
        if _has_action(root, role):
            # Full-width actions are the near-universal mobile treatment for a
            # section's primary call to action.
            record(BreakpointName.MOBILE, button_width="100%")
    responsive: list[dict[str, JsonValue]] = []
    for breakpoint in (BreakpointName.TABLET, BreakpointName.MOBILE):
        if breakpoint not in changes:
            continue
        inferred_provenance = {
            **provenance,
            "method": "inferred",
            "viewport": breakpoint.value,
        }
        responsive.append({
            "breakpoint": breakpoint.value,
            "viewport": CANONICAL_VIEWPORTS[breakpoint].model_dump(mode="json"),
            "status": "inferred",
            "layout_changes": changes[breakpoint],
            "style": {"observations": [], "raw": {}},
            "hidden": None,
            "provenance": [inferred_provenance],
        })
    section["responsive"] = responsive


__all__ = [
    "CANONICAL_VIEWPORTS",
    "add_inferred_static_responsive",
    "enrich_section_from_static_dom",
]
