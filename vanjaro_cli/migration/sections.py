"""Section detection, classification, and content extraction."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from vanjaro_cli.migration.crawler import IGNORED_LINK_SCHEMES

__all__ = [
    "extract_sections",
    "extract_page_title",
    "extract_global_element",
    "collect_image_urls",
    "TEMPLATE_MAP",
]

TEMPLATE_MAP: dict[str, str] = {
    "hero": "Centered Hero",
    "cards": "Feature Cards (3-up)",
    "testimonial": "Testimonial Cards (3-up)",
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
        text = soup.title.get_text(separator=" ", strip=True)
        if text:
            return text
    first_h1 = soup.find("h1")
    if first_h1:
        return first_h1.get_text(separator=" ", strip=True)
    return ""


BACKGROUND_ATTR = "data-migrate-bg"
TEXT_COLOR_ATTR = "data-migrate-color"
BACKGROUND_IMAGE_ATTR = "data-migrate-bg-image"
HIDDEN_ATTR = "data-migrate-hidden"


def _strip_hidden_elements(soup: BeautifulSoup) -> None:
    """Drop subtrees the browser never painted.

    The rendered crawl stamps ``data-migrate-hidden`` on display:none /
    visibility:hidden elements (inactive tab panes, hidden slides, offcanvas
    menus); ``aria-hidden="true"`` catches carousel clone items in static
    fetches too. Without this, serialized DOMs dump entire hidden datasets
    (e.g. every testimonial tab) into extracted sections.
    """
    for element in soup.find_all(attrs={HIDDEN_ATTR: True}):
        element.decompose()
    for element in soup.find_all(attrs={"aria-hidden": "true"}):
        element.decompose()

_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CSS_BG_DECL = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;}]+)", re.IGNORECASE)
_CSS_COLOR_DECL = re.compile(r"(?:^|;)\s*color\s*:\s*([^;}]+)", re.IGNORECASE)
_CSS_COLOR_VALUE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")


def _color_from_declaration(declaration: str) -> str | None:
    match = _CSS_COLOR_VALUE.search(declaration)
    return match.group(0) if match else None


def annotate_section_styles(soup: BeautifulSoup, css_text: str) -> None:
    """Stamp elements matched by CSS background rules with their colors.

    Section-level backgrounds almost always come from stylesheet classes, not
    inline styles, so the extractor can't see them in the HTML alone. This
    pass resolves background-color rules (and the text color set in the same
    rule) onto the matched elements as ``data-migrate-*`` attributes for
    :func:`extract_sections` to pick up. Later rules win, approximating the
    cascade without computing specificity.
    """
    for selector_group, body in _CSS_RULE.findall(css_text):
        bg_match = _CSS_BG_DECL.search(body)
        if not bg_match:
            continue
        background = _color_from_declaration(bg_match.group(1))
        if not background:
            continue
        fg_match = _CSS_COLOR_DECL.search(body)
        text_color = _color_from_declaration(fg_match.group(1)) if fg_match else None
        for selector in selector_group.split(","):
            selector = selector.strip()
            if not selector or selector.startswith("@") or ":" in selector:
                continue
            try:
                matches = soup.select(selector)
            except Exception:  # noqa: BLE001 — soupsieve raises several types on unsupported selectors
                continue
            for element in matches:
                element[BACKGROUND_ATTR] = background
                if text_color:
                    element[TEXT_COLOR_ATTR] = text_color


_DEFAULT_BACKGROUNDS = frozenset({
    "#fff",
    "#ffffff",
    "white",
    "transparent",
    "none",
    # Computed-style forms from rendered crawls
    "rgb(255,255,255)",
    "rgba(255,255,255,1)",
    "rgba(0,0,0,0)",
})


def _is_default_background(value: str) -> bool:
    """White/transparent is the page default — carrying it adds style noise."""
    return value.strip().lower().replace(" ", "") in _DEFAULT_BACKGROUNDS


def _section_background(element: Tag) -> tuple[str | None, str | None]:
    """Return (background_color, text_color) for a section element.

    Checks the element's inline style, its annotation, then large child
    wrappers (carrying most of the section's text) — backgrounds often sit on
    an inner band div rather than the layout pane itself. Small annotated
    descendants like buttons are ignored.
    """
    inline = element.get("style", "")
    bg_match = _CSS_BG_DECL.search(inline)
    if bg_match:
        background = _color_from_declaration(bg_match.group(1))
        if background:
            fg_match = _CSS_COLOR_DECL.search(inline)
            return background, _color_from_declaration(fg_match.group(1)) if fg_match else None

    candidates = [element]
    section_text = len(element.get_text(separator=" ", strip=True)) or 1
    for descendant in element.find_all(
        ("div", "section", "article"), attrs={BACKGROUND_ATTR: True}, limit=8
    ):
        if len(descendant.get_text(separator=" ", strip=True)) / section_text >= 0.5:
            candidates.append(descendant)
    for candidate in candidates:
        background = candidate.get(BACKGROUND_ATTR)
        if background:
            return background, candidate.get(TEXT_COLOR_ATTR)
    return None, None


def _section_background_image(element: Tag, base_url: str) -> str | None:
    """Return the section's background image URL, if one was annotated."""
    candidates = [element]
    section_text = len(element.get_text(separator=" ", strip=True)) or 1
    for descendant in element.find_all(
        ("div", "section", "article"), attrs={BACKGROUND_IMAGE_ATTR: True}, limit=8
    ):
        if len(descendant.get_text(separator=" ", strip=True)) / section_text >= 0.5:
            candidates.append(descendant)
    for candidate in candidates:
        image_url = candidate.get(BACKGROUND_IMAGE_ATTR)
        if image_url and not image_url.startswith("data:"):
            return urljoin(base_url, image_url)
    return None


def _chrome_background(element: Tag) -> tuple[str | None, str | None]:
    """Resolve the band color for a header/footer element.

    Chrome carries almost no text, so the text-share gate in
    :func:`_section_background` never matches its stamped descendants —
    header/footer bands typically live on zero-text overlay divs
    (``div.shade``, ``footer_bottom_bg``). Take the element's own stamp,
    else the first stamped descendant whose color isn't the default white.
    """
    own = element.get(BACKGROUND_ATTR)
    if own and not _is_default_background(own):
        return own, element.get(TEXT_COLOR_ATTR)
    for descendant in element.find_all(attrs={BACKGROUND_ATTR: True}, limit=12):
        background = descendant.get(BACKGROUND_ATTR)
        if background and not _is_default_background(background):
            # A zero-text overlay's computed color is meaningless — leave
            # text color unset so dark bands get the auto-white fallback.
            has_text = bool(descendant.get_text(separator=" ", strip=True))
            return background, descendant.get(TEXT_COLOR_ATTR) if has_text else None
    return None, None


_NON_STRUCTURAL_TAGS = ("script", "style", "noscript", "input", "link", "meta", "template")

# Tags that commonly wrap an entire page body without contributing structure.
# ``form`` matters for ASP.NET WebForms/DNN sites, where <body> holds a single
# page-wide <form> and every real section lives inside it.
_WRAPPER_TAGS = ("div", "article", "form", "main")

_MAX_WRAPPER_DESCENT = 6


def _structural_children(element: Tag) -> list[Tag]:
    return [
        child
        for child in element.find_all(recursive=False)
        if isinstance(child, Tag) and child.name not in _NON_STRUCTURAL_TAGS
    ]


def _has_visible_content(element: Tag) -> bool:
    return bool(element.get_text(separator=" ", strip=True)) or element.find("img") is not None


def _visible_children(element: Tag) -> list[Tag]:
    """Structural children that render something (skips hidden-input wrappers
    like ASP.NET's ``div.aspNetHidden`` and empty layout panes)."""
    return [c for c in _structural_children(element) if _has_visible_content(c)]


def _section_like_child_count(element: Tag) -> int:
    """Count children that look like sections of their own (carry a heading
    somewhere inside, or are sectioning tags). A leaf section whose direct
    children are a bare heading plus content scores 0 here, which protects
    it from being split apart."""
    count = 0
    for child in _visible_children(element):
        if child.name in ("section", "article") or child.find(
            ("h1", "h2", "h3", "h4", "h5", "h6")
        ):
            count += 1
    return count


_DOMINANT_TEXT_SHARE = 0.6


def _is_banner_image_section(content: dict) -> bool:
    """A leading section that is just imagery — no headings, no real text."""
    images = content.get("images") or []
    if not images or not images[0].get("src"):
        return False
    if content.get("headings") or content.get("buttons"):
        return False
    text_length = sum(len(p) for p in content.get("paragraphs") or [])
    return text_length < 40


def _is_chrome_like(element: Tag) -> bool:
    """Cheap pre-classification of header/footer/nav elements.

    Used to keep chrome text out of the dominance denominator — rendered
    DOMs carry full nav text in mobile menus, which otherwise dilutes the
    content pane's share below the expansion threshold.
    """
    if element.name in ("header", "footer", "nav"):
        return True
    classes = " ".join(element.get("class", [])).lower()
    return "header" in classes or "footer" in classes or "menu" in classes


# Whole-class names that mark a child as theme/CMS layout plumbing rather
# than a content card. Repeated ``div.dnn_layout`` bands must not read as a
# "uniform card grid" — that blocks splitting a page's section bands apart.
_LAYOUT_CLASS_NAMES = frozenset({"dnn_layout", "clearfix", "container", "wrapper", "row"})


def _is_layout_classed(child: Tag) -> bool:
    for cls in child.get("class", []):
        lowered = cls.lower()
        if lowered in _LAYOUT_CLASS_NAMES:
            return True
        # DNN pane classes (BannerPane, Full_Screen_PaneE, contentpane) —
        # 'panel' is real card markup and must not match.
        if "pane" in lowered and "panel" not in lowered:
            return True
    return False


def _children_look_like_cards(element: Tag) -> bool:
    """True when a majority of visible children share one tag+class signature.

    Card grids repeat one child shape (3x ``article``, Nx ``div.col-md-4``);
    page-level layout containers (DNN panes, theme rows) mix shapes or carry
    layout class names, which never count toward uniformity. Uniform
    children mean the element is a leaf section that must not be split.
    """
    children = _visible_children(element)
    if len(children) < 2:
        return False
    signatures = [
        (child.name, tuple(sorted(child.get("class", []))))
        for child in children
        if not _is_layout_classed(child)
    ]
    if not signatures:
        return False
    most_common_count = max(signatures.count(sig) for sig in set(signatures))
    return most_common_count >= 2 and most_common_count / len(children) >= 0.5


def _is_multi_module_pane(section: Tag, inner: list[Tag]) -> bool:
    """True when a pane stacks two or more self-contained content modules.

    Each child must own a heading and carry real body content (text or
    images), and the children must not form a uniform card grid. This
    separates genuinely distinct stacked sections (a feature band above a
    portfolio grid) from a single section whose layout happens to nest a
    couple of headed sub-blocks.
    """
    if _is_chrome_like(section) or len(inner) < 2:
        return False
    if _children_look_like_cards(section):
        return False
    for child in inner:
        if child.find(_HEADING_TAGS) is None:
            return False
        if not (child.find("p") or child.find("img")):
            return False
    return True


def _top_level_sections(soup: BeautifulSoup) -> list[Tag]:
    """Return one element per visual section of the page.

    Two passes deal with wrapper-heavy markup (ASP.NET WebForms/DNN pages
    wrap everything in <form>; themes add chains of layout divs):

    1. Collapse chains of single visible wrappers (div/article/form/main).
    2. Expand a *dominant content container* in place: when one child holds
       most of the page text and contains multiple section-like children
       (e.g. DNN's content pane sitting next to header/footer chrome), its
       children replace it in document order. Chrome siblings stay put.
    """
    container = soup.find("main") or soup.body
    if not container:
        return []

    sections = _visible_children(container)
    for _ in range(_MAX_WRAPPER_DESCENT):
        if len(sections) != 1 or sections[0].name not in _WRAPPER_TAGS:
            break
        inner = _visible_children(sections[0])
        if not inner:
            break
        sections = inner

    for _ in range(_MAX_WRAPPER_DESCENT):
        if len(sections) < 2:
            # A single node is a section, not a container — expanding it would
            # shred card grids (every card carries its own heading). Dominant
            # expansion only applies when chrome siblings prove this level is
            # a page-level layout row.
            break
        total_text = sum(
            len(s.get_text(separator=" ", strip=True)) for s in sections if not _is_chrome_like(s)
        ) or 1
        expanded: list[Tag] = []
        did_expand = False
        for section in sections:
            if _is_chrome_like(section):
                expanded.append(section)
                continue
            text_share = len(section.get_text(separator=" ", strip=True)) / total_text
            inner = _visible_children(section)
            if (
                text_share > _DOMINANT_TEXT_SHARE
                and section.name in _WRAPPER_TAGS
                and len(inner) == 1
            ):
                # Dominant single-child wrapper: unwrap and keep descending.
                # JS-injected body siblings (offcanvas menus, overlays) defeat
                # the single-wrapper chain pass, so it must also happen here.
                expanded.append(inner[0])
                did_expand = True
            elif text_share > _DOMINANT_TEXT_SHARE and any(
                _is_chrome_like(child) for child in inner
            ):
                # Content sections never contain headers/footers/menus — an
                # element wrapping chrome is a page-level layout wrapper.
                expanded.extend(inner)
                did_expand = True
            elif (
                text_share > _DOMINANT_TEXT_SHARE
                and _section_like_child_count(section) >= 2
                and not _children_look_like_cards(section)
            ):
                expanded.extend(inner)
                did_expand = True
            elif _is_multi_module_pane(section, inner):
                # Two or more stacked content modules sharing one pane — each
                # carries its own heading and isn't part of a uniform card
                # grid. They're distinct sections regardless of how much of
                # the page's text this pane holds; without splitting, the
                # dominant module's card grid swallows the others at rescope
                # time (e.g. home's feature band lost behind the portfolio).
                expanded.extend(inner)
                did_expand = True
            else:
                expanded.append(section)
        sections = expanded
        if not did_expand:
            break

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


def _is_button_styled(anchor: Tag) -> bool:
    """True when the anchor's classes mark it as a button (``btn``/``button``)."""
    classes = " ".join(anchor.get("class", []))
    return "btn" in classes or "button" in classes


_PRICE_AMOUNT = re.compile(r"[\$£€]\s*[\d][\d.,]*")
_PRICE_PERIOD = re.compile(r"/\s*(month|mo|year|yr|week|wk)\b", re.IGNORECASE)


def _price_for_heading(heading: Tag) -> str:
    """Return a normalized price ('$99.95/month') scoped to a plan heading.

    Pricing tables keep the amount in a ``<span class="price">`` with the
    currency and billing period in surrounding markup — none of it visible to
    heading/paragraph extraction, so plan cards migrate priceless. Walks up to
    the card wrapper that owns this heading, and only the first heading inside
    that wrapper claims the price (so a card's sub-headings don't all repeat
    it).
    """
    walker = heading.parent
    for _ in range(5):
        if walker is None:
            break
        price_el = walker.find(class_=re.compile(r"\bprice\b", re.IGNORECASE))
        if price_el is not None:
            headings_here = walker.find_all(_HEADING_TAGS)
            if headings_here and headings_here[0] is not heading:
                return ""
            scope_text = (price_el.find_parent(class_=re.compile(r"price")) or walker).get_text(
                " ", strip=True
            )
            amount = _PRICE_AMOUNT.search(scope_text)
            if amount:
                price = amount.group(0).replace(" ", "")
                period = _PRICE_PERIOD.search(scope_text)
                return f"{price}/{period.group(1).lower()}" if period else price
            return ""
        walker = walker.parent
    return ""


def _is_bold_only_paragraph(tag: Tag) -> bool:
    """True when a <p>'s entire visible text comes from a single bold run."""
    bold = tag.find(["strong", "b"])
    if bold is None:
        return False
    bold_text = bold.get_text(separator=" ", strip=True)
    para_text = tag.get_text(separator=" ", strip=True)
    return bool(bold_text) and bold_text == para_text


def _extract_content(element: Tag, base_url: str) -> dict:
    """Pull structured content from an HTML element for migration."""
    headings: list[str] = []
    for level in ("h1", "h2", "h3", "h4"):
        for tag in element.find_all(level):
            # A heading inside a <blockquote> is the quote's own text, not a
            # section/card heading; it's captured separately in blockquotes.
            # Left in the heading list it lands in a card-title slot and
            # renders link-styled (Oasis Advisors' pull-quotes).
            if tag.find_parent("blockquote") is not None:
                continue
            text = tag.get_text(separator=" ", strip=True)
            if text:
                price = _price_for_heading(tag)
                headings.append(f"{text} — {price}" if price else text)

    paragraphs = []
    for tag in element.find_all("p"):
        text = tag.get_text(separator=" ", strip=True)
        if not text:
            continue
        # A paragraph that is wholly one bold run is a pseudo-subheading (the
        # CMW post bodies use <p><strong>...</strong></p> for section breaks);
        # keep the emphasis so the hierarchy survives. Text components emit
        # their content as raw HTML, so the wrapper renders.
        if _is_bold_only_paragraph(tag):
            paragraphs.append(f"<strong>{text}</strong>")
        else:
            paragraphs.append(text)

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
        text = btn.get_text(separator=" ", strip=True)
        if text:
            buttons.append({"text": text, "href": ""})
    for anchor in element.find_all("a"):
        if not _is_button_styled(anchor):
            continue
        text = anchor.get_text(separator=" ", strip=True)
        raw_href = (anchor.get("href") or "").strip()
        if not text or not raw_href:
            continue
        buttons.append({"text": text, "href": urljoin(base_url, raw_href)})

    links: list[dict] = []
    for anchor in element.find_all("a", href=True):
        if _is_button_styled(anchor):
            continue
        text = anchor.get_text(separator=" ", strip=True)
        if text:
            links.append({"text": text, "href": urljoin(base_url, anchor["href"])})

    list_items: list[str] = []
    for list_tag in element.find_all(["ul", "ol"]):
        for li in list_tag.find_all("li", recursive=False):
            text = li.get_text(separator=" ", strip=True)
            if text:
                list_items.append(text)

    blockquotes: list[dict] = []
    for bq in element.find_all("blockquote"):
        text = bq.get_text(separator=" ", strip=True)
        if not text:
            continue
        citation_tag = bq.find(["cite", "footer"])
        citation = citation_tag.get_text(separator=" ", strip=True) if citation_tag else ""
        quote_text = text
        if citation and quote_text.endswith(citation):
            quote_text = quote_text[: -len(citation)].strip(" \u2014\u2013-")
        blockquotes.append({"text": quote_text, "citation": citation})

    tables: list[list[list[str]]] = []
    for table in element.find_all("table"):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                cell.get_text(separator=" ", strip=True)
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
        caption = figcaption.get_text(separator=" ", strip=True) if figcaption else ""
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

    if "testimonial" in classes or "quote" in classes:
        return "testimonial"
    # A blockquote only signals a testimonial section when quotes are the
    # point: several of them, or a lone quote with no competing gallery/cards.
    # One decorative pull-quote inside a service page (description + image
    # gallery) must not hijack the whole section's classification.
    blockquotes = element.find_all("blockquote")
    if len(blockquotes) >= 2 or (blockquotes and element.find("img") is None):
        return "testimonial"

    if _looks_like_contact_form(element, classes):
        return "contact"

    # Blog post grids are checked before galleries: their thumbnails are
    # anchor-wrapped (so the gallery detector would claim them) but they also
    # carry per-post excerpts the gallery template would drop.
    if _looks_like_blog_cards(element):
        return "blog_cards"

    if _looks_like_gallery(element):
        return "gallery"

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

    # Card grids buried under wrapper markup (CMS module chrome): a group of
    # same-class sibling blocks each carrying its own heading is a card row
    # no matter how deep it nests. Image-rich, text-poor groups are galleries
    # (portfolio thumbnail grids); the rest are feature cards.
    group = _find_sibling_card_group(element)
    if group:
        with_image = sum(1 for member in group if member.find("img"))
        with_text = sum(1 for member in group if member.find("p"))
        if with_image >= len(group) // 2 and with_image > with_text:
            return "gallery"
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


_BLOG_POST_CLASS = re.compile(r"\b(?:list-post|blog-post|post-item|article)\b", re.IGNORECASE)


def _looks_like_blog_cards(element: Tag) -> bool:
    """Detect a blog post grid: ≥3 post cards with image + heading + excerpt.

    A post card is an ``<article>``, a ``post``-classed block, or any card
    carrying a "Read More"/"Continue reading" link — each with an image, a
    heading, and an excerpt paragraph. Catching these before galleries (whose
    anchor-wrapped thumbnails would otherwise claim them) and feature cards
    routes them to the Blog Post Cards template, which keeps the excerpt the
    gallery template drops. Cards nest under module wrappers, so the search
    walks any depth.
    """
    cards = _find_cards_by_heading(element)
    if len(cards) < 3:
        cards = _find_sibling_card_group(element)
    if len(cards) < 3:
        return False

    blog_like = 0
    for card in cards:
        if card.find("img") is None or card.find(_HEADING_TAGS) is None:
            continue
        has_excerpt = any(
            len(p.get_text(" ", strip=True)) >= 40 for p in card.find_all("p")
        )
        link_texts = " ".join(
            (a.get_text(" ", strip=True) or "").lower() for a in card.find_all("a")
        )
        has_read_more = "read more" in link_texts or "continue reading" in link_texts
        is_post = card.name == "article" or _BLOG_POST_CLASS.search(" ".join(card.get("class", [])))
        if has_read_more or (has_excerpt and is_post):
            blog_like += 1
    return blog_like >= 3


def _looks_like_bio(element: Tag, content: dict) -> bool:
    """Detect a bio / about-me split layout: one notable image + paragraph text.

    The Bio / About template is a two-column image-on-one-side, text-on-the-
    other-side layout. Heuristic: the section contains exactly one or two
    images, at least one heading, and at least two paragraphs of SHORT text.
    The length cap keeps full article bodies (blog posts routinely carry one
    featured image + many paragraphs) out of the Bio template, whose image
    column floats and circle-crops the image.
    """
    image_count = len(content.get("images", []))
    heading_count = len(content.get("headings", []))
    paragraphs = content.get("paragraphs", [])

    if image_count not in (1, 2):
        return False
    if heading_count < 1:
        return False
    if len(paragraphs) < 2:
        return False
    return sum(len(p) for p in paragraphs) <= 800


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
            text = tag.get_text(separator=" ", strip=True)
            if text and _DIGITS_PATTERN.match(text):
                stat_count += 1
                break
    return stat_count >= 3


_CARD_LIKE_TYPES = frozenset({"gallery", "blog_cards", "cards"})
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _find_cards_by_heading(element: Tag) -> list[Tag]:
    """Find per-card wrappers by walking up from each heading to its nearest scope.

    A card is the closest ancestor of a heading that is a ``div``/``article``/``li``
    containing exactly one heading and at least one ``<img>`` tag. This isolates
    card boundaries inside sections that the flat ``_extract_content`` pass can't
    distinguish (e.g. a page-wide ``<form>`` wrapper that also contains header
    logos and chamber-of-commerce images).
    """
    cards: list[Tag] = []
    seen_ids: set[int] = set()
    for heading in element.find_all(_HEADING_TAGS):
        walker = heading.parent
        while walker is not None and walker is not element:
            if walker.name in ("div", "article", "li"):
                nested_headings = walker.find_all(_HEADING_TAGS)
                if len(nested_headings) == 1 and walker.find("img") is not None:
                    walker_id = id(walker)
                    if walker_id not in seen_ids:
                        seen_ids.add(walker_id)
                        cards.append(walker)
                    break
            walker = walker.parent
    return cards


def _find_gallery_anchors(element: Tag) -> list[Tag]:
    """Return every ``<a>`` element in ``element`` that directly wraps an ``<img>``."""
    return [anchor for anchor in element.find_all("a") if anchor.find("img")]


# Animation / scroll-reveal / state tokens that vary per card (so the same
# card grid carries different class strings: infobox01+fadeInLeft+delay1 vs
# infobox02+fadeInRight+delay2). Stripped before grouping siblings.
_DECORATIVE_CLASS_TOKENS = frozenset({
    "animation", "animation_item", "animated", "wow", "aos",
    "fadein", "fadeinleft", "fadeinright", "fadeinup", "fadeindown",
    "slideup", "slidedown", "slideinleft", "slideinright",
    "scaleup", "zoomin", "bounce", "active",
})
_TRAILING_DIGITS = re.compile(r"\d+$")


def _normalized_class_signature(child: Tag) -> str:
    """A class signature that ignores per-card animation and index variation.

    Drops scroll-reveal/state tokens and the trailing digits CMS themes append
    to enumerate cards (``infobox01`` -> ``infobox``, ``delay2`` -> ``delay``),
    so a uniform card grid groups even when each card's class string differs.
    """
    tokens = set()
    for raw in child.get("class", []):
        token = _TRAILING_DIGITS.sub("", raw.lower())
        if token and token not in _DECORATIVE_CLASS_TOKENS:
            tokens.add(token)
    return " ".join(sorted(tokens))


def _find_sibling_card_group(element: Tag) -> list[Tag]:
    """Find the largest group of same-class sibling blocks that each own a heading.

    Card grids on CMS-built sites nest the repeating unit several wrapper
    levels below the section element (module chrome, content panes), so
    direct-children checks miss them. Walks every container in the subtree
    and groups its direct ``div``/``article``/``li`` children by tag + a
    normalized class signature (animation/index tokens stripped); a group of
    3+ members where every member carries a heading is a card row. Requiring
    headings keeps image-only strips (badge rows, testimonial avatars) and
    free-flowing article bodies out.
    """
    best: list[Tag] = []
    for container in element.find_all(["div", "section", "ul", "ol"]):
        groups: dict[tuple[str, str], list[Tag]] = {}
        for child in container.find_all(recursive=False):
            if not isinstance(child, Tag) or child.name not in ("div", "article", "li"):
                continue
            signature = (child.name, _normalized_class_signature(child))
            if not signature[1]:
                continue
            groups.setdefault(signature, []).append(child)
        for members in groups.values():
            if len(members) < 3 or len(members) <= len(best):
                continue
            if all(member.find(_HEADING_TAGS) for member in members):
                best = members
    return best


def _first_image_entry(card: Tag, base_url: str) -> dict:
    """Extract a single ``{src, alt}`` entry from the first ``<img>`` inside ``card``.

    Returns an empty-string placeholder when no image is found so positional
    alignment with sibling ``headings`` / ``paragraphs`` arrays is preserved.
    """
    img = card.find("img")
    if img is None or not img.get("src"):
        return {"src": "", "alt": ""}
    return {
        "src": urljoin(base_url, img["src"]),
        "alt": img.get("alt", ""),
    }


def _first_card_button(card: Tag, base_url: str) -> dict | None:
    """Return the first ``btn``/``button``-classed anchor inside ``card`` as a dict."""
    for anchor in card.find_all("a"):
        if not _is_button_styled(anchor):
            continue
        text = anchor.get_text(separator=" ", strip=True)
        href = (anchor.get("href") or "").strip()
        if text and href:
            return {"text": text, "href": urljoin(base_url, href)}
    return None


def _first_card_link(card: Tag, base_url: str) -> dict | None:
    """Return the first non-button anchor with real text and href inside ``card``."""
    for anchor in card.find_all("a", href=True):
        if _is_button_styled(anchor):
            continue
        text = anchor.get_text(separator=" ", strip=True)
        href = anchor.get("href", "").strip()
        if text and href:
            return {"text": text, "href": urljoin(base_url, href)}
    return None


def _excerpt(text: str, limit: int = 200) -> str:
    """Truncate ``text`` to an excerpt at a word boundary near ``limit``.

    Adds an ellipsis only when something was cut. Used for post-grid cards
    whose rendered DOM carries the full article body where a card should show
    a teaser.
    """
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.—- ")
    return f"{clipped}…"


def _rescope_content_to_cards(
    element: Tag,
    section_type: str,
    base_url: str,
    content: dict,
) -> dict:
    """Realign ``content`` so ``heading_N`` / ``image_N`` / ``text_N`` refer to the Nth card.

    Called after the classifier labels a section as a card-like type. The flat
    extraction in ``_extract_content`` walks ``<img>`` tags in document order,
    which pulls in header logos and chrome imagery before the actual card
    contents. That causes templates like ``Gallery (3-up)`` to pair post titles
    with the site logo instead of the per-post featured image.

    Returns ``content`` unchanged when we can't identify ≥3 cards — the flat
    extraction is better than an empty realigned result.
    """
    cards = _find_cards_by_heading(element)
    if len(cards) < 3:
        # Cards without images (icon-font feature rows) never match the
        # heading-walker, but the sibling-group detector that classified the
        # section can still hand us the per-card wrappers.
        cards = _find_sibling_card_group(element)
    if len(cards) < 3 and section_type == "gallery":
        # Pure anchor-wrapped image grids (e.g. portfolio thumbnail lightboxes)
        # have no per-card headings, so fall back to ``<a>`` elements as cards.
        cards = _find_gallery_anchors(element)
    if len(cards) < 3:
        return content

    # A pure image gallery (no card carries a heading) has no per-card text —
    # its only real content is the section's own heading + intro paragraph,
    # which the flat extraction already captured. Keep that and just clean up
    # the image list (dropping chrome logos), so a service page's description
    # survives and image alt-text doesn't masquerade as card titles.
    if all(card.find(_HEADING_TAGS) is None for card in cards):
        return {**content, "images": [_first_image_entry(card, base_url) for card in cards]}

    headings: list[str] = []
    paragraphs: list[str] = []
    images: list[dict] = []
    buttons: list[dict | None] = []
    links: list[dict | None] = []

    for card in cards:
        heading_tag = card.find(_HEADING_TAGS)
        image_entry = _first_image_entry(card, base_url)
        heading_text = heading_tag.get_text(separator=" ", strip=True) if heading_tag else ""
        if not heading_text and image_entry["alt"]:
            heading_text = image_entry["alt"]
        headings.append(heading_text)
        images.append(image_entry)

        paragraph_tag = card.find("p")
        paragraph_text = paragraph_tag.get_text(separator=" ", strip=True) if paragraph_tag else ""
        # A card whose paragraph is far longer than any teaser is a post grid
        # carrying the full article body in the rendered DOM; trim it to an
        # excerpt. The generous gate leaves normal feature-card copy intact.
        paragraphs.append(_excerpt(paragraph_text, limit=240))

        buttons.append(_first_card_button(card, base_url))
        links.append(_first_card_link(card, base_url))

    return {
        **content,
        "headings": headings,
        "paragraphs": paragraphs,
        "images": images,
        "buttons": buttons,
        "links": links,
    }


def _rescope_testimonial(content: dict) -> dict:
    """Align a testimonial section's content with quote+name card slots.

    Testimonial quotes live in ``<blockquote>`` elements and the speaker's
    name is usually the avatar image's alt text (citations are often empty),
    so the flat extraction leaves the Testimonial Cards template's quote/name
    slots blank and dumps the raw avatars instead. Maps each quote to a text
    slot and its name to a heading slot (citation first, else the matching
    image alt), and drops the inline avatars the template has no slot for.
    """
    blockquotes = content.get("blockquotes") or []
    quotes = [bq.get("text", "") for bq in blockquotes if isinstance(bq, dict) and bq.get("text")]
    if len(quotes) < 1:
        return content

    images = content.get("images") or []
    names: list[str] = []
    for index, blockquote in enumerate(bq for bq in blockquotes if isinstance(bq, dict) and bq.get("text")):
        name = blockquote.get("citation") or ""
        if not name and index < len(images) and isinstance(images[index], dict):
            name = images[index].get("alt", "")
        names.append(name)

    return {**content, "paragraphs": quotes, "headings": names, "images": []}


SPLIT_MEDIA_TEMPLATE = "Split Media"
SPLIT_MEDIA_REVERSE_TEMPLATE = "Split Media Reverse"


def _is_grid_column(tag: Tag) -> bool:
    """Return True for a Bootstrap-style column div (``col`` / ``col-md-6`` / ...)."""
    return tag.name == "div" and any(
        token == "col" or token.startswith("col-") for token in tag.get("class", [])
    )


def _has_push_pull(column: Tag) -> bool:
    """Return True when a column carries a Bootstrap push/pull order-swap class."""
    return any("push" in token or "pull" in token for token in column.get("class", []))


def _classify_split_columns(columns: list[Tag]) -> tuple[Tag, Tag] | None:
    """Split a two-column row into (image_column, text_column).

    A media column holds an image and almost no text; a text column holds a
    heading or paragraph and no image. Returns ``None`` when the pair isn't a
    clean image-beside-text split (so ordinary multi-column rows are ignored).
    """
    media: Tag | None = None
    text: Tag | None = None
    for column in columns:
        has_image = column.find("img") is not None
        has_heading = column.find(_HEADING_TAGS) is not None
        has_paragraph = any(p.get_text(strip=True) for p in column.find_all("p"))
        own_text_length = len(column.get_text(" ", strip=True))
        if has_image and not has_heading and own_text_length < 40:
            media = column
        elif (has_heading or has_paragraph) and not has_image:
            text = column
    if media is not None and text is not None:
        return media, text
    return None


def _visual_image_on_left(row: Tag, media: Tag, text: Tag) -> bool:
    """Decide whether the image renders left of the text after push/pull swaps.

    Bootstrap's ``col-*-push-N`` / ``col-*-pull-N`` reverse a column pair's
    visual order without changing DOM order, so the source markup encodes an
    alternating layout the document order alone would miss.
    """
    children = [child for child in row.find_all(recursive=False) if isinstance(child, Tag)]
    try:
        media_first = children.index(media) < children.index(text)
    except ValueError:
        media_first = True
    swapped = _has_push_pull(media) or _has_push_pull(text)
    return media_first != swapped


def _find_split_media_rows(element: Tag) -> list[tuple[Tag, Tag, bool]]:
    """Find image-beside-text rows inside a section.

    Each result is ``(media_column, text_column, image_on_left)`` for a
    ``div.row`` that holds exactly two columns — one image, one text.
    """
    rows: list[tuple[Tag, Tag, bool]] = []
    for row in element.find_all("div"):
        if "row" not in row.get("class", []):
            continue
        columns = [
            child for child in row.find_all(recursive=False)
            if isinstance(child, Tag) and _is_grid_column(child)
        ]
        if len(columns) != 2:
            continue
        pair = _classify_split_columns(columns)
        if pair is None:
            continue
        media, text = pair
        rows.append((media, text, _visual_image_on_left(row, media, text)))
    return rows


def _split_media_sections(element: Tag, content: dict, base_url: str) -> list[dict] | None:
    """Split alternating image-beside-text rows into one section each.

    edca-style "how we work" pages stack several two-column rows (image left /
    text right, then text left / image right) inside one section; the flat
    extraction collapses them into a single Rich Text Block with every image
    dropped to a background. Each row instead becomes its own Split Media
    section, alternating the template so the image side matches the source.
    Returns ``None`` when the section has fewer than two such rows (a lone
    split row is already handled by the Bio template).
    """
    rows = _find_split_media_rows(element)
    if len(rows) < 2:
        return None

    inherited = {
        key: content[key]
        for key in ("background_color", "text_color")
        if key in content
    }

    sections: list[dict] = []
    for media, text, image_on_left in rows:
        row_content = _extract_content(text, base_url)
        row_content["images"] = [_first_image_entry(media, base_url)]
        row_content.update(inherited)
        template = SPLIT_MEDIA_TEMPLATE if image_on_left else SPLIT_MEDIA_REVERSE_TEMPLATE
        sections.append({"type": "split", "template": template, "content": row_content})
    return sections


def extract_sections(html: str, base_url: str, css_text: str | None = None) -> list[dict]:
    """
    Extract sections from a page's HTML.

    Each result dict has `type`, `template`, and `content` keys. When
    ``css_text`` is provided, section background/text colors are resolved
    from the stylesheet and included in content.
    """
    soup = BeautifulSoup(html, "html.parser")
    _strip_hidden_elements(soup)
    if css_text:
        annotate_section_styles(soup, css_text)
    top_level = _top_level_sections(soup)

    sections: list[dict] = []
    for element in top_level:
        content = _extract_content(element, base_url)
        # Skip empty wrappers
        if not any(content.values()):
            continue
        background, text_color = _section_background(element)
        if background and not _is_default_background(background):
            content["background_color"] = background
            if text_color:
                content["text_color"] = text_color
        background_image = _section_background_image(element, base_url)
        if background_image:
            content["background_image"] = background_image
        # First *kept* section is hero-eligible — skipped chrome (headers)
        # and empty wrappers shouldn't cost the real first section its slot.
        # Page chrome is supplied by global header/footer block wrapping at
        # assemble time; keeping these sections would double-render it. The
        # tag/class check also drops offcanvas menus the classifier misses.
        if _is_chrome_like(element):
            continue
        if not sections and _is_banner_image_section(content):
            # A leading image-only pane is the page's hero banner; promote the
            # image to a section background so hero templates can render it
            # full-width instead of dropping it into a text template. Remove
            # it from the inline image list — it must not render twice.
            content["background_image"] = content["images"][0]["src"]
            content["images"] = content["images"][1:]
            section_type = "hero"
        else:
            # Alternating image-beside-text rows split into one Split Media
            # section each. Checked before classification: the separate
            # image-only/text-only columns are structurally distinct from a
            # feature-card grid (where each card holds its own image + text),
            # so a real card grid never yields two such rows.
            split_sections = _split_media_sections(element, content, base_url)
            if split_sections:
                sections.extend(split_sections)
                continue
            section_type = _classify_section(element, content, is_first=not sections)
        if section_type in ("header", "footer"):
            continue
        if section_type in _CARD_LIKE_TYPES:
            content = _rescope_content_to_cards(element, section_type, base_url, content)
        elif section_type == "testimonial":
            content = _rescope_testimonial(content)
        if section_type == "content":
            plan_sections = _split_pricing_plans(element, content, base_url)
            if plan_sections:
                sections.extend(plan_sections)
                continue
            # Blog post bodies carry their byline in date/label elements that
            # paragraph extraction misses; surface it as the leading line.
            meta_line = _extract_post_meta(element)
            if meta_line:
                content["paragraphs"] = [meta_line] + (content.get("paragraphs") or [])
        sections.append({
            "type": section_type,
            "template": TEMPLATE_MAP.get(section_type, TEMPLATE_MAP["content"]),
            "content": content,
        })
    return sections


def _find_pricing_plan_cards(element: Tag) -> list[Tag]:
    """Find the largest group of sibling blocks that each price a plan.

    A plan card carries a heading, a feature list, and a currency amount.
    The cards nest several wrappers below the section (CMS columns), so this
    groups same-tag siblings at any depth and returns the largest qualifying
    group — without requiring the matching class signatures a uniform card
    grid would (pricing columns often differ: a red plan vs a dark plan).
    """
    best: list[Tag] = []
    for container in element.find_all(["div", "section", "ul", "ol"]):
        members = [
            child for child in container.find_all(recursive=False)
            if isinstance(child, Tag)
            and child.name in ("div", "article", "li")
            and child.find(_HEADING_TAGS) is not None
            and child.find("li") is not None
            and _PRICE_AMOUNT.search(child.get_text(" ", strip=True))
        ]
        if len(members) >= 2 and len(members) > len(best):
            best = members
    return best


def _split_pricing_plans(element: Tag, content: dict, base_url: str) -> list[dict] | None:
    """Split a multi-plan pricing section into one content section per plan.

    Two or three plan cards (each a heading + a price + its own feature list)
    share one section, so the single-heading Rich Text Block shows only the
    first plan. The flat-positional override system can't partition the
    combined feature list per card, so each plan instead becomes its own
    content section: name+price heading and that plan's features. Returns
    ``None`` when the section isn't a multi-plan pricing block.
    """
    plan_cards = _find_pricing_plan_cards(element)
    if len(plan_cards) < 2:
        return None

    plans: list[dict] = []
    for card in plan_cards:
        heading_tag = card.find(_HEADING_TAGS)
        name = heading_tag.get_text(" ", strip=True) if heading_tag else ""
        price = _price_for_heading(heading_tag) if heading_tag else ""
        list_items = [
            li.get_text(" ", strip=True)
            for li in card.find_all("li")
            if li.get_text(" ", strip=True)
        ]
        plan_content = {
            **{k: [] for k in content},
            "headings": [f"{name} — {price}" if price else name],
            "list_items": list_items,
        }
        plans.append({
            "type": "content",
            "template": TEMPLATE_MAP["content"],
            "content": plan_content,
        })
    return plans


def _is_real_page_href(href: str) -> bool:
    """Return True if ``href`` points at a real navigable page.

    Hash-only anchors, protocol links (``mailto:``, ``tel:``, ``javascript:``,
    ...), and empty strings are all skipped — none of them represent a page
    whose parent-child relationship can be preserved in DNN's menu. The
    ignored-scheme set is shared with the crawler so both paths drop the
    same kinds of links.
    """
    if not href:
        return False
    stripped = href.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if ":" in stripped:
        scheme = stripped.split(":", 1)[0].lower()
        if scheme in IGNORED_LINK_SCHEMES:
            return False
    return True


def _walk_nav_items(list_element: Tag, base_url: str) -> list[dict]:
    """Recursively walk a ``<ul>`` / ``<ol>`` into a nested nav-items tree.

    Each entry is ``{"label", "href", "children"}`` where ``children`` is
    another list of the same shape. Non-page links (hash anchors, mailto,
    etc.) are dropped so the tree only contains hrefs that can map to real
    DNN pages.
    """
    items: list[dict] = []
    for li in list_element.find_all("li", recursive=False):
        anchor = li.find("a", recursive=False) or li.find("a")
        if anchor is None:
            continue
        href = anchor.get("href", "").strip()
        if not _is_real_page_href(href):
            continue
        label = anchor.get_text(separator=" ", strip=True)
        if not label:
            continue

        children: list[dict] = []
        nested_list = li.find(["ul", "ol"], recursive=False)
        if nested_list is not None:
            children = _walk_nav_items(nested_list, base_url)

        items.append({
            "label": label,
            "href": urljoin(base_url, href),
            "children": children,
        })
    return items


def _extract_nav_structure(element: Tag, base_url: str) -> list[dict]:
    """Extract a nested nav-items tree from the first ``<nav>`` inside ``element``.

    Returns an empty list when the element has no nav, or when the nav has
    no top-level ``<ul>`` / ``<ol>``. Used by :func:`extract_global_element`
    to annotate ``<header>`` sections so downstream tooling (page-creation
    orchestration) can match nav labels to real pages and mark them for
    inclusion in the menu.
    """
    nav = element.find("nav")
    if nav is None:
        return []
    top_list = nav.find(["ul", "ol"])
    if top_list is None:
        return []
    return _walk_nav_items(top_list, base_url)


def extract_global_element(html: str, base_url: str, element_name: str) -> dict | None:
    """Extract the first <header> or <footer> from HTML as a section dict."""
    soup = BeautifulSoup(html, "html.parser")
    _strip_hidden_elements(soup)
    element = soup.find(element_name)
    if not element:
        return None
    content = _extract_content(element, base_url)
    if element_name == "header":
        content["nav_items"] = _extract_nav_structure(element, base_url)
    background, text_color = _chrome_background(element)
    if background:
        content["background_color"] = background
        if text_color:
            content["text_color"] = text_color
    background_image = _section_background_image(element, base_url)
    if background_image:
        content["background_image"] = background_image
    if element_name == "footer":
        social_links = _extract_social_links(element)
        if social_links:
            content["social_links"] = social_links
        copyright_text = _extract_copyright_text(element)
        if copyright_text:
            content["copyright_text"] = copyright_text
    return {
        "type": element_name,
        "template": TEMPLATE_MAP.get(element_name, TEMPLATE_MAP["content"]),
        "content": content,
    }


_DATE_CLASS = re.compile(r"\bdate\b|detail-date|post-date|entry-date", re.IGNORECASE)
_TAG_CLASS = re.compile(r"^label$|\btag\b", re.IGNORECASE)


def _extract_post_meta(element: Tag) -> str:
    """Build a post meta line ('21 Sep — Website Security, Updates') if present.

    Blog modules render the date and category labels in dedicated elements
    (``div.detail-date``, ``span.label``) that paragraph extraction never
    sees, so post pages lose their byline entirely without this.
    """
    date_text = ""
    date_el = element.find(class_=_DATE_CLASS)
    if date_el is not None:
        candidate = date_el.get_text(" ", strip=True)
        if candidate and len(candidate) <= 20:
            date_text = candidate

    tags = []
    for tag_el in element.find_all("span", class_=_TAG_CLASS, limit=8):
        text = tag_el.get_text(" ", strip=True)
        if text and len(text) <= 40 and text not in tags:
            tags.append(text)

    parts = [p for p in (date_text, ", ".join(tags)) if p]
    return " — ".join(parts)


_SOCIAL_DOMAINS = {
    "facebook.com": "Facebook",
    "twitter.com": "Twitter",
    "x.com": "X",
    "instagram.com": "Instagram",
    "linkedin.com": "LinkedIn",
    "youtube.com": "YouTube",
    "plus.google.com": "Google+",
    "pinterest.com": "Pinterest",
}

_COPYRIGHT_PATTERN = re.compile(r"copyright|©", re.IGNORECASE)


def _extract_social_links(element: Tag) -> list[dict]:
    """Collect social profile links — usually icon-only anchors with no text."""
    found: list[dict] = []
    seen: set[str] = set()
    for anchor in element.find_all("a", href=True):
        href = anchor["href"].strip()
        for domain, label in _SOCIAL_DOMAINS.items():
            if domain in href and href not in seen:
                seen.add(href)
                found.append({"label": label, "href": href})
                break
    return found


def _extract_copyright_text(element: Tag) -> str:
    """Find the copyright line — often a bare <span>, invisible to <p> extraction."""
    for text_node in element.find_all(string=_COPYRIGHT_PATTERN):
        text = text_node.strip()
        if text and len(text) < 160:
            return text
    return ""


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
        content = section.get("content", {})
        for image in content.get("images", []):
            _add(image.get("src", ""))
            for srcset_url in image.get("srcset_urls", []):
                _add(srcset_url)
        _add(content.get("background_image", ""))
    return ordered
