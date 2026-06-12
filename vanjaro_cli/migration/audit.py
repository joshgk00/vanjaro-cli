"""Structural best-practice audit for migrated Vanjaro pages.

Pure functions — no I/O, no network calls. Each check receives a parsed
BeautifulSoup document and returns a finding dict with keys:

  check   — string identifier
  score   — 0-100 integer
  summary — one-line human description
  details — list of string findings (worst offenders)
"""

from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup, Tag

__all__ = [
    "SCORE_HIGH_BELOW",
    "SCORE_MEDIUM_BELOW",
    "audit_page",
    "audit_site",
    "check_composition",
    "check_global_blocks",
    "check_inline_styles",
    "check_responsive_images",
    "check_theme_classes",
]

# Audit-check score thresholds that classify a finding's severity. Defined here
# beside the checks that produce the scores so the cutoffs and the scoring stay
# in one place; gap_report.py imports these for its punch-list severity labels.
SCORE_HIGH_BELOW = 50
SCORE_MEDIUM_BELOW = 80

# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------

_VER_QUERY = re.compile(r"\?ver=[^&\s\"']+", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_ATTR_ID = re.compile(r'\bid="[^"]*"')
_ATTR_DATA_GUID = re.compile(r'\bdata-guid="[^"]*"')


def _vj_editor(soup: BeautifulSoup) -> Tag | None:
    """Return the #vjEditor element, or None if not present."""
    editor = soup.find(id="vjEditor")
    return editor if isinstance(editor, Tag) else None


class _EditorScan:
    """Everything the per-page checks need from one downward walk of #vjEditor.

    Collected in a single traversal instead of each check re-walking the
    subtree: ``elements`` carries every descendant Tag paired with whether it
    sits inside a DNN module embed (div[vjmod]/.DnnModule, which may legitimately
    inline styles and is excluded from content checks); ``images`` is the same
    for ``<img>`` tags; ``top_level_children`` and ``section_count`` describe the
    composition; ``max_depth`` is the deepest nesting under the editor.
    """

    __slots__ = (
        "elements",
        "images",
        "top_level_children",
        "section_count",
        "max_depth",
    )

    def __init__(self, editor: Tag) -> None:
        self.elements: list[tuple[Tag, bool]] = []
        self.images: list[tuple[Tag, bool]] = []
        self.section_count = 0
        self.max_depth = 0
        self.top_level_children = [c for c in editor.children if isinstance(c, Tag)]

        def walk(element: Tag, depth: int, ancestor_is_module: bool) -> None:
            if depth > self.max_depth:
                self.max_depth = depth
            for child in element.children:
                if not isinstance(child, Tag):
                    continue
                # An element is "in a module subtree" only when an ANCESTOR is a
                # module embed — a module wrapper element itself is not excluded,
                # matching the original upward-parents membership test.
                self.elements.append((child, ancestor_is_module))
                if child.name == "img":
                    self.images.append((child, ancestor_is_module))
                if child.name == "section":
                    self.section_count += 1
                classes = child.get("class") or []
                child_subtree_is_module = (
                    ancestor_is_module
                    or "DnnModule" in classes
                    or bool(child.get("vjmod"))
                )
                walk(child, depth + 1, child_subtree_is_module)

        walk(editor, 0, False)


def _normalize_markup(html: str) -> str:
    """Strip volatile attributes and whitespace for cross-page dedup comparisons."""
    normalized = _ATTR_ID.sub('', html)
    normalized = _ATTR_DATA_GUID.sub('', normalized)
    normalized = _VER_QUERY.sub('', normalized)
    normalized = _WHITESPACE.sub(' ', normalized)
    return normalized.strip()


# This live-render dedup check (normalize markup, fingerprint, count repeats)
# mirrors what vanjaro_cli/migration/dedup.py catches pre-assembly. The parallel
# is intentional: dedup.py works on crawl JSON before the page is built, this
# works on the rendered HTML afterward — different representations, so neither
# can reuse the other's fingerprint.
def _section_fingerprint(section: Tag) -> str:
    markup = _normalize_markup(str(section))
    return hashlib.md5(markup.encode()).hexdigest()  # noqa: S324 — fingerprint only, not crypto

# ---------------------------------------------------------------------------
# Check: inline-styles
# ---------------------------------------------------------------------------


def check_inline_styles(editor: Tag, scan: _EditorScan | None = None) -> dict:
    """Count style= attributes on non-module content inside #vjEditor.

    Reference sites score 0-3 per page; each attribute above zero costs 10
    points up to a floor of 0.
    """
    if scan is None:
        scan = _EditorScan(editor)
    offenders: list[str] = []
    for element, in_module in scan.elements:
        if in_module:
            continue
        if element.get("style"):
            label = element.name
            el_id = element.get("id") or element.get("class")
            if el_id:
                if isinstance(el_id, list):
                    el_id = " ".join(el_id)
                label = f"{label}#{el_id}" if element.get("id") else f"{label}.{el_id}"
            offenders.append(label)

    count = len(offenders)
    score = max(0, 100 - 10 * count)
    return {
        "check": "inline-styles",
        "score": score,
        "summary": f"{count} inline style attribute(s) found (target: 0-3)",
        "details": offenders[:20],
    }

# ---------------------------------------------------------------------------
# Check: global-blocks
# ---------------------------------------------------------------------------


def check_global_blocks(
    pages: list[tuple[str, BeautifulSoup]],
) -> dict:
    """Evaluate global-block hygiene across all audited pages.

    (a) Header + footer presence: each page should have at least one
        div[data-guid] wrapper. Bonus if the same GUID appears on every page
        (indicating a proper global block).
    (b) Duplicate-section detection: top-level sections whose normalized
        markup appears on 2+ pages without a data-guid wrapper should be
        global blocks.

    Note: Vanjaro renders global-block wrappers as ``<div data-guid="...">``
    with no ``published`` attribute in the page HTML — the attribute is only
    present in the Vanjaro editor UI. Detection relies on ``data-guid`` alone.
    """
    details: list[str] = []

    # (a) Header/footer wrappers
    guid_pages: dict[str, list[str]] = {}   # guid -> list of page URLs
    pages_missing_globals: list[str] = []

    for url, soup in pages:
        editor = _vj_editor(soup)
        if editor is None:
            pages_missing_globals.append(url)
            continue
        guids = [
            el.get("data-guid")
            for el in editor.find_all(True)
            if isinstance(el, Tag) and el.get("data-guid")
        ]
        if not guids:
            pages_missing_globals.append(url)
        for guid in guids:
            guid_pages.setdefault(guid, []).append(url)

    sitewide_guids = [g for g, urls in guid_pages.items() if len(urls) == len(pages)]
    if pages_missing_globals:
        details.append(
            f"Pages missing global-block wrappers: {', '.join(pages_missing_globals)}"
        )
    if sitewide_guids:
        details.append(
            f"Sitewide global blocks (correct): {len(sitewide_guids)} GUID(s) present on all pages"
        )

    # (b) Duplicate non-global sections
    fingerprint_pages: dict[str, list[str]] = {}  # fingerprint -> page URLs
    for url, soup in pages:
        editor = _vj_editor(soup)
        if editor is None:
            continue
        for child in editor.children:
            if not isinstance(child, Tag):
                continue
            if child.get("data-guid"):
                continue  # already a global block
            fp = _section_fingerprint(child)
            fingerprint_pages.setdefault(fp, []).append(url)

    duplicate_sections = [
        fp for fp, urls in fingerprint_pages.items()
        if len(set(urls)) >= 2
    ]
    if duplicate_sections:
        details.append(
            f"{len(duplicate_sections)} section(s) appear on 2+ pages without a global-block wrapper — "
            "consider converting to global blocks"
        )

    total_checks = len(pages) + (1 if pages else 0)
    passes = len(pages) - len(pages_missing_globals) + len(sitewide_guids)
    score = max(0, min(100, int(100 * passes / max(total_checks, 1))))
    if duplicate_sections:
        score = max(0, score - 10 * len(duplicate_sections))

    if not guid_pages:
        summary = (
            f"No global-block wrappers found on any page; "
            f"{len(duplicate_sections)} duplicate section(s) without global wrapping"
        )
    else:
        summary = (
            f"{len(sitewide_guids)} sitewide global block(s); "
            f"{len(pages_missing_globals)} page(s) missing wrappers; "
            f"{len(duplicate_sections)} duplicate section(s) without global wrapping"
        )

    return {
        "check": "global-blocks",
        "score": score,
        "summary": summary,
        "details": details,
    }

# ---------------------------------------------------------------------------
# Check: theme-classes
# ---------------------------------------------------------------------------

_HEAD_STYLE = re.compile(r"\bhead-style-\d+\b")
_PARA_STYLE = re.compile(r"\bparagraph-style-\d+\b")
_BTN_STYLE = re.compile(r"\bbutton-style-\d+\b")
_INLINE_COLOR = re.compile(
    r"(?:^|;|\{)\s*(?:color|background-color)\s*:", re.IGNORECASE
)


def check_theme_classes(editor: Tag, soup: BeautifulSoup) -> dict:
    """Score theme-class coverage for headings, text, and buttons.

    Also flags inline color/background-color in per-page <style> blocks
    scoped to content IDs as informational.
    """
    details: list[str] = []
    fractions: list[float] = []

    headings = editor.find_all(class_="vj-heading")
    if headings:
        styled = [h for h in headings if any(_HEAD_STYLE.search(c) for c in (h.get("class") or []))]
        frac = len(styled) / len(headings)
        fractions.append(frac)
        if frac < 1.0:
            details.append(
                f"{len(headings) - len(styled)}/{len(headings)} .vj-heading elements missing head-style-N class"
            )

    texts = editor.find_all(class_="vj-text")
    if texts:
        styled = [t for t in texts if any(_PARA_STYLE.search(c) for c in (t.get("class") or []))]
        frac = len(styled) / len(texts)
        fractions.append(frac)
        if frac < 1.0:
            details.append(
                f"{len(texts) - len(styled)}/{len(texts)} .vj-text elements missing paragraph-style-N class"
            )

    buttons = editor.find_all(class_="btn")
    if buttons:
        styled = [b for b in buttons if any(_BTN_STYLE.search(c) for c in (b.get("class") or []))]
        frac = len(styled) / len(buttons)
        fractions.append(frac)
        if frac < 1.0:
            details.append(
                f"{len(buttons) - len(styled)}/{len(buttons)} .btn elements missing button-style-N class"
            )

    # Informational: per-page <style> blocks with inline color declarations
    for style_tag in soup.find_all("style"):
        css_text = style_tag.get_text()
        if _INLINE_COLOR.search(css_text) and re.search(r"#vjEditor|#dnn_ContentPane", css_text):
            details.append(
                "Per-page <style> block contains inline color/background-color declarations "
                "(informational — prefer theme classes)"
            )
            break

    if not fractions:
        score = 100
        summary = "No theme-classified elements found (vj-heading, vj-text, .btn)"
    else:
        coverage = sum(fractions) / len(fractions)
        score = int(100 * coverage)
        summary = f"Theme-class coverage: {score}% across headings/text/buttons"

    return {
        "check": "theme-classes",
        "score": score,
        "summary": summary,
        "details": details,
    }

# ---------------------------------------------------------------------------
# Check: responsive-images
# ---------------------------------------------------------------------------


def check_responsive_images(editor: Tag, scan: _EditorScan | None = None) -> dict:
    """Score the fraction of images wrapped in <picture> with srcset variants.

    Excludes images inside DNN module subtrees. Reference sites: ~100%.
    """
    if scan is None:
        scan = _EditorScan(editor)
    details: list[str] = []
    plain_imgs: list[str] = []
    total = 0

    for img, in_module in scan.images:
        if in_module:
            continue
        total += 1
        parent = img.parent
        if isinstance(parent, Tag) and parent.name == "picture":
            sources = parent.find_all("source")
            has_versions = any(
                "/.versions/" in (src.get("srcset") or "")
                for src in sources
                if isinstance(src, Tag)
            )
            if not has_versions:
                src_val = img.get("src") or "(no src)"
                details.append(f"<picture> wrapper missing /.versions/ srcset: {src_val}")
                plain_imgs.append(str(src_val))
        else:
            src_val = img.get("src") or "(no src)"
            plain_imgs.append(str(src_val))
            details.append(f"Unwrapped <img>: {src_val}")

    responsive = total - len(plain_imgs)
    score = int(100 * responsive / total) if total > 0 else 100
    summary = (
        f"{responsive}/{total} image(s) have /.versions/ srcset wrappers"
        if total > 0
        else "No images found"
    )

    return {
        "check": "responsive-images",
        "score": score,
        "summary": summary,
        "details": details[:20],
    }

# ---------------------------------------------------------------------------
# Check: composition
# ---------------------------------------------------------------------------

_GOOD_CHILD_MIN = 3
_GOOD_CHILD_MAX = 9
_GOOD_DEPTH_MAX = 20


def check_composition(editor: Tag, scan: _EditorScan | None = None) -> dict:
    """Score top-level child count and max DOM depth under #vjEditor.

    Good ranges (from reference data):
      - Top-level children: 3-9
      - Max DOM depth: <= 20
    Also reports raw <section> count as informational.
    """
    if scan is None:
        scan = _EditorScan(editor)
    details: list[str] = []

    child_count = len(scan.top_level_children)
    raw_sections = scan.section_count
    depth = scan.max_depth

    child_score: int
    if _GOOD_CHILD_MIN <= child_count <= _GOOD_CHILD_MAX:
        child_score = 100
    elif child_count < _GOOD_CHILD_MIN:
        child_score = max(0, 100 - 20 * (_GOOD_CHILD_MIN - child_count))
    else:
        child_score = max(0, 100 - 10 * (child_count - _GOOD_CHILD_MAX))

    depth_score = 100 if depth <= _GOOD_DEPTH_MAX else max(0, 100 - 5 * (depth - _GOOD_DEPTH_MAX))

    score = (child_score + depth_score) // 2

    if child_count < _GOOD_CHILD_MIN:
        details.append(f"Too few top-level children: {child_count} (target: {_GOOD_CHILD_MIN}-{_GOOD_CHILD_MAX})")
    elif child_count > _GOOD_CHILD_MAX:
        details.append(f"Too many top-level children: {child_count} (target: {_GOOD_CHILD_MIN}-{_GOOD_CHILD_MAX})")

    if depth > _GOOD_DEPTH_MAX:
        details.append(f"DOM depth {depth} exceeds target (<= {_GOOD_DEPTH_MAX})")

    details.append(f"Raw <section> count: {raw_sections} (informational)")

    summary = (
        f"Top-level children: {child_count}, max depth: {depth}, sections: {raw_sections}"
    )

    return {
        "check": "composition",
        "score": score,
        "summary": summary,
        "details": details,
    }

# ---------------------------------------------------------------------------
# Page-level audit entry point
# ---------------------------------------------------------------------------


def audit_page(url: str, html: str, soup: BeautifulSoup | None = None) -> dict:
    """Run all per-page checks against rendered HTML and return a PageAudit dict.

    ``soup`` lets a caller that already parsed the HTML (e.g. ``audit_site``,
    which parses every page once for the global-blocks check) hand the parsed
    document back instead of re-parsing. When omitted the HTML is parsed here.
    """
    if soup is None:
        soup = BeautifulSoup(html, "html.parser")
    editor = _vj_editor(soup)

    checks: dict[str, dict] = {}

    if editor is None:
        placeholder: dict = {
            "check": "",
            "score": 0,
            "summary": "#vjEditor not found — page may not be a Vanjaro content page",
            "details": [],
        }
        for name in ("inline-styles", "theme-classes", "responsive-images", "composition"):
            checks[name] = {**placeholder, "check": name}
        page_score = 0.0
    else:
        scan = _EditorScan(editor)
        checks["inline-styles"] = check_inline_styles(editor, scan)
        checks["theme-classes"] = check_theme_classes(editor, soup)
        checks["responsive-images"] = check_responsive_images(editor, scan)
        checks["composition"] = check_composition(editor, scan)
        page_score = sum(c["score"] for c in checks.values()) / len(checks)

    return {
        "url": url,
        "checks": checks,
        "score": round(page_score, 1),
    }

# ---------------------------------------------------------------------------
# Site-level audit entry point (adds global-blocks check)
# ---------------------------------------------------------------------------


def audit_site(pages: list[tuple[str, str]]) -> dict:
    """Audit a set of pages and produce an AuditReport dict.

    ``pages`` is a list of ``(url, html)`` pairs. The global-blocks check is
    evaluated across all pages together; per-page checks run independently.
    """
    parsed_pages: list[tuple[str, BeautifulSoup]] = [
        (url, BeautifulSoup(html, "html.parser")) for url, html in pages
    ]

    page_audits = [
        audit_page(url, html, soup)
        for (url, html), (_, soup) in zip(pages, parsed_pages)
    ]

    global_blocks_finding = check_global_blocks(parsed_pages)

    # Incorporate global-blocks score into composite
    all_scores = [page_audit["score"] for page_audit in page_audits]

    site_score = (
        (sum(all_scores) / len(all_scores) + global_blocks_finding["score"]) / 2
        if all_scores
        else float(global_blocks_finding["score"])
    )

    return {
        "pages": page_audits,
        "site_checks": {
            "global-blocks": global_blocks_finding,
        },
        "score": round(site_score, 1),
    }
