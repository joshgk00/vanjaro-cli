"""Section detection, classification, and content extraction."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

__all__ = [
    "extract_sections",
    "extract_page_title",
    "extract_global_element",
    "collect_image_urls",
    "TEMPLATE_MAP",
]

TEMPLATE_MAP: dict[str, str] = {
    "hero": "Hero (Centered)",
    "cards": "Feature Cards (3-up)",
    "testimonial": "Testimonial (Single)",
    "cta": "CTA Banner",
    "header": "Site Header",
    "footer": "Site Footer",
    "content": "Rich Text Block",
}


def extract_page_title(soup: BeautifulSoup) -> str:
    """Return the page title from <title> or the first <h1>."""
    if soup.title:
        text = soup.title.get_text(strip=True)
        if text:
            return text
    first_h1 = soup.find("h1")
    if first_h1:
        return first_h1.get_text(strip=True)
    return ""


def _top_level_sections(soup: BeautifulSoup) -> list[Tag]:
    """Return the top-level structural children of <main> or <body>."""
    container = soup.find("main") or soup.body
    if not container:
        return []

    sections: list[Tag] = []
    for child in container.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue
        if child.name in ("script", "style", "noscript"):
            continue
        sections.append(child)

    # If the top level is thin (e.g., one wrapper div), descend one level
    if len(sections) == 1 and sections[0].name in ("div", "article"):
        inner = [
            c for c in sections[0].find_all(recursive=False)
            if isinstance(c, Tag) and c.name not in ("script", "style", "noscript")
        ]
        if len(inner) > 1:
            sections = inner

    return sections


def _extract_content(element: Tag, base_url: str) -> dict:
    """Pull headings, paragraphs, images, links, and buttons from an element."""
    headings: list[str] = []
    for level in ("h1", "h2", "h3", "h4"):
        for tag in element.find_all(level):
            text = tag.get_text(strip=True)
            if text:
                headings.append(text)

    paragraphs = [
        tag.get_text(strip=True)
        for tag in element.find_all("p")
        if tag.get_text(strip=True)
    ]

    images: list[dict] = []
    for img in element.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        images.append({
            "src": urljoin(base_url, src),
            "alt": img.get("alt", ""),
        })

    buttons: list[dict] = []
    for btn in element.find_all("button"):
        text = btn.get_text(strip=True)
        if text:
            buttons.append({"text": text, "href": ""})
    for anchor in element.find_all("a"):
        classes = " ".join(anchor.get("class", []))
        if "btn" not in classes and "button" not in classes:
            continue
        text = anchor.get_text(strip=True)
        raw_href = (anchor.get("href") or "").strip()
        if not text or not raw_href:
            continue
        buttons.append({"text": text, "href": urljoin(base_url, raw_href)})

    links: list[dict] = []
    for anchor in element.find_all("a", href=True):
        classes = " ".join(anchor.get("class", []))
        if "btn" in classes or "button" in classes:
            continue
        text = anchor.get_text(strip=True)
        if text:
            links.append({"text": text, "href": urljoin(base_url, anchor["href"])})

    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "images": images,
        "links": links,
        "buttons": buttons,
    }


def _classify_section(element: Tag, content: dict, is_first: bool) -> str:
    """Heuristically label the section type."""
    role = element.get("role", "")
    tag_name = element.name or ""
    classes = " ".join(element.get("class", [])).lower()

    if tag_name == "header" or role == "banner" or "header" in classes:
        return "header"
    if tag_name == "footer" or role == "contentinfo" or "footer" in classes:
        return "footer"

    if element.find("blockquote") or "testimonial" in classes or "quote" in classes:
        return "testimonial"

    has_big_heading = bool(content["headings"])
    has_cta = bool(content["buttons"])

    if is_first and has_big_heading and has_cta:
        return "hero"

    # Cards: ≥3 repeated child blocks each containing heading/image
    child_blocks = [
        c for c in element.find_all(recursive=False)
        if isinstance(c, Tag) and c.name in ("div", "article", "li")
    ]
    if len(child_blocks) == 1 and child_blocks[0].name in ("div", "ul", "ol"):
        child_blocks = [
            c for c in child_blocks[0].find_all(recursive=False)
            if isinstance(c, Tag)
        ]
    repeated = [
        c for c in child_blocks
        if c.find(["h2", "h3", "h4"]) or c.find("img")
    ]
    if len(repeated) >= 3:
        return "cards"

    # CTA: short (one heading + one button) with little else
    if (
        len(content["headings"]) <= 1
        and len(content["buttons"]) >= 1
        and len(content["paragraphs"]) <= 2
    ):
        return "cta"

    return "content"


def extract_sections(html: str, base_url: str) -> list[dict]:
    """
    Extract sections from a page's HTML.

    Each result dict has `type`, `template`, and `content` keys.
    """
    soup = BeautifulSoup(html, "html.parser")
    top_level = _top_level_sections(soup)

    sections: list[dict] = []
    for index, element in enumerate(top_level):
        content = _extract_content(element, base_url)
        # Skip empty wrappers
        if not any(content.values()):
            continue
        section_type = _classify_section(element, content, is_first=index == 0)
        sections.append({
            "type": section_type,
            "template": TEMPLATE_MAP.get(section_type, TEMPLATE_MAP["content"]),
            "content": content,
        })
    return sections


def extract_global_element(html: str, base_url: str, element_name: str) -> dict | None:
    """Extract the first <header> or <footer> from HTML as a section dict."""
    soup = BeautifulSoup(html, "html.parser")
    element = soup.find(element_name)
    if not element:
        return None
    content = _extract_content(element, base_url)
    return {
        "type": element_name,
        "template": TEMPLATE_MAP.get(element_name, TEMPLATE_MAP["content"]),
        "content": content,
    }


def collect_image_urls(page_sections: list[dict]) -> list[str]:
    """Collect unique image URLs referenced across a page's sections."""
    seen: set[str] = set()
    ordered: list[str] = []
    for section in page_sections:
        for image in section.get("content", {}).get("images", []):
            src = image.get("src")
            if src and src not in seen:
                seen.add(src)
                ordered.append(src)
    return ordered
