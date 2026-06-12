"""Unified post-migration gap report — aggregates content, structure, and visual gaps.

All functions are pure: no I/O, no network calls. The CLI in
:mod:`vanjaro_cli.commands.migrate_gap_report_cmd` loads inputs and hands them
to the functions here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from vanjaro_cli.migration.audit import SCORE_HIGH_BELOW, SCORE_MEDIUM_BELOW

__all__ = [
    "GapItem",
    "GapReport",
    "Severity",
    "compute_verify_score",
    "gaps_from_audit",
    "gaps_from_verify",
    "gaps_from_visual_report",
    "merge_and_sort",
    "render_markdown",
]

Severity = Literal["high", "medium", "low"]
Category = Literal["content", "structure", "visual"]
Source = Literal["verify", "audit", "visual"]

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class GapItem:
    page: str
    category: Category
    severity: Severity
    description: str
    source: Source
    suggested_action: str


@dataclass
class GapReport:
    items: list[GapItem]

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.items if i.severity == "high")

    @property
    def medium_count(self) -> int:
        return sum(1 for i in self.items if i.severity == "medium")

    @property
    def low_count(self) -> int:
        return sum(1 for i in self.items if i.severity == "low")

    def as_list(self) -> list[dict]:
        return [
            {
                "page": item.page,
                "category": item.category,
                "severity": item.severity,
                "description": item.description,
                "source": item.source,
                "suggested_action": item.suggested_action,
            }
            for item in self.items
        ]


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------


def _audit_check_severity(score: int) -> Severity:
    if score < SCORE_HIGH_BELOW:
        return "high"
    if score < SCORE_MEDIUM_BELOW:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Gaps from verify-all JSON output
# ---------------------------------------------------------------------------

_IMAGE_GAP_ACTIONS: dict[str, str] = {
    "source_url_in_migrated": (
        "Re-run `vanjaro migrate rewrite-urls` to replace source image URLs with "
        "Vanjaro portal paths."
    ),
    "not_in_manifest": (
        "Add the image to the asset manifest and upload via `vanjaro assets upload-dir`."
    ),
    "not_uploaded": (
        "Upload the asset via `vanjaro assets upload-dir`, then verify the manifest entry."
    ),
    "not_referenced": (
        "Re-assemble or manually edit the page to reference the uploaded Vanjaro image path."
    ),
}

_LINK_GAP_ACTIONS: dict[str, str] = {
    "source_url_in_migrated": (
        "Re-run `vanjaro migrate rewrite-urls` to replace source-site links with "
        "Vanjaro relative paths."
    ),
    "broken_internal": (
        "Verify the target page exists in Vanjaro and fix the link via the page editor."
    ),
}


def gaps_from_verify(verify_json: dict) -> list[GapItem]:
    """Derive GapItems from a verify-all JSON report."""
    items: list[GapItem] = []
    for report in verify_json.get("reports", []) or []:
        if not isinstance(report, dict):
            continue
        if report.get("status") == "skipped":
            continue

        page = report.get("source_url", "unknown")

        # Text gaps
        text = report.get("text") or {}
        if isinstance(text, dict) and not text.get("passed", True):
            score = float(text.get("score", 0))
            threshold = float(text.get("threshold", 0.9))
            missing_h = len(text.get("missing_headings", []) or [])
            missing_p = len(text.get("missing_paragraphs", []) or [])
            items.append(GapItem(
                page=page,
                category="content",
                severity="high",
                description=(
                    f"Text match score {score:.0%} is below threshold {threshold:.0%}. "
                    f"Missing: {missing_h} heading(s), {missing_p} paragraph(s)."
                ),
                source="verify",
                suggested_action=(
                    "Compare the source page against the migrated page and fill in "
                    "missing headings and paragraphs in the Vanjaro page editor."
                ),
            ))

        # Image hard gaps
        for gap in (report.get("images", {}) or {}).get("hard_gaps", []) or []:
            if not isinstance(gap, dict):
                continue
            gap_type = gap.get("type", "unknown")
            src = gap.get("src", "")
            action = _IMAGE_GAP_ACTIONS.get(
                gap_type,
                "Investigate and fix image reference manually.",
            )
            items.append(GapItem(
                page=page,
                category="content",
                severity="high",
                description=f"Image gap ({gap_type}): {src}",
                source="verify",
                suggested_action=action,
            ))

        # Link hard gaps
        for gap in (report.get("links", {}) or {}).get("hard_gaps", []) or []:
            if not isinstance(gap, dict):
                continue
            gap_type = gap.get("type", "unknown")
            href = gap.get("href", "")
            action = _LINK_GAP_ACTIONS.get(
                gap_type,
                "Fix the link reference manually in the Vanjaro page editor.",
            )
            items.append(GapItem(
                page=page,
                category="content",
                severity="high",
                description=f"Link gap ({gap_type}): {href}",
                source="verify",
                suggested_action=action,
            ))

        # Metadata mismatches
        meta = report.get("metadata") or {}
        if isinstance(meta, dict):
            if not meta.get("title_match", True):
                items.append(GapItem(
                    page=page,
                    category="content",
                    severity="medium",
                    description=(
                        f"Page title mismatch. Source: \"{meta.get('source_title', '')}\" "
                        f"vs migrated: \"{meta.get('migrated_title', '')}\"."
                    ),
                    source="verify",
                    suggested_action=(
                        "Update the page title in Vanjaro via the page settings editor."
                    ),
                ))
            if not meta.get("description_match", True):
                items.append(GapItem(
                    page=page,
                    category="content",
                    severity="low",
                    description=(
                        f"Meta description mismatch. Source: \"{meta.get('source_description', '')}\" "
                        f"vs migrated: \"{meta.get('migrated_description', '')}\"."
                    ),
                    source="verify",
                    suggested_action=(
                        "Update the meta description in Vanjaro page settings."
                    ),
                ))

        # Structure drift
        structure = report.get("structure") or {}
        if isinstance(structure, dict) and not structure.get("within_tolerance", True):
            source_s = structure.get("source_sections", 0)
            migrated_s = structure.get("migrated_sections", 0)
            items.append(GapItem(
                page=page,
                category="structure",
                severity="medium",
                description=(
                    f"Section count drift: source has {source_s} section(s), "
                    f"migrated has {migrated_s}."
                ),
                source="verify",
                suggested_action=(
                    "Review the page layout in the Vanjaro editor and add or "
                    "merge sections to match the source structure."
                ),
            ))

        # Global block mismatches
        for block_label, block_key in (("header", "header"), ("footer", "footer")):
            block = report.get(block_key)
            if not isinstance(block, dict):
                continue
            if block.get("status") == "mismatch":
                missing_h = block.get("missing_headings", []) or []
                missing_l = block.get("missing_links", []) or []
                items.append(GapItem(
                    page=page,
                    category="content",
                    severity="medium",
                    description=(
                        f"{block_label.capitalize()} global block mismatch: "
                        f"{len(missing_h)} missing heading(s), {len(missing_l)} missing link(s)."
                    ),
                    source="verify",
                    suggested_action=(
                        f"Edit the {block_label} global block in Vanjaro to add "
                        "missing headings and navigation links."
                    ),
                ))

    return items


def compute_verify_score(verify_json: dict) -> float | None:
    """Derive a simple content-fidelity percentage from verify-all output."""
    reports = verify_json.get("reports", []) or []
    if not isinstance(reports, list) or not reports:
        pages_summary = verify_json.get("pages")
        if isinstance(pages_summary, dict):
            passed = int(pages_summary.get("passed", 0))
            total = (
                passed
                + int(pages_summary.get("failed", 0))
                + int(pages_summary.get("skipped", 0))
            )
            return 100.0 * passed / total if total > 0 else None
        return None

    counted = [r for r in reports if isinstance(r, dict) and r.get("status") != "skipped"]
    if not counted:
        return None
    passed = sum(1 for r in counted if r.get("status") == "passed")
    return 100.0 * passed / len(counted)


# ---------------------------------------------------------------------------
# Gaps from audit JSON output
# ---------------------------------------------------------------------------

_AUDIT_CHECK_ACTIONS: dict[str, str] = {
    "inline-styles": (
        "Remove inline style= attributes and apply Vanjaro theme classes or "
        "custom CSS rules instead."
    ),
    "theme-classes": (
        "Add head-style-N, paragraph-style-N, and button-style-N theme classes "
        "to headings, text blocks, and buttons via the Vanjaro theme builder."
    ),
    "responsive-images": (
        "Re-upload images through the Vanjaro asset pipeline so they are wrapped "
        "in <picture> tags with /.versions/ srcset variants."
    ),
    "composition": (
        "Review the page layout: aim for 3-9 top-level sections and a max DOM "
        "depth of 20 by reorganizing or merging blocks in the Vanjaro editor."
    ),
    "global-blocks": (
        "Convert repeated sections to global blocks via the Vanjaro block library "
        "and ensure every page has a global header/footer wrapper."
    ),
}

_SITE_LEVEL_PAGE = "(site-wide)"


def gaps_from_audit(audit_json: dict) -> list[GapItem]:
    """Derive GapItems from an audit-structure JSON report."""
    items: list[GapItem] = []

    for page_audit in audit_json.get("pages", []) or []:
        if not isinstance(page_audit, dict):
            continue
        page = page_audit.get("url", "unknown")
        for check_name, finding in (page_audit.get("checks", {}) or {}).items():
            if not isinstance(finding, dict):
                continue
            score = int(finding.get("score", 100))
            if score >= 100:
                continue
            severity = _audit_check_severity(score)
            summary = finding.get("summary", check_name)
            details = finding.get("details", []) or []
            detail_text = "; ".join(str(d) for d in details if not str(d).startswith("Raw <section>"))
            description = f"{check_name} score {score}/100: {summary}"
            if detail_text:
                description = f"{description} — {detail_text}"
            items.append(GapItem(
                page=page,
                category="structure",
                severity=severity,
                description=description,
                source="audit",
                suggested_action=_AUDIT_CHECK_ACTIONS.get(
                    check_name,
                    "Review the audit finding and address manually.",
                ),
            ))

    # Site-wide checks (global-blocks)
    for check_name, finding in (audit_json.get("site_checks", {}) or {}).items():
        if not isinstance(finding, dict):
            continue
        score = int(finding.get("score", 100))
        if score >= 100:
            continue
        severity = _audit_check_severity(score)
        summary = finding.get("summary", check_name)
        details = finding.get("details", []) or []
        detail_text = "; ".join(str(d) for d in details)
        description = f"{check_name} score {score}/100: {summary}"
        if detail_text:
            description = f"{description} — {detail_text}"
        items.append(GapItem(
            page=_SITE_LEVEL_PAGE,
            category="structure",
            severity=severity,
            description=description,
            source="audit",
            suggested_action=_AUDIT_CHECK_ACTIONS.get(
                check_name,
                "Review the site-wide audit finding and address manually.",
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# Gaps from visual report markdown
# ---------------------------------------------------------------------------

_VISUAL_SEVERITY_RE = re.compile(r"\b(high|medium|low)\b", re.IGNORECASE)
_PAGE_HEADER_RE = re.compile(r"^#+\s+(.+)", re.MULTILINE)
_ISSUE_RE = re.compile(r"^\s*[-*]\s+(.+)", re.MULTILINE)


def gaps_from_visual_report(report_text: str) -> list[GapItem]:
    """Derive GapItems from a visual-report markdown string.

    The visual report produced by the migration-visual-report skill is a
    markdown file with per-page sections. Each section contains a bulleted
    list of discrepancies. This parser extracts those bullets and infers
    severity from any ``high``/``medium``/``low`` label embedded in the
    bullet text, defaulting to ``medium``.

    The format is treated as best-effort: if the markdown doesn't match the
    expected shape the function returns an empty list rather than erroring.
    """
    items: list[GapItem] = []
    if not report_text or not report_text.strip():
        return items

    current_page = "(unknown)"
    lines = report_text.splitlines()
    in_issues = False

    for line in lines:
        header_match = _PAGE_HEADER_RE.match(line)
        if header_match:
            heading_text = header_match.group(1).strip()
            # Skip non-page headings like "Summary" or "Overview"
            if any(w in heading_text.lower() for w in ("summary", "overview", "report", "visual")):
                in_issues = False
                continue
            current_page = heading_text
            in_issues = True
            continue

        if not in_issues:
            continue

        issue_match = _ISSUE_RE.match(line)
        if not issue_match:
            continue

        description = issue_match.group(1).strip()
        if not description:
            continue

        severity_match = _VISUAL_SEVERITY_RE.search(description)
        severity: Severity = severity_match.group(1).lower() if severity_match else "medium"  # type: ignore[assignment]

        items.append(GapItem(
            page=current_page,
            category="visual",
            severity=severity,
            description=description,
            source="visual",
            suggested_action=(
                "Compare the source screenshot against the migrated page and fix "
                "layout, color, or content differences in the Vanjaro editor."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# Merge + sort
# ---------------------------------------------------------------------------


def merge_and_sort(item_lists: list[list[GapItem]]) -> list[GapItem]:
    """Merge multiple GapItem lists and sort by page then severity."""
    all_items: list[GapItem] = []
    for lst in item_lists:
        all_items.extend(lst)
    return sorted(all_items, key=lambda i: (i.page, _SEVERITY_ORDER[i.severity]))


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_SEVERITY_BADGE = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}


def render_markdown(
    items: list[GapItem],
    *,
    verify_score: float | None = None,
    audit_score: float | None = None,
) -> str:
    """Render a human-readable markdown punch list from a merged GapItem list."""
    report = GapReport(items=items)
    lines: list[str] = []

    lines.append("# Migration Gap Report")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    if verify_score is not None:
        lines.append(f"- Content fidelity score (verify): **{verify_score:.1f}%**")
    if audit_score is not None:
        lines.append(f"- Structure quality score (audit): **{audit_score:.1f}/100**")
    lines.append(f"- Total gaps: **{len(items)}**")
    lines.append(
        f"  - High: {report.high_count} | Medium: {report.medium_count} | Low: {report.low_count}"
    )
    lines.append("")

    if not items:
        lines.append("No gaps found. The migration looks complete.")
        return "\n".join(lines)

    site_items = [i for i in items if i.page == _SITE_LEVEL_PAGE]
    page_items = [i for i in items if i.page != _SITE_LEVEL_PAGE]

    pages_seen: list[str] = []
    for item in page_items:
        if item.page not in pages_seen:
            pages_seen.append(item.page)

    if pages_seen:
        lines.append("## Per-Page Punch List")
        lines.append("")

    for page in pages_seen:
        page_gaps = [i for i in page_items if i.page == page]
        lines.append(f"### {page}")
        lines.append("")
        for gap in page_gaps:
            badge = _SEVERITY_BADGE[gap.severity]
            lines.append(f"- {badge} **{gap.category}** ({gap.source}): {gap.description}")
            lines.append(f"  - *Action*: {gap.suggested_action}")
        lines.append("")

    if site_items:
        lines.append("## Site-Wide Items")
        lines.append("")
        for gap in site_items:
            badge = _SEVERITY_BADGE[gap.severity]
            lines.append(f"- {badge} **{gap.category}** ({gap.source}): {gap.description}")
            lines.append(f"  - *Action*: {gap.suggested_action}")
        lines.append("")

    return "\n".join(lines)
