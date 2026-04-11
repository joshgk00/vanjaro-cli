"""Section detection, classification, and content extraction."""

from __future__ import annotations

import re
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
    "faq": "FAQ Accordion",
    "pricing": "Pricing Cards (3-up)",
    "stats": "Stats Grid (4-up)",
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


_SRCSET_ENTRY = re.compile(r"([^\s,]+)\s+[\d.]+[wx]")
_BG_IMAGE_URL = re.compile(r"""background-image:\s*url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.IGNORECASE)


def _parse_srcset_urls(srcset: str, base_url: str) -> list[str]:
    """Parse a srcset attribute value and return resolved absolute URLs."""
    urls: list[str] = []
    for match in _SRCSET_ENTRY.finditer(srcset):
        raw = match.group(1).strip()
        if raw:
            urls.append(urljoin(base_url, raw))
    if not urls:
        # Fallback: split on commas and take the first token of each entry
        for part in srcset.split(","):
            token = part.strip().split()[0] if part.strip() else ""
            if token:
                urls.append(urljoin(base_url, token))
    return urls


def _extract_content(element: Tag, base_url: str) -> dict:
    """Pull structured content from an HTML element for migration."""
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
        entry: dict = {
            "src": urljoin(base_url, src),
            "alt": img.get("alt", ""),
        }
        srcset = img.get("srcset")
        if srcset:
            entry["srcset"] = srcset
            entry["srcset_urls"] = _parse_srcset_urls(srcset, base_url)
        sizes = img.get("sizes")
        if sizes:
            entry["sizes"] = sizes
        images.append(entry)

    for picture in element.find_all("picture"):
        img_tag = picture.find("img")
        fallback_src = ""
        fallback_alt = ""
        if img_tag:
            fallback_src = urljoin(base_url, img_tag.get("src", ""))
            fallback_alt = img_tag.get("alt", "")
        for source in picture.find_all("source"):
            srcset = source.get("srcset")
            if not srcset:
                continue
            parsed_urls = _parse_srcset_urls(srcset, base_url)
            media = source.get("media", "")
            source_type = source.get("type", "")
            images.append({
                "src": parsed_urls[0] if parsed_urls else fallback_src,
                "alt": fallback_alt,
                "srcset": srcset,
                "srcset_urls": parsed_urls,
                "media": media,
                "source_type": source_type,
                "role": "picture_source",
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

    blockquotes: list[dict] = []
    for bq in element.find_all("blockquote"):
        text = bq.get_text(strip=True)
        if not text:
            continue
        citation_tag = bq.find(["cite", "footer"])
        citation = citation_tag.get_text(strip=True) if citation_tag else ""
        quote_text = text
        if citation and quote_text.endswith(citation):
            quote_text = quote_text[: -len(citation)].strip(" \u2014\u2013-")
        blockquotes.append({"text": quote_text, "citation": citation})

    tables: list[list[list[str]]] = []
    for table in element.find_all("table"):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                cell.get_text(strip=True)
                for cell in tr.find_all(["th", "td"])
            ]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)

    videos: list[dict] = []
    for video_tag in element.find_all("video"):
        src = video_tag.get("src")
        if not src:
            source_tag = video_tag.find("source")
            src = source_tag.get("src") if source_tag else None
        if src:
            videos.append({"type": "native", "src": urljoin(base_url, src)})
    for iframe in element.find_all("iframe"):
        src = iframe.get("src")
        if src:
            videos.append({"type": "embed", "src": src})

    for figure in element.find_all("figure"):
        figcaption = figure.find("figcaption")
        caption = figcaption.get_text(strip=True) if figcaption else ""
        img = figure.find("img")
        if img and img.get("src"):
            # Find the matching image entry and add the caption
            img_src = urljoin(base_url, img["src"])
            for image_entry in images:
                if image_entry["src"] == img_src:
                    image_entry["caption"] = caption
                    break
            else:
                images.append({
                    "src": img_src,
                    "alt": img.get("alt", ""),
                    "caption": caption,
                })

    seen_bg_urls: set[str] = set()
    for tag in element.find_all(style=True):
        style = tag.get("style", "")
        for match in _BG_IMAGE_URL.finditer(style):
            raw_url = match.group(1).strip()
            if not raw_url:
                continue
            absolute_url = urljoin(base_url, raw_url)
            if absolute_url in seen_bg_urls:
                continue
            seen_bg_urls.add(absolute_url)
            images.append({
                "src": absolute_url,
                "alt": "",
                "role": "background",
            })

    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "images": images,
        "links": links,
        "buttons": buttons,
        "list_items": list_items,
        "blockquotes": blockquotes,
        "tables": tables,
        "videos": videos,
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

    if _looks_like_faq(element):
        return "faq"

    if _looks_like_pricing(element, classes):
        return "pricing"

    has_big_heading = bool(content["headings"])
    has_cta = bool(content["buttons"])

    if is_first and has_big_heading and has_cta:
        return "hero"

    if _looks_like_stats(element):
        return "stats"

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


def _direct_child_blocks(element: Tag) -> list[Tag]:
    """Return direct child block elements, unwrapping a single container div."""
    children = [
        c for c in element.find_all(recursive=False)
        if isinstance(c, Tag) and c.name in ("div", "article", "li")
    ]
    if len(children) == 1 and children[0].name in ("div", "ul", "ol"):
        children = [
            c for c in children[0].find_all(recursive=False)
            if isinstance(c, Tag)
        ]
    return children


def _looks_like_faq(element: Tag) -> bool:
    """Detect an FAQ / accordion section.

    Matches:
    - 3+ ``<details>`` elements (native HTML accordion), OR
    - 3+ children with an ``accordion-item`` or ``faq-item`` class, OR
    - 3+ children with ``accordion`` in the parent's class
    """
    if len(element.find_all("details")) >= 3:
        return True

    classes = " ".join(element.get("class", [])).lower()
    if "accordion" in classes or "faq" in classes:
        children = [
            c for c in element.find_all(recursive=False)
            if isinstance(c, Tag) and c.name not in ("script", "style")
        ]
        if len(children) >= 3:
            return True

    accordion_items = [
        child for child in _direct_child_blocks(element)
        if any(
            token in " ".join(child.get("class", [])).lower()
            for token in ("accordion-item", "faq-item", "accordion_item")
        )
    ]
    return len(accordion_items) >= 3


_CURRENCY_PATTERN = re.compile(r"[\$\u00a3\u20ac]\s*\d")
_BILLING_PATTERN = re.compile(r"/\s*(?:mo|month|yr|year|week)\b", re.IGNORECASE)


def _looks_like_pricing(element: Tag, classes: str) -> bool:
    """Detect a pricing section.

    Matches:
    - "pricing" or "plans" in the section's class names, OR
    - 3+ child blocks each containing a currency symbol followed by a digit
      (e.g. ``$10``, ``$25/mo``)
    """
    if "pricing" in classes or "plans" in classes:
        return True

    child_blocks = _direct_child_blocks(element)
    price_cards = 0
    for child in child_blocks:
        text = child.get_text()
        if _CURRENCY_PATTERN.search(text) or _BILLING_PATTERN.search(text):
            price_cards += 1
            if price_cards >= 3:
                return True
    return False


_DIGITS_PATTERN = re.compile(r"^\s*[\d,\.]+[+%]?\s*$")


def _looks_like_stats(element: Tag) -> bool:
    """Detect a stats / counter section.

    Matches when 3+ direct child blocks each contain a short text node that
    is mostly digits (e.g. ``1,200+``, ``99%``, ``50``). These are the big
    numbers in a typical stats section, paired with descriptive labels.
    """
    child_blocks = _direct_child_blocks(element)
    stat_count = 0
    for child in child_blocks:
        for tag in child.find_all(["h1", "h2", "h3", "h4", "span", "strong", "b"]):
            text = tag.get_text(strip=True)
            if text and _DIGITS_PATTERN.match(text):
                stat_count += 1
                break
    return stat_count >= 3


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
    """Collect unique image URLs referenced across a page's sections.

    Includes main ``src`` values, all ``srcset_urls`` from responsive images,
    and ``background`` role images from CSS inline styles.
    """
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)

    for section in page_sections:
        for image in section.get("content", {}).get("images", []):
            _add(image.get("src", ""))
            for srcset_url in image.get("srcset_urls", []):
                _add(srcset_url)
    return ordered
