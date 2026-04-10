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
    "contact": "Contact Section",
    "bio": "Bio / About",
    "gallery": "Gallery (3-up)",
    "blog_cards": "Blog Post Cards (3-up)",
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

    list_items: list[str] = []
    for list_tag in element.find_all(["ul", "ol"]):
        for li in list_tag.find_all("li", recursive=False):
            text = li.get_text(strip=True)
            if text:
                list_items.append(text)

    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "images": images,
        "links": links,
        "buttons": buttons,
        "list_items": list_items,
    }


def _classify_section(element: Tag, content: dict, is_first: bool) -> str:
    """Heuristically label the section type.

    The detector ladder runs most-specific to least-specific. Each
    detector below either returns a definitive type or falls through to
    the next one. The final fallback is ``content`` (Rich Text Block).
    """
    role = element.get("role", "")
    tag_name = element.name or ""
    classes = " ".join(element.get("class", [])).lower()

    if tag_name == "header" or role == "banner" or "header" in classes:
        return "header"
    if tag_name == "footer" or role == "contentinfo" or "footer" in classes:
        return "footer"

    if element.find("blockquote") or "testimonial" in classes or "quote" in classes:
        return "testimonial"

    if _looks_like_contact_form(element, classes):
        return "contact"

    if _looks_like_gallery(element):
        return "gallery"

    if _looks_like_blog_cards(element):
        return "blog_cards"

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

    if _looks_like_bio(element, content):
        return "bio"

    return "content"


def _looks_like_contact_form(element: Tag, classes: str) -> bool:
    """Detect a contact section by the presence of a real form.

    Requires:
    - A ``<form>`` element somewhere inside the section, AND
    - At least one ``<input>`` / ``<textarea>`` / ``<select>`` child of
      the form (skips empty form wrappers used for analytics tracking).

    The class-name check is a low-cost early-out for sections explicitly
    marked as a contact area when the form lives elsewhere on the page.
    """
    if any(token in classes for token in ("contact", "get-in-touch", "reach-us")):
        if element.find(["input", "textarea", "select"]):
            return True

    form = element.find("form")
    if form is None:
        return False
    return form.find(["input", "textarea", "select"]) is not None


def _looks_like_gallery(element: Tag) -> bool:
    """Detect an image gallery: ≥3 ``<a>`` elements wrapping ``<img>`` elements.

    The thumbnail-to-fullsize lightbox pattern that ashleyslaughterdesigns
    uses fits this exactly. Plain ``<img>`` grids without anchor wrappers
    are still picked up by the existing ``cards`` detector below.
    """
    anchor_image_count = 0
    for anchor in element.find_all("a"):
        if anchor.find("img"):
            anchor_image_count += 1
            if anchor_image_count >= 3:
                return True
    return False


def _looks_like_blog_cards(element: Tag) -> bool:
    """Detect a blog post grid: ≥3 children each with image + heading + ``Read More``.

    Blog post grids look superficially like the existing ``cards`` detector
    but distinguish themselves by having a "Read More" / "Continue reading"
    link in each card. Catching them earlier than ``cards`` lets the
    crawler suggest the right template (Blog Post Cards 3-up vs Feature Cards).
    """
    candidates = [
        c for c in element.find_all(recursive=False)
        if isinstance(c, Tag) and c.name in ("div", "article", "li")
    ]
    if len(candidates) == 1 and candidates[0].name in ("div", "ul", "ol"):
        candidates = [
            c for c in candidates[0].find_all(recursive=False)
            if isinstance(c, Tag)
        ]

    blog_like = 0
    for child in candidates:
        if not child.find("img"):
            continue
        if not child.find(["h2", "h3", "h4"]):
            continue
        link_texts = " ".join(
            (a.get_text(strip=True) or "").lower() for a in child.find_all("a")
        )
        if "read more" in link_texts or "continue reading" in link_texts:
            blog_like += 1
            if blog_like >= 3:
                return True
    return False


def _looks_like_bio(element: Tag, content: dict) -> bool:
    """Detect a bio / about-me split layout: one notable image + paragraph text.

    The Bio / About template is a two-column image-on-one-side, text-on-the-
    other-side layout. Heuristic: the section contains exactly one or two
    images, at least one heading, and at least two paragraphs of text. We
    use the extracted ``content`` dict (which already de-duplicates and
    filters empty values) to avoid re-walking the tree.
    """
    image_count = len(content.get("images", []))
    heading_count = len(content.get("headings", []))
    paragraph_count = len(content.get("paragraphs", []))

    if image_count not in (1, 2):
        return False
    if heading_count < 1:
        return False
    if paragraph_count < 2:
        return False
    return True


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
