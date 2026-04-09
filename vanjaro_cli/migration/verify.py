"""Phase 5 migration verification — pure comparator logic and gap report model.

Given the artifacts from a crawl and the content fetched from the migrated
Vanjaro site, produce a structured gap report that names anything that did
not make it across: missing text, unreferenced or unuploaded images,
unrewritten links, structural drift, and metadata mismatches.

Everything in this module is pure — no I/O, no Vanjaro client calls. The
CLI in :mod:`vanjaro_cli.commands.migrate_verify_cmd` loads the inputs and
hands them to :func:`verify_page` / :func:`verify_global_block`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from vanjaro_cli.migration.content_walk import WalkedContent, walk_grapesjs_tree
from vanjaro_cli.migration.text_match import (
    TextMatchResult,
    fuzzy_set_match,
    normalize_text,
    score_text_match,
)

__all__ = [
    "GlobalBlockReport",
    "ImageGap",
    "ImageReport",
    "LinkGap",
    "LinkReport",
    "MetadataReport",
    "PageReport",
    "Status",
    "StructureReport",
    "collect_source_content",
    "verify_global_block",
    "verify_page",
]


Status = Literal["passed", "failed", "skipped"]


@dataclass
class ImageGap:
    type: str
    src: str

    def as_dict(self) -> dict:
        return {"type": self.type, "src": self.src}


@dataclass
class ImageReport:
    hard_gaps: list[ImageGap] = field(default_factory=list)
    soft_gaps: list[ImageGap] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "hard_gaps": [gap.as_dict() for gap in self.hard_gaps],
            "soft_gaps": [gap.as_dict() for gap in self.soft_gaps],
        }


@dataclass
class LinkGap:
    type: str
    href: str

    def as_dict(self) -> dict:
        return {"type": self.type, "href": self.href}


@dataclass
class LinkReport:
    hard_gaps: list[LinkGap] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"hard_gaps": [gap.as_dict() for gap in self.hard_gaps]}


@dataclass
class StructureReport:
    source_sections: int = 0
    migrated_sections: int = 0
    within_tolerance: bool = True

    def as_dict(self) -> dict:
        return {
            "source_sections": self.source_sections,
            "migrated_sections": self.migrated_sections,
            "within_tolerance": self.within_tolerance,
        }


@dataclass
class MetadataReport:
    title_match: bool = True
    description_match: bool = True
    source_title: str = ""
    migrated_title: str = ""
    source_description: str = ""
    migrated_description: str = ""

    def as_dict(self) -> dict:
        return {
            "title_match": self.title_match,
            "description_match": self.description_match,
            "source_title": self.source_title,
            "migrated_title": self.migrated_title,
            "source_description": self.source_description,
            "migrated_description": self.migrated_description,
        }


@dataclass
class GlobalBlockReport:
    status: Literal["match", "mismatch"]
    missing_headings: list[str] = field(default_factory=list)
    missing_links: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "missing_headings": list(self.missing_headings),
            "missing_links": list(self.missing_links),
        }


@dataclass
class PageReport:
    source_url: str
    page_id: int | None
    status: Status
    text: TextMatchResult
    images: ImageReport
    links: LinkReport
    structure: StructureReport
    metadata: MetadataReport
    header: GlobalBlockReport | None = None
    footer: GlobalBlockReport | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        payload: dict = {
            "source_url": self.source_url,
            "page_id": self.page_id,
            "status": self.status,
            "text": self.text.as_dict(),
            "images": self.images.as_dict(),
            "links": self.links.as_dict(),
            "structure": self.structure.as_dict(),
            "metadata": self.metadata.as_dict(),
        }
        if self.header is not None:
            payload["header"] = self.header.as_dict()
        if self.footer is not None:
            payload["footer"] = self.footer.as_dict()
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


def collect_source_content(source_sections: list[dict]) -> WalkedContent:
    """Flatten crawl section dicts into a :class:`WalkedContent` snapshot.

    Mirrors :func:`walk_grapesjs_tree` output so the same comparator can
    diff both sides. Each section increments ``section_count`` — the crawler
    only emits top-level sections so nesting is not a concern.
    """
    walked = WalkedContent()
    for section in source_sections:
        if not isinstance(section, dict):
            continue
        walked.section_count += 1
        content = section.get("content", {})
        if not isinstance(content, dict):
            continue

        for heading in content.get("headings", []) or []:
            if isinstance(heading, str) and heading.strip():
                walked.headings.append(heading)

        for paragraph in content.get("paragraphs", []) or []:
            if isinstance(paragraph, str) and paragraph.strip():
                walked.paragraphs.append(paragraph)

        for image in content.get("images", []) or []:
            if isinstance(image, dict):
                src = image.get("src", "")
                if isinstance(src, str) and src:
                    walked.images.append(src)

        for link in content.get("links", []) or []:
            if isinstance(link, dict):
                href = link.get("href", "")
                if isinstance(href, str) and href:
                    walked.links.append(href)

        for button in content.get("buttons", []) or []:
            if isinstance(button, dict):
                href = button.get("href", "")
                if isinstance(href, str) and href:
                    walked.links.append(href)

    return walked


def verify_page(
    source_sections: list[dict],
    migrated_components: list[dict],
    asset_manifest: list[dict],
    source_page: dict,
    migrated_page: dict,
    text_threshold: float = 0.9,
    *,
    page_id: int | None = None,
    source_url: str = "",
    known_vanjaro_paths: set[str] | None = None,
) -> PageReport:
    """Compare a source page against its migrated counterpart."""
    source_content = collect_source_content(source_sections)
    migrated_content = walk_grapesjs_tree(migrated_components)

    text_result = score_text_match(
        source_content.headings,
        source_content.paragraphs,
        migrated_content.headings,
        migrated_content.paragraphs,
        threshold=text_threshold,
    )

    image_report = _compare_images(
        source_content.images, migrated_content.images, asset_manifest
    )
    link_report = _compare_links(
        migrated_content.links,
        source_url=source_url,
        known_vanjaro_paths=known_vanjaro_paths,
    )
    structure_report = _compare_structure(
        source_content.section_count, migrated_content.section_count
    )
    metadata_report = _compare_metadata(source_page, migrated_page)

    status: Status = "passed"
    if not text_result.passed:
        status = "failed"
    if image_report.hard_gaps or link_report.hard_gaps:
        status = "failed"

    return PageReport(
        source_url=source_url or _safe_get(source_page, "url"),
        page_id=page_id,
        status=status,
        text=text_result,
        images=image_report,
        links=link_report,
        structure=structure_report,
        metadata=metadata_report,
    )


def verify_global_block(
    source_global: dict,
    migrated_global_components: list[dict],
) -> GlobalBlockReport:
    """Compare a crawled header/footer section against a Vanjaro global block.

    Checks that every source heading and every source link label also
    appears in the migrated block (fuzzy match). Missing items are reported;
    extras are ignored (a global block may carry site chrome that the source
    didn't have).
    """
    content = source_global.get("content", {}) if isinstance(source_global, dict) else {}

    source_headings = [
        heading
        for heading in content.get("headings", []) or []
        if isinstance(heading, str) and heading.strip()
    ]
    source_link_labels = [
        link.get("text", "")
        for link in content.get("links", []) or []
        if isinstance(link, dict) and isinstance(link.get("text"), str) and link["text"].strip()
    ]

    migrated = walk_grapesjs_tree(migrated_global_components)

    _, missing_headings = fuzzy_set_match(source_headings, migrated.headings)
    _, missing_links = fuzzy_set_match(source_link_labels, migrated.link_labels)

    status: Literal["match", "mismatch"] = (
        "match" if not missing_headings and not missing_links else "mismatch"
    )
    return GlobalBlockReport(
        status=status,
        missing_headings=missing_headings,
        missing_links=missing_links,
    )


def _compare_images(
    source_images: list[str],
    migrated_images: list[str],
    asset_manifest: list[dict],
) -> ImageReport:
    """Categorize image gaps into hard and soft tiers.

    Hard gaps break the migration:
      - ``source_url_in_migrated``: a source URL still appears verbatim
      - ``not_in_manifest``: a source image was never crawled/uploaded
      - ``not_uploaded``: in the manifest but no vanjaro_url
      - ``not_referenced``: uploaded but not referenced anywhere in the tree

    Soft gaps are warnings only:
      - ``extra_in_migrated``: an image on the page that wasn't in the source
    """
    report = ImageReport()
    source_set = set(source_images)
    migrated_set = set(migrated_images)

    manifest_by_source: dict[str, dict] = {}
    vanjaro_urls: set[str] = set()
    for entry in asset_manifest:
        if not isinstance(entry, dict):
            continue
        source_url = entry.get("source_url")
        if isinstance(source_url, str) and source_url:
            manifest_by_source[source_url] = entry
        vanjaro_url = entry.get("vanjaro_url")
        if isinstance(vanjaro_url, str) and vanjaro_url:
            vanjaro_urls.add(vanjaro_url)

    # Hard: source URLs that leaked through the rewrite step. `dict.fromkeys`
    # preserves first-seen order while deduping, so a leak referenced five
    # times in the tree only appears once in the report.
    for src in dict.fromkeys(migrated_images):
        if src in source_set or src in manifest_by_source:
            report.hard_gaps.append(ImageGap(type="source_url_in_migrated", src=src))

    for src in dict.fromkeys(source_images):
        entry = manifest_by_source.get(src)
        if entry is None:
            report.hard_gaps.append(ImageGap(type="not_in_manifest", src=src))
            continue
        vanjaro_url = entry.get("vanjaro_url")
        if not isinstance(vanjaro_url, str) or not vanjaro_url:
            report.hard_gaps.append(ImageGap(type="not_uploaded", src=src))
            continue
        if vanjaro_url not in migrated_set:
            report.hard_gaps.append(ImageGap(type="not_referenced", src=src))

    for src in dict.fromkeys(migrated_images):
        if src in vanjaro_urls:
            continue
        if src in source_set or src in manifest_by_source:
            continue  # already reported as a hard gap above
        report.soft_gaps.append(ImageGap(type="extra_in_migrated", src=src))

    return report


def _compare_links(
    migrated_links: list[str],
    *,
    source_url: str,
    known_vanjaro_paths: set[str] | None,
) -> LinkReport:
    """Flag unrewritten source-site URLs and broken internal references."""
    report = LinkReport()
    source_host = urlparse(source_url).netloc.lower() if source_url else ""

    for href in dict.fromkeys(migrated_links):
        if href.startswith("#"):
            continue

        parsed = urlparse(href)
        host = parsed.netloc.lower()

        if source_host and host == source_host:
            report.hard_gaps.append(LinkGap(type="source_url_in_migrated", href=href))
            continue

        if host:
            continue  # external URL — out of scope

        if known_vanjaro_paths is None:
            continue  # no path map loaded, cannot validate internal refs

        normalized = _normalize_path(parsed.path)
        if normalized and normalized not in known_vanjaro_paths:
            report.hard_gaps.append(LinkGap(type="broken_internal", href=href))

    return report


def _compare_structure(source_sections: int, migrated_sections: int) -> StructureReport:
    return StructureReport(
        source_sections=source_sections,
        migrated_sections=migrated_sections,
        within_tolerance=abs(source_sections - migrated_sections) <= 1,
    )


def _compare_metadata(source_page: dict, migrated_page: dict) -> MetadataReport:
    """Normalized title/description comparison.

    Description comparison is skipped (treated as a match) when the source
    side has no description — the crawler does not yet extract meta
    descriptions, so an empty source means "unknown" rather than "empty".
    """
    source_title = normalize_text(_safe_get(source_page, "title"))
    migrated_title = normalize_text(_safe_get(migrated_page, "title"))
    source_description = normalize_text(_safe_get(source_page, "description"))
    migrated_description = normalize_text(_safe_get(migrated_page, "description"))

    description_match = (
        not source_description or source_description == migrated_description
    )

    return MetadataReport(
        title_match=source_title == migrated_title,
        description_match=description_match,
        source_title=source_title,
        migrated_title=migrated_title,
        source_description=source_description,
        migrated_description=migrated_description,
    )


def _safe_get(data: object, key: str) -> str:
    if not isinstance(data, dict):
        return ""
    value = data.get(key, "")
    return value if isinstance(value, str) else ""


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    trimmed = path.rstrip("/")
    return trimmed or "/"


