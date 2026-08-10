"""Static HTML section boundaries, roles, interactions, and relationship repair."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pydantic import JsonValue

from vanjaro_cli.migration.sections import dated_card_kind, has_form_fields


STABLE_NAV_MIN_LINKS = 2

_INTERACTION_SELECTORS = {
    "accordion": "details, .accordion, [data-accordion]",
    "tabs": '[role="tablist"], .tabs, .tab-list, [data-tabs]',
    "carousel": '.carousel, .slider, [data-ride="carousel"], [data-bs-ride="carousel"]',
    "menu": "nav",
    "video_embed": 'video, iframe[src*="youtube"], iframe[src*="vimeo"]',
    "form": "form",
    "modal_trigger": (
        '[data-toggle="modal"], [data-bs-toggle="modal"], '
        '[aria-haspopup="dialog"]'
    ),
}


def css_selector_for(element: Tag) -> str | None:
    """Return the shortest stable selector supported by static provenance."""

    data_id = element.get("data-id")
    if (
        isinstance(data_id, str)
        and data_id.strip()
        and element.has_attr("data-element_type")
    ):
        escaped = data_id.strip().replace("\\", "\\\\").replace("'", "\\'")
        return f"[data-id='{escaped}']"
    element_id = element.get("id")
    if isinstance(element_id, str) and element_id.strip():
        return f"#{element_id.strip()}"
    data_id = element.get("data-id")
    if isinstance(data_id, str) and data_id.strip():
        escaped = data_id.strip().replace("\\", "\\\\").replace("'", "\\'")
        return f"[data-id='{escaped}']"
    return _structural_selector(element)


def _structural_selector(element: Tag) -> str | None:
    """Locate an element by position when it names itself no other way.

    A real page's sections carry no id, so provenance recorded nothing and the
    browser had no way to find the element the static extractor had chosen.
    Rendered measurement then paired with nothing on every real site.

    An `nth-of-type` chain is stable across the only span it is used for: the
    static parse and the render happen on the same HTML.
    """

    steps: list[str] = []
    node = element
    while isinstance(node, Tag) and node.name not in (None, "[document]", "html"):
        parent = node.parent
        if not isinstance(parent, Tag):
            break
        siblings = parent.find_all(node.name, recursive=False)
        if node not in siblings:
            return None
        steps.append(f"{node.name}:nth-of-type({siblings.index(node) + 1})")
        node = parent
    if not steps:
        return None
    return " > ".join(reversed(steps))


def static_boundary_candidates(html: str) -> list[Tag]:
    """Find source-authored page boundaries without depending on a builder."""

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[Tag] = []
    seen: set[int] = set()

    def add(element: Tag | None) -> None:
        if not isinstance(element, Tag) or id(element) in seen:
            return
        if not element.get_text(" ", strip=True) and element.find(["img", "video"]) is None:
            return
        seen.add(id(element))
        candidates.append(element)

    for nav in soup.select("header nav, nav"):
        owner = nav.find_parent("header") or nav
        if css_selector_for(owner) and len(nav.find_all("a", href=True)) >= STABLE_NAV_MIN_LINKS:
            add(owner)
            break

    # Sectioning elements at any depth, outermost only. Requiring them to be
    # direct children of main or body missed every Vanjaro-built page: those
    # nest their sections inside layout divs and have no <main>, so this
    # returned nothing at all while the content extractor found eleven. The
    # rendered observation script had the same blind spot.
    sectioning = soup.select("section, article")
    for element in sectioning:
        if any(other is not element and other in element.parents for other in sectioning):
            continue
        add(element)
    for element in soup.select("[data-elementor-type] > [data-id][data-element_type='container']"):
        add(element)
    for element in soup.select("#Body > [id^='dnn_'], [id^='dnn_'][class*='Pane']"):
        add(element)

    positions = {id(tag): index for index, tag in enumerate(soup.find_all(True))}
    return sorted(_without_wrappers(candidates), key=lambda tag: positions.get(id(tag), 0))


def _without_wrappers(candidates: list[Tag]) -> list[Tag]:
    """Drop a candidate whose whole content is other candidates.

    The sectioning rule keeps only the outermost element, but the builder rules
    below it have no such filter, and a real DNN page put `#dnn_content` around
    three panes that were themselves candidates. Every word inside it was
    counted twice, and one boundary held the same content as three others.

    Outermost is the wrong tie-break here: the wrapper is layout and the panes
    are the sections. So the test is contribution rather than depth — a
    candidate stays if it carries any text or media of its own, and is dropped
    only when the nested candidates account for all of it.
    """

    kept: list[Tag] = []
    for element in candidates:
        nested = [
            other for other in candidates if other is not element and element in other.parents
        ]
        if not nested:
            kept.append(element)
            continue
        own_words = _normalized_words(element.get_text(" ", strip=True))
        nested_words: set[str] = set()
        nested_media: set[int] = set()
        for other in nested:
            nested_words |= _normalized_words(other.get_text(" ", strip=True))
            nested_media |= {id(node) for node in other.find_all(["img", "video"])}
        own_media = {id(node) for node in element.find_all(["img", "video"])}
        if own_words <= nested_words and own_media <= nested_media:
            continue
        kept.append(element)
    return kept


def _normalized_words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9%]+", value.casefold()))


# Content keys holding visitor-facing text. Asset keys are excluded on purpose:
# an image URL like `/Portals/0/adam/Content/hero.png` tokenizes into words that
# collide with real copy, so a section with no text at all can outscore the
# boundary that genuinely contains it.
_TEXT_CONTENT_KEYS = (
    "headings",
    "paragraphs",
    "buttons",
    "links",
    "list_items",
    "blockquotes",
    "tables",
)


def _raw_section_words(raw_section: Mapping[str, JsonValue]) -> set[str]:
    """Collect the visitor-facing words a raw section claims.

    Matching a raw section to a DOM boundary compares words, so only words a
    visitor would read may count. Including asset URLs let a text-free hero
    score against an unrelated pane on a shared path token and take the
    boundary that held the page's actual copy.
    """

    content = raw_section.get("content")
    if not isinstance(content, dict):
        return set()
    values: list[str] = []
    for key in _TEXT_CONTENT_KEYS:
        raw_values = content.get(key)
        if not isinstance(raw_values, list):
            continue
        for item in raw_values:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                values.extend(
                    str(part)
                    for name, part in item.items()
                    if isinstance(part, str) and name in {"text", "label", "citation", "title"}
                )
            elif isinstance(item, list):
                values.extend(str(cell) for cell in item if isinstance(cell, str))
    return _normalized_words(" ".join(values))


_NAVIGATION_MINIMUM_LINKS = 3
_NAVIGATION_LINK_TEXT_SHARE = 0.8


def _is_link_bar(element: Tag) -> bool:
    """Report whether a boundary is a navigation bar wearing no nav markup.

    A builder that emits its own chrome carries no `<header>` and no `<nav>`: a
    real Vanjaro page put its entire site header in a plain `<section>`, which
    then matched a CTA template that wanted a title the header does not have,
    and blocked the plan.

    What a navigation bar is, structurally, is a row of links and almost
    nothing else. The two things it is most likely to be confused with both
    fail that test: a footer carries headings and a copyright line, and a call
    to action carries the prose that makes the call.
    """

    if element.find(["h1", "h2", "h3", "h4", "h5", "h6"]) is not None:
        return False
    links = element.find_all("a", href=True)
    if len(links) < _NAVIGATION_MINIMUM_LINKS:
        return False
    total = len(element.get_text(" ", strip=True))
    if not total:
        return False
    link_text = sum(len(link.get_text(" ", strip=True)) for link in links)
    return link_text / total >= _NAVIGATION_LINK_TEXT_SHARE


def _hint_tokens(hints: str) -> set[str]:
    """Split selector and class hints into whole words.

    A substring test read `#tpl-ctas-s1` as a call to action because "ctas"
    contains "cta", and the section — a heading, an image and two paragraphs
    with no link at all — then matched a CTA template that wanted an action it
    does not have.
    """

    return set(re.split(r"[^a-z0-9]+", hints))


def _linked_thumbnails(element: Tag) -> list[Tag]:
    """Return anchors whose whole content is a picture.

    A thumbnail that goes somewhere is not a call to action — iteration 35
    already established that an action carrying no label is not the call. What
    it is, next to a heading and a paragraph, is a media feature.
    """

    return [
        anchor
        for anchor in element.find_all("a", href=True)
        if anchor.find("img") is not None and not anchor.get_text(" ", strip=True)
    ]


def media_text_split(element: Tag) -> tuple[Tag, Tag] | None:
    """Return a section's (media column, text column) when it is a two-up split.

    A real page laid a picture beside its copy in two Bootstrap columns and the
    layout was recorded as a one-column stack, so the section read `rich_text`
    and matched a template with no media field and no action — it would have
    built without its image or its button.

    Keyed on shape rather than on column classes: a container whose element
    children are exactly two blocks, one carrying the pictures and the other
    carrying the words. A block holding both is one column of mixed content,
    not half of a split.
    """

    # One picture beside one block of copy. Without this the inner row of a
    # four-card grid matched, and so did a stacked media feature carrying a
    # mascot and a thumbnail.
    if len(element.find_all("img")) != 1:
        return None
    section_text = len(element.get_text(" ", strip=True))
    for container in element.find_all(True):
        columns = [child for child in container.find_all(True, recursive=False)]
        if len(columns) != 2:
            continue
        media = [column for column in columns if column.find("img") is not None]
        worded = [column for column in columns if len(column.get_text(" ", strip=True)) > 40]
        if len(media) != 1 or len(worded) != 1 or media[0] is worded[0]:
            continue
        # The row has to be the section's content, not one band inside it.
        paired = len(columns[0].get_text(" ", strip=True)) + len(columns[1].get_text(" ", strip=True))
        if section_text and paired < section_text * 0.9:
            continue
        return media[0], worded[0]
    return None


def static_role(element: Tag, section_index: int) -> str:
    """Classify a boundary from semantic structure and stable source hints."""

    selector = (css_selector_for(element) or "").casefold()
    classes = " ".join(element.get("class", [])).casefold()
    text = element.get_text(" ", strip=True).casefold()
    hints = f"{selector} {classes}"
    if element.name in {"header", "nav"} or element.find("nav") is not None:
        return "navigation"
    if _is_link_bar(element):
        return "navigation"
    if "testimonial" in hints or element.find("blockquote") is not None:
        return "testimonials"
    if "stats" in hints or len(element.select("li strong")) >= 2:
        return "stats"
    if "process" in hints or ("process" in text[:80] and len(element.select(".elementor-column")) >= 2):
        return "process_steps"
    repeat_articles = element.find_all("article")
    if len(repeat_articles) >= 2:
        if any(token in hints for token in ("project", "gallery", "portfolio", "loop")):
            return "project_gallery"
        # `<article>` is the element a blog post is written in, so reading a row
        # of them as feature cards takes the tag for the kind of thing. When the
        # articles carry publication dates they say what they are.
        return dated_card_kind(repeat_articles) or "feature_cards"
    if "hero" in _hint_tokens(hints) or (element.find("h1") is not None and section_index <= 1):
        return "hero"
    if "cta" in _hint_tokens(hints):
        return "call_to_action"
    if (
        element.find("a", href=re.compile(r"^mailto:")) is not None
        or element.find("form") is not None
        # A form needs no `<form>` element: one that posts over XHR emits none,
        # and its section read as a call to action and would have been rebuilt
        # as a lookalike banner. Forms are never rebuilt as HTML.
        or has_form_fields(element)
    ):
        return "contact"
    if element.find("img") is not None and element.find("ul") is not None:
        return "split_feature"
    if media_text_split(element) is not None:
        return "split_media"
    # One linked thumbnail beside a heading and copy. Several of them is a
    # gallery, and a card grid's links carry their own labels, so neither
    # reaches here.
    if len(_linked_thumbnails(element)) == 1 and element.find(["h1", "h2", "h3", "h4"]) is not None:
        return "video_feature"
    if element.find("img") is not None and not text:
        # A band with a picture and no words at all is a photo band. Falling
        # through to rich text gave it a template whose body is required, which
        # a section carrying no text can never satisfy.
        return "photo_band"
    actions = [
        action
        for action in element.find_all("a", href=True)
        # An action with no label is not the call. A media block whose thumbnail
        # is wrapped in a link otherwise reads as a call to action, and then
        # matches a template that requires an action it cannot fill.
        if action.get_text(" ", strip=True)
    ]
    if len(actions) == 1 and len(element.find_all(["h1", "h2", "h3"])) == 1 and len(text) < 180:
        return "call_to_action"
    if "contact" in hints:
        return "contact"
    return "rich_text"


_FOOTER_MINIMUM_LINKS = 3
# The footer is last, or second to last behind a copyright bar.
_FOOTER_SEARCH_DEPTH = 2
_FOOTER_MINIMUM_HEADINGS = 2


def _is_footer(element: Tag) -> bool:
    """Report whether a trailing boundary is the page footer.

    `<footer>` is excluded from boundary discovery already, so this only ever
    sees a builder that used a plain `<section>` — as a real Vanjaro page does
    for both its chrome. The header was fixed in VF-218 and the footer was left
    matching CTA templates that want a title it does not have.

    Shape, not position alone: a footer is column headings over link lists,
    which is why it fails the link-bar test that catches the header. Position
    is still required — the caller only offers trailing candidates — because a
    services grid has the same shape in the middle of a page.
    """

    if element.name in {"header", "nav"}:
        return False
    if element.find(["h1", "h2", "h3"]) is not None:
        # A section heading means the block is part of the page's argument. A
        # footer labels its columns, and labels are small.
        return False
    headings = element.find_all(["h4", "h5", "h6"])
    links = element.find_all("a", href=True)
    return len(headings) >= _FOOTER_MINIMUM_HEADINGS and len(links) >= _FOOTER_MINIMUM_LINKS


def _trailing_footer(candidates: Sequence[Tag]) -> Tag | None:
    """Return the last candidate that reads as the page footer, if any.

    Only one: two footer sections make `split_global_sections` report
    conflicting variants and block, which is worse than leaving a copyright
    bar in the body where it does no harm.
    """

    for element in reversed(candidates[-_FOOTER_SEARCH_DEPTH:]):
        if _is_footer(element):
            return element
    return None


def prepare_static_sections(
    html: str, sections: Sequence[Mapping[str, JsonValue]]
) -> list[dict[str, JsonValue]]:
    """Attach stable DOM provenance and subtrees to legacy extraction output."""

    candidates = static_boundary_candidates(html)
    # Roles are keyed on document order, not on position within the shrinking
    # candidate pool: `section_index` means "how far down the page", and a
    # pool-relative index makes it drift as earlier candidates are claimed.
    roles = {id(tag): static_role(tag, index) for index, tag in enumerate(candidates)}
    footer = _trailing_footer(candidates)
    if footer is not None:
        roles[id(footer)] = "footer"
    remaining = list(candidates)
    prepared: list[dict[str, JsonValue]] = []
    claimed_chrome: set[int] = set()
    for raw in sections:
        raw_words = _raw_section_words(raw)
        scored = [
            (len(raw_words & _normalized_words(tag.get_text(" ", strip=True))), -index, tag)
            for index, tag in enumerate(remaining)
        ]
        match = max(scored, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]
        copy = dict(raw)
        if isinstance(match, Tag):
            remaining.remove(match)
            role = roles[id(match)]
            if role in _CHROME_ROLES:
                # The extractor emitted this chrome as an ordinary section.
                # Withholding the candidate instead would leave that section
                # to match some other subtree, which is how a header came to
                # wear the footer's DOM.
                claimed_chrome.add(id(match))
                copy = _chrome_section(match, role)
            else:
                copy["_static_selector"] = css_selector_for(match)
                copy["_static_html"] = str(match)
                copy["_static_role"] = role
        prepared.append(copy)

    for element in reversed(candidates):
        role = roles[id(element)]
        if role not in _CHROME_ROLES or id(element) in claimed_chrome:
            continue
        if role == "navigation":
            prepared.insert(0, _chrome_section(element, role))
        else:
            prepared.append(_chrome_section(element, role))
    return prepared


_CHROME_ROLES = frozenset({"navigation", "footer"})

_CHROME_TEMPLATES = {"navigation": "Site Header", "footer": "Site Footer"}


def _chrome_section(element: Tag, role: str) -> dict[str, JsonValue]:
    return {
        "type": role,
        "template": _CHROME_TEMPLATES[role],
        "content": {},
        "_static_selector": css_selector_for(element),
        "_static_html": str(element),
        "_static_role": role,
    }


def _section_search_text(raw_section: Mapping[str, JsonValue]) -> str:
    content = raw_section.get("content")
    if not isinstance(content, dict):
        return ""
    values: list[str] = []
    for key in ("headings", "paragraphs", "buttons", "links"):
        raw_values = content.get(key)
        if not isinstance(raw_values, list):
            continue
        for value in raw_values:
            if isinstance(value, dict):
                text = value.get("text") or value.get("label")
                if text:
                    values.append(str(text))
            elif value:
                values.append(str(value))
    return " ".join(values).casefold()


def interaction_kinds_by_section(
    html: str, raw_sections: Sequence[Mapping[str, JsonValue]]
) -> dict[int, tuple[str, ...]]:
    """Associate static interactive controls with extracted sections."""

    soup = BeautifulSoup(html, "html.parser")
    candidates = [
        element
        for element in soup.find_all(["section", "article"])
        if element.find_parent(["section", "article"]) is None
        and element.find_parent(["header", "footer", "dialog"]) is None
    ]
    result_lists: dict[int, list[str]] = {}
    section_texts = [_section_search_text(section) for section in raw_sections]

    def find_target(kind: str, candidate: Tag) -> int | None:
        if not raw_sections:
            return None
        if kind == "menu":
            return 0
        for index, raw_section in enumerate(raw_sections):
            section_type = raw_section.get("type")
            content = raw_section.get("content")
            if kind == "accordion" and section_type == "faq":
                return index
            if kind == "form" and (
                section_type == "contact"
                or isinstance(content, dict) and content.get("form_fields")
            ):
                return index
            if kind == "video_embed" and isinstance(content, dict) and content.get("videos"):
                return index
        candidate_text = candidate.get_text(" ", strip=True).casefold()
        if candidate_text:
            for index, section_text in enumerate(section_texts):
                if candidate_text in section_text or section_text in candidate_text:
                    return index
        return min(candidates.index(candidate), len(raw_sections) - 1)

    for candidate in candidates:
        for kind, selector in _INTERACTION_SELECTORS.items():
            if candidate.select_one(selector) is not None:
                target = find_target(kind, candidate)
                if target is not None:
                    result_lists.setdefault(target, []).append(kind)
    if raw_sections and soup.find("nav") is not None:
        result_lists.setdefault(0, []).append("menu")
    return {
        index: tuple(dict.fromkeys(kinds))
        for index, kinds in result_lists.items()
    }


def append_missing_video_sections(
    html: str,
    source_url: str,
    sections: list[dict],
) -> None:
    """Retain media-only sections the legacy text-first detector omits."""

    existing_sources = {
        str(video.get("src"))
        for section in sections
        for video in (
            section.get("content", {}).get("videos", [])
            if isinstance(section.get("content"), dict)
            else []
        )
        if isinstance(video, dict) and video.get("src")
    }
    soup = BeautifulSoup(html, "html.parser")
    missing: list[dict[str, JsonValue]] = []
    for video in soup.find_all("video"):
        source = video.get("src")
        if not source:
            nested = video.find("source", src=True)
            source = nested.get("src") if nested else None
        if source:
            absolute = urljoin(source_url, str(source))
            if absolute not in existing_sources:
                missing.append({"type": "native", "src": absolute})
                existing_sources.add(absolute)
    for iframe in soup.find_all("iframe", src=True):
        source = urljoin(source_url, str(iframe.get("src")))
        if ("youtube" in source or "vimeo" in source) and source not in existing_sources:
            missing.append({"type": "embed", "src": source})
            existing_sources.add(source)
    if missing:
        sections.append(
            {
                "type": "content",
                "template": "Rich Text Block",
                "content": {
                    "headings": [],
                    "paragraphs": [],
                    "images": [],
                    "links": [],
                    "buttons": [],
                    "list_items": [],
                    "blockquotes": [],
                    "tables": [],
                    "videos": missing,
                    "form_fields": [],
                    "form_action": "",
                },
            }
        )


def enrich_faq_relationships(html: str, sections: list[dict]) -> None:
    """Recover question/answer ownership from semantic ``details`` markup."""

    faq_sections = [section for section in sections if section.get("type") == "faq"]
    if not faq_sections:
        return
    soup = BeautifulSoup(html, "html.parser")
    faq_candidates = [
        element
        for element in soup.find_all(["section", "article", "div"])
        if len(element.find_all("details", recursive=True)) >= 2
        and not any(
            len(parent.find_all("details", recursive=True)) >= 2
            for parent in element.find_parents(["section", "article", "div"])
        )
    ]
    for raw_section, candidate in zip(faq_sections, faq_candidates):
        content = raw_section.get("content")
        if not isinstance(content, dict):
            continue
        details = candidate.find_all("details")
        questions = [
            summary.get_text(" ", strip=True)
            for detail in details
            if (summary := detail.find("summary")) is not None
        ]
        answers = [
            " ".join(
                text
                for text in (
                    child.get_text(" ", strip=True)
                    for child in detail.find_all(["p", "div"], recursive=False)
                )
                if text
            )
            for detail in details
        ]
        if len(questions) != len(answers) or not questions:
            continue
        existing_headings = content.get("headings")
        section_title = (
            [existing_headings[0]]
            if isinstance(existing_headings, list) and existing_headings
            else []
        )
        content["headings"] = section_title + questions
        content["paragraphs"] = answers


__all__ = [
    "STABLE_NAV_MIN_LINKS",
    "append_missing_video_sections",
    "css_selector_for",
    "enrich_faq_relationships",
    "interaction_kinds_by_section",
    "prepare_static_sections",
    "static_boundary_candidates",
    "static_role",
]
