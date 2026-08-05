"""Static HTML section boundaries, roles, interactions, and relationship repair."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pydantic import JsonValue


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
    return None


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

    for element in soup.select("main > section, main > article, body > section, [role='main'] > section"):
        add(element)
    for element in soup.select("[data-elementor-type] > [data-id][data-element_type='container']"):
        add(element)
    for element in soup.select("#Body > [id^='dnn_'], [id^='dnn_'][class*='Pane']"):
        add(element)

    positions = {id(tag): index for index, tag in enumerate(soup.find_all(True))}
    return sorted(candidates, key=lambda tag: positions.get(id(tag), 0))


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


def static_role(element: Tag, section_index: int) -> str:
    """Classify a boundary from semantic structure and stable source hints."""

    selector = (css_selector_for(element) or "").casefold()
    classes = " ".join(element.get("class", [])).casefold()
    text = element.get_text(" ", strip=True).casefold()
    hints = f"{selector} {classes}"
    if element.name in {"header", "nav"} or element.find("nav") is not None:
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
        return "feature_cards"
    if "hero" in hints or (element.find("h1") is not None and section_index <= 1):
        return "hero"
    if "cta" in hints:
        return "call_to_action"
    if element.find("a", href=re.compile(r"^mailto:")) is not None or element.find("form") is not None:
        return "contact"
    if element.find("img") is not None and element.find("ul") is not None:
        return "split_feature"
    actions = element.find_all("a", href=True)
    if len(actions) == 1 and len(element.find_all(["h1", "h2", "h3"])) == 1 and len(text) < 180:
        return "call_to_action"
    if "contact" in hints:
        return "contact"
    return "rich_text"


def prepare_static_sections(
    html: str, sections: Sequence[Mapping[str, JsonValue]]
) -> list[dict[str, JsonValue]]:
    """Attach stable DOM provenance and subtrees to legacy extraction output."""

    candidates = static_boundary_candidates(html)
    remaining = list(candidates)
    prepared: list[dict[str, JsonValue]] = []
    for raw in sections:
        raw_words = _raw_section_words(raw)
        scored = [
            (len(raw_words & _normalized_words(tag.get_text(" ", strip=True))), -index, tag)
            for index, tag in enumerate(remaining)
            if static_role(tag, index) != "navigation"
        ]
        match = max(scored, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]
        copy = dict(raw)
        if isinstance(match, Tag):
            remaining.remove(match)
            copy["_static_selector"] = css_selector_for(match)
            copy["_static_html"] = str(match)
            copy["_static_role"] = static_role(match, len(prepared))
        prepared.append(copy)

    nav_candidates = [tag for tag in candidates if static_role(tag, 0) == "navigation"]
    for nav in reversed(nav_candidates):
        prepared.insert(0, {
            "type": "navigation",
            "template": "Site Header",
            "content": {},
            "_static_selector": css_selector_for(nav),
            "_static_html": str(nav),
            "_static_role": "navigation",
        })
    return prepared


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
