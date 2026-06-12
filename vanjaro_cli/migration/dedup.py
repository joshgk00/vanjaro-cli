"""Detect sections that repeat across pages so they can become global blocks.

Hand-built Vanjaro sites register a section that appears on multiple pages
(a CTA strip, a testimonial band) ONCE as a global block and reference it on
each page via a ``globalblockwrapper``. The migration crawler instead writes
an independent section file per page. This module finds the repeats by
fingerprinting normalized section content and groups the duplicates so the
dedup command can collapse them into a single global block.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

__all__ = [
    "DuplicateGroup",
    "GLOBAL_KEY_PLACEHOLDER",
    "find_duplicate_groups",
    "global_placeholder",
    "humanize_key",
    "normalize_section",
    "parse_global_placeholder",
    "section_fingerprint",
]

# A dedup stub's wrapper carries its target global block as a ``{{global:KEY}}``
# token instead of a real GUID — the block isn't registered until
# ``blocks build-library`` runs, so assemble resolves the token afterward.
GLOBAL_KEY_PLACEHOLDER = "{{global:%s}}"
_GLOBAL_PLACEHOLDER_PATTERN = re.compile(r"^\{\{global:(?P<key>.+)\}\}$")


def global_placeholder(key: str) -> str:
    """Return the ``{{global:KEY}}`` placeholder string for a dedup key."""
    return GLOBAL_KEY_PLACEHOLDER % key


def parse_global_placeholder(value: str) -> str | None:
    """Return the dedup key inside a ``{{global:KEY}}`` token, or None if not one."""
    match = _GLOBAL_PLACEHOLDER_PATTERN.match(value)
    return match.group("key") if match else None


def _strip_query(url: str) -> str:
    """Drop a URL's query string and fragment, keeping scheme/host/path.

    Cache-busting and CDN-resize query params (``?ver``, ``?w``, ``?h``,
    ``?mode``, ``?anchor``) vary between otherwise-identical sections, so they
    must not influence the fingerprint. Link/button targets keep their path —
    sections that link to different destinations are NOT duplicates.
    """
    if not isinstance(url, str):
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _normalize_images(images: object) -> list[dict[str, str]]:
    """Reduce an images list to ``[{src(path-only), alt}]`` for hashing.

    Responsive-source noise (``srcset``, ``srcset_urls``, ``picture_source``)
    is dropped because it carries the same images at different resolutions and
    jitters between crawls.
    """
    if not isinstance(images, list):
        return []
    normalized: list[dict[str, str]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        normalized.append({
            "src": _strip_query(image.get("src", "")),
            "alt": image.get("alt", "") if isinstance(image.get("alt"), str) else "",
        })
    return normalized


def _normalize_links(links: object) -> list[dict[str, str]]:
    """Reduce a links/buttons list to ``[{text, href(path-only)}]`` for hashing."""
    if not isinstance(links, list):
        return []
    normalized: list[dict[str, str]] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        normalized.append({
            "text": link.get("text", "") if isinstance(link.get("text"), str) else "",
            "href": _strip_query(link.get("href", "")),
        })
    return normalized


def _string_list(values: object) -> list[str]:
    """Coerce a content field into a list of strings, dropping other shapes."""
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def normalize_section(section: dict) -> dict:
    """Strip crawl noise from a section so structural duplicates hash alike.

    Excluded from the fingerprint: ``background_color``, ``text_color``,
    ``background_image`` (CSS annotation jitter), per-element ids, image query
    strings, and responsive-source variants. Included: type, template,
    headings, paragraphs, list items, blockquotes, normalized images, and
    normalized links/buttons.
    """
    content = section.get("content")
    if not isinstance(content, dict):
        content = {}

    return {
        "type": section.get("type", ""),
        "template": section.get("template", ""),
        "headings": _string_list(content.get("headings")),
        "paragraphs": _string_list(content.get("paragraphs")),
        "list_items": _string_list(content.get("list_items")),
        "blockquotes": _string_list(content.get("blockquotes")),
        "images": _normalize_images(content.get("images")),
        "links": _normalize_links(content.get("links")),
        "buttons": _normalize_links(content.get("buttons")),
    }


def section_fingerprint(section: dict) -> str:
    """Return a SHA-256 hex digest of the section's normalized content."""
    normalized = normalize_section(section)
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _slugify(value: str) -> str:
    """Convert arbitrary text to a lowercase hyphenated slug."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def humanize_key(key: str) -> str:
    """Turn a dedup key like ``global-cta-get-started`` into a block name."""
    words = key.split("-")
    return " ".join(word.capitalize() for word in words if word)


def _group_key(section: dict) -> str:
    """Derive a stable, human-readable key from a section's type and heading."""
    section_type = _slugify(str(section.get("type", "")) or "section")
    content = section.get("content")
    first_heading = ""
    if isinstance(content, dict):
        headings = content.get("headings")
        if isinstance(headings, list):
            for heading in headings:
                if isinstance(heading, str) and heading.strip():
                    first_heading = heading
                    break
                if isinstance(heading, dict) and isinstance(heading.get("text"), str):
                    first_heading = heading["text"]
                    break
    heading_slug = _slugify(first_heading)
    parts = ["global", section_type]
    if heading_slug:
        parts.append(heading_slug)
    return "-".join(parts)


class DuplicateGroup:
    """A set of section files across distinct pages sharing one fingerprint.

    ``member_sections`` pairs each member file with the section dict parsed
    while fingerprinting, so the dedup command can back up the original section
    without re-reading the file from disk.
    """

    def __init__(self, key: str, canonical: dict, canonical_file: Path) -> None:
        self.key = key
        self.canonical = canonical
        self.canonical_file = canonical_file
        self.member_sections: list[tuple[Path, dict]] = [(canonical_file, canonical)]
        self.pages: list[str] = []

    @property
    def member_files(self) -> list[Path]:
        """The member files, in order."""
        return [section_file for section_file, _ in self.member_sections]

    @property
    def name(self) -> str:
        """Human-readable block name derived from the key."""
        return humanize_key(self.key)


def _page_of(section_file: Path, pages_dir: Path) -> str:
    """Return the page directory name a section file belongs to."""
    try:
        relative = section_file.relative_to(pages_dir)
    except ValueError:
        return section_file.parent.name
    return relative.parts[0] if relative.parts else section_file.parent.name


def find_duplicate_groups(pages_dir: Path) -> list[DuplicateGroup]:
    """Group section files that share a fingerprint across >= 2 distinct pages.

    Same-page repeats don't count toward the distinct-page threshold — a
    section that appears twice on one page is page content, not site chrome.
    Keys are made unique by suffixing a counter when two different
    fingerprints would otherwise collide on the same type+heading slug.
    """
    pages_dir = Path(pages_dir)
    section_files = sorted(pages_dir.glob("*/section-*.json"))

    fingerprint_members: dict[str, list[tuple[Path, str, dict]]] = {}
    for section_file in section_files:
        try:
            section = json.loads(section_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(section, dict):
            continue
        fingerprint = section_fingerprint(section)
        page = _page_of(section_file, pages_dir)
        fingerprint_members.setdefault(fingerprint, []).append(
            (section_file, page, section)
        )

    groups: list[DuplicateGroup] = []
    used_keys: set[str] = set()
    for fingerprint in sorted(fingerprint_members):
        members = fingerprint_members[fingerprint]
        distinct_pages = {page for _, page, _ in members}
        if len(distinct_pages) < 2:
            continue

        canonical_file, _, canonical = members[0]
        base_key = _group_key(canonical)
        key = base_key
        suffix = 2
        while key in used_keys:
            key = f"{base_key}-{suffix}"
            suffix += 1
        used_keys.add(key)

        group = DuplicateGroup(key, canonical, canonical_file)
        group.member_sections = [
            (section_file, section) for section_file, _, section in members
        ]
        group.pages = sorted(distinct_pages)
        groups.append(group)

    return groups
