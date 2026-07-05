"""Tests for vanjaro_cli.migration.gap_report — pure functions."""

from __future__ import annotations

from vanjaro_cli.migration.gap_report import (
    GapItem,
    GapReport,
    gaps_from_audit,
    gaps_from_verify,
    gaps_from_vision_json,
    gaps_from_visual_report,
    merge_and_sort,
    render_markdown,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_verify_json(
    *,
    passed: int = 0,
    failed: int = 0,
    skipped: int = 0,
    reports: list[dict] | None = None,
) -> dict:
    return {
        "inventory": "site-inventory.json",
        "pages": {"passed": passed, "failed": failed, "skipped": skipped},
        "reports": reports or [],
    }


def _make_page_report(
    source_url: str,
    status: str = "passed",
    *,
    text_passed: bool = True,
    text_score: float = 1.0,
    text_threshold: float = 0.9,
    missing_headings: list[str] | None = None,
    missing_paragraphs: list[str] | None = None,
    image_hard_gaps: list[dict] | None = None,
    link_hard_gaps: list[dict] | None = None,
    title_match: bool = True,
    description_match: bool = True,
    source_title: str = "Title",
    migrated_title: str = "Title",
    source_description: str = "",
    migrated_description: str = "",
    within_tolerance: bool = True,
    source_sections: int = 3,
    migrated_sections: int = 3,
) -> dict:
    return {
        "source_url": source_url,
        "page_id": 1,
        "status": status,
        "text": {
            "score": text_score,
            "threshold": text_threshold,
            "passed": text_passed,
            "matched_headings": 0,
            "missing_headings": missing_headings or [],
            "matched_paragraphs": 0,
            "missing_paragraphs": missing_paragraphs or [],
        },
        "images": {"hard_gaps": image_hard_gaps or [], "soft_gaps": []},
        "links": {"hard_gaps": link_hard_gaps or []},
        "structure": {
            "source_sections": source_sections,
            "migrated_sections": migrated_sections,
            "within_tolerance": within_tolerance,
        },
        "metadata": {
            "title_match": title_match,
            "description_match": description_match,
            "source_title": source_title,
            "migrated_title": migrated_title,
            "source_description": source_description,
            "migrated_description": migrated_description,
        },
    }


def _make_audit_json(
    pages: list[dict] | None = None,
    site_checks: dict | None = None,
    score: float = 85.0,
) -> dict:
    return {
        "pages": pages or [],
        "site_checks": site_checks or {},
        "score": score,
    }


def _make_page_audit(url: str, checks: dict[str, dict], score: float = 75.0) -> dict:
    return {"url": url, "checks": checks, "score": score}


def _make_check(name: str, score: int, summary: str = "", details: list[str] | None = None) -> dict:
    return {
        "check": name,
        "score": score,
        "summary": summary or f"{name} score {score}",
        "details": details or [],
    }


# ---------------------------------------------------------------------------
# gaps_from_verify — text gap
# ---------------------------------------------------------------------------


def test_verify_text_gap_produces_high_severity():
    report = _make_page_report(
        "https://example.com/",
        status="failed",
        text_passed=False,
        text_score=0.72,
        missing_headings=["About Us"],
        missing_paragraphs=["We build great things."],
    )
    items = gaps_from_verify(_make_verify_json(reports=[report]))

    text_items = [i for i in items if "Text match score" in i.description]
    assert len(text_items) == 1
    item = text_items[0]
    assert item.severity == "high"
    assert item.category == "content"
    assert item.source == "verify"
    assert "72%" in item.description
    assert "1 heading" in item.description
    assert "1 paragraph" in item.description


# ---------------------------------------------------------------------------
# gaps_from_verify — image gaps
# ---------------------------------------------------------------------------


def test_verify_image_hard_gap_types():
    gap_types = ["not_in_manifest", "not_uploaded", "not_referenced", "source_url_in_migrated"]
    hard_gaps = [{"type": t, "src": f"/img-{t}.jpg"} for t in gap_types]
    report = _make_page_report(
        "https://example.com/",
        status="failed",
        image_hard_gaps=hard_gaps,
    )
    items = gaps_from_verify(_make_verify_json(reports=[report]))

    image_items = [i for i in items if i.category == "content" and "Image gap" in i.description]
    assert len(image_items) == 4
    for item in image_items:
        assert item.severity == "high"
        assert item.source == "verify"


# ---------------------------------------------------------------------------
# gaps_from_verify — link gaps
# ---------------------------------------------------------------------------


def test_verify_link_gap_source_url():
    report = _make_page_report(
        "https://example.com/about",
        status="failed",
        link_hard_gaps=[{"type": "source_url_in_migrated", "href": "https://old-site.com/page"}],
    )
    items = gaps_from_verify(_make_verify_json(reports=[report]))

    link_items = [i for i in items if "Link gap" in i.description]
    assert len(link_items) == 1
    assert link_items[0].severity == "high"
    assert "rewrite-urls" in link_items[0].suggested_action


def test_verify_link_gap_broken_internal():
    report = _make_page_report(
        "https://example.com/services",
        status="failed",
        link_hard_gaps=[{"type": "broken_internal", "href": "/deleted-page"}],
    )
    items = gaps_from_verify(_make_verify_json(reports=[report]))
    link_items = [i for i in items if "Link gap" in i.description]
    assert len(link_items) == 1
    assert "Vanjaro" in link_items[0].suggested_action


# ---------------------------------------------------------------------------
# gaps_from_verify — metadata gaps
# ---------------------------------------------------------------------------


def test_verify_title_mismatch_is_medium():
    report = _make_page_report(
        "https://example.com/",
        title_match=False,
        source_title="Home Page",
        migrated_title="Welcome",
    )
    items = gaps_from_verify(_make_verify_json(reports=[report]))
    title_items = [i for i in items if "title mismatch" in i.description]
    assert len(title_items) == 1
    assert title_items[0].severity == "medium"


def test_verify_description_mismatch_is_low():
    report = _make_page_report(
        "https://example.com/",
        description_match=False,
        source_description="We build software.",
        migrated_description="",
    )
    items = gaps_from_verify(_make_verify_json(reports=[report]))
    desc_items = [i for i in items if "description mismatch" in i.description]
    assert len(desc_items) == 1
    assert desc_items[0].severity == "low"


# ---------------------------------------------------------------------------
# gaps_from_verify — structure drift
# ---------------------------------------------------------------------------


def test_verify_structure_drift_is_medium():
    report = _make_page_report(
        "https://example.com/",
        within_tolerance=False,
        source_sections=5,
        migrated_sections=2,
    )
    items = gaps_from_verify(_make_verify_json(reports=[report]))
    struct_items = [i for i in items if "Section count drift" in i.description]
    assert len(struct_items) == 1
    assert struct_items[0].severity == "medium"
    assert struct_items[0].category == "structure"


# ---------------------------------------------------------------------------
# gaps_from_verify — skipped pages ignored
# ---------------------------------------------------------------------------


def test_verify_skipped_pages_produce_no_gaps():
    report = {
        "source_url": "https://example.com/",
        "status": "skipped",
        "text": {"passed": True, "score": 1.0, "threshold": 0.9},
        "images": {"hard_gaps": [], "soft_gaps": []},
        "links": {"hard_gaps": []},
        "structure": {"within_tolerance": True},
        "metadata": {"title_match": True, "description_match": True},
    }
    items = gaps_from_verify(_make_verify_json(reports=[report]))
    assert items == []


# ---------------------------------------------------------------------------
# gaps_from_verify — global block mismatch
# ---------------------------------------------------------------------------


def test_verify_header_block_mismatch():
    report = _make_page_report("https://example.com/")
    report["header"] = {
        "status": "mismatch",
        "missing_headings": ["Services"],
        "missing_links": ["About", "Contact"],
    }
    items = gaps_from_verify(_make_verify_json(reports=[report]))
    block_items = [i for i in items if "Header global block" in i.description]
    assert len(block_items) == 1
    assert block_items[0].severity == "medium"
    assert "1 missing heading" in block_items[0].description
    assert "2 missing link" in block_items[0].description


# ---------------------------------------------------------------------------
# gaps_from_audit — per-page checks
# ---------------------------------------------------------------------------


def test_audit_high_severity_below_50():
    page = _make_page_audit(
        "https://vanjaro.local/",
        {
            "inline-styles": _make_check("inline-styles", 20, "20 inline style attributes"),
        },
    )
    items = gaps_from_audit(_make_audit_json(pages=[page]))
    assert len(items) == 1
    assert items[0].severity == "high"
    assert items[0].category == "structure"
    assert items[0].source == "audit"
    assert "Remove inline style" in items[0].suggested_action


def test_audit_medium_severity_50_to_79():
    page = _make_page_audit(
        "https://vanjaro.local/about",
        {"theme-classes": _make_check("theme-classes", 65, "Theme-class coverage: 65%")},
    )
    items = gaps_from_audit(_make_audit_json(pages=[page]))
    assert len(items) == 1
    assert items[0].severity == "medium"


def test_audit_low_severity_80_to_99():
    page = _make_page_audit(
        "https://vanjaro.local/services",
        {"responsive-images": _make_check("responsive-images", 90, "9/10 images responsive")},
    )
    items = gaps_from_audit(_make_audit_json(pages=[page]))
    assert len(items) == 1
    assert items[0].severity == "low"


def test_audit_perfect_score_produces_no_gap():
    page = _make_page_audit(
        "https://vanjaro.local/",
        {"composition": _make_check("composition", 100)},
    )
    items = gaps_from_audit(_make_audit_json(pages=[page]))
    assert items == []


# ---------------------------------------------------------------------------
# gaps_from_audit — site-wide global-blocks check
# ---------------------------------------------------------------------------


def test_audit_site_wide_global_blocks_gap():
    site_checks = {
        "global-blocks": _make_check(
            "global-blocks",
            40,
            "0 sitewide global blocks; 3 pages missing wrappers",
            details=["Pages missing global-block wrappers: /, /about, /services"],
        )
    }
    items = gaps_from_audit(_make_audit_json(site_checks=site_checks))
    assert len(items) == 1
    assert items[0].page == "(site-wide)"
    assert items[0].severity == "high"
    assert "global-blocks" in items[0].description


# ---------------------------------------------------------------------------
# gaps_from_audit — details attached to description
# ---------------------------------------------------------------------------


def test_audit_details_included_in_description():
    page = _make_page_audit(
        "https://vanjaro.local/",
        {
            "inline-styles": _make_check(
                "inline-styles",
                70,
                "3 inline style attributes",
                details=["div.hero", "span.accent"],
            )
        },
    )
    items = gaps_from_audit(_make_audit_json(pages=[page]))
    assert "div.hero" in items[0].description


# ---------------------------------------------------------------------------
# gaps_from_visual_report
# ---------------------------------------------------------------------------

_SAMPLE_VISUAL_REPORT = """\
# Visual Discrepancy Report

## Summary

3 pages compared, 4 issues found.

## https://example.com/

- [high] Hero image missing entirely
- Missing navigation link color

## https://example.com/about

- Footer background is wrong color (medium severity)
"""


def test_visual_report_basic_parse():
    items = gaps_from_visual_report(_SAMPLE_VISUAL_REPORT)
    assert len(items) == 3
    pages = {i.page for i in items}
    assert "https://example.com/" in pages
    assert "https://example.com/about" in pages


def test_visual_report_severity_extraction():
    items = gaps_from_visual_report(_SAMPLE_VISUAL_REPORT)
    high_items = [i for i in items if i.severity == "high"]
    assert len(high_items) == 1
    assert "Hero image" in high_items[0].description


def test_visual_report_defaults_to_medium():
    items = gaps_from_visual_report(_SAMPLE_VISUAL_REPORT)
    medium_items = [i for i in items if i.severity == "medium"]
    assert len(medium_items) >= 1


def test_visual_report_all_items_are_visual_category():
    items = gaps_from_visual_report(_SAMPLE_VISUAL_REPORT)
    for item in items:
        assert item.category == "visual"
        assert item.source == "visual"


def test_visual_report_empty_string_returns_empty():
    assert gaps_from_visual_report("") == []
    assert gaps_from_visual_report("   \n  ") == []


def test_visual_report_no_issues_section_returns_empty():
    assert gaps_from_visual_report("# Summary\n\nAll looks good.\n") == []


# ---------------------------------------------------------------------------
# merge_and_sort
# ---------------------------------------------------------------------------


def test_merge_and_sort_ordering():
    items = [
        GapItem("https://b.com/", "content", "low", "low b", "verify", "action"),
        GapItem("https://a.com/", "content", "high", "high a", "verify", "action"),
        GapItem("https://a.com/", "structure", "medium", "med a", "audit", "action"),
        GapItem("https://b.com/", "content", "high", "high b", "verify", "action"),
    ]
    merged = merge_and_sort([items])
    assert merged[0].page == "https://a.com/"
    assert merged[0].severity == "high"
    assert merged[1].page == "https://a.com/"
    assert merged[1].severity == "medium"
    assert merged[2].page == "https://b.com/"
    assert merged[2].severity == "high"
    assert merged[3].page == "https://b.com/"
    assert merged[3].severity == "low"


def test_merge_and_sort_empty_lists():
    assert merge_and_sort([]) == []
    assert merge_and_sort([[], []]) == []


def test_merge_and_sort_combines_multiple_sources():
    verify_items = [GapItem("https://a.com/", "content", "high", "d", "verify", "a")]
    audit_items = [GapItem("https://a.com/", "structure", "medium", "d", "audit", "a")]
    merged = merge_and_sort([verify_items, audit_items])
    assert len(merged) == 2
    sources = {i.source for i in merged}
    assert sources == {"verify", "audit"}


# ---------------------------------------------------------------------------
# GapReport property helpers
# ---------------------------------------------------------------------------


def test_gap_report_counts():
    items = [
        GapItem("p1", "content", "high", "d", "verify", "a"),
        GapItem("p1", "content", "high", "d2", "verify", "a"),
        GapItem("p2", "structure", "medium", "d3", "audit", "a"),
        GapItem("p3", "visual", "low", "d4", "visual", "a"),
    ]
    report = GapReport(items=items)
    assert report.high_count == 2
    assert report.medium_count == 1
    assert report.low_count == 1


def test_gap_report_as_list_shape():
    item = GapItem("https://x.com/", "content", "high", "desc", "verify", "do this")
    report = GapReport(items=[item])
    lst = report.as_list()
    assert len(lst) == 1
    entry = lst[0]
    assert entry["page"] == "https://x.com/"
    assert entry["category"] == "content"
    assert entry["severity"] == "high"
    assert entry["description"] == "desc"
    assert entry["source"] == "verify"
    assert entry["suggested_action"] == "do this"


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_summary_header():
    items = [
        GapItem("https://a.com/", "content", "high", "Image missing", "verify", "Fix it"),
        GapItem("(site-wide)", "structure", "medium", "Global blocks", "audit", "Add globals"),
    ]
    md = render_markdown(items, verify_score=75.0, audit_score=82.5)

    assert "# Migration Gap Report" in md
    assert "## Summary" in md
    assert "75.0%" in md
    assert "82.5/100" in md
    assert "Total gaps: **2**" in md
    assert "High: 1 | Medium: 1 | Low: 0" in md


def test_render_markdown_per_page_section():
    items = [
        GapItem("https://a.com/page", "content", "high", "Text gap", "verify", "Fix text"),
    ]
    md = render_markdown(items)
    assert "### https://a.com/page" in md
    assert "[HIGH]" in md
    assert "Text gap" in md
    assert "*Action*: Fix text" in md


def test_render_markdown_site_wide_section():
    items = [
        GapItem("(site-wide)", "structure", "high", "No global blocks", "audit", "Add globals"),
    ]
    md = render_markdown(items)
    assert "## Site-Wide Items" in md
    assert "No global blocks" in md
    assert "## Per-Page Punch List" not in md


def test_render_markdown_no_gaps():
    md = render_markdown([])
    assert "No gaps found" in md


def test_render_markdown_scores_optional():
    md = render_markdown([])
    assert "verify" not in md.lower() or "score" not in md.lower()
    assert "audit" not in md.lower() or "score" not in md.lower()


def test_gaps_from_vision_json_maps_systemic_and_page_findings():
    payload = {
        "overall_score": 64,
        "systemic_findings": [
            {
                "id": "missing-section-color-bands",
                "severity": "high",
                "issue": "Colored background bands missing sitewide.",
                "code_hint": "sections.py background resolution",
            },
        ],
        "pages": [
            {
                "slug": "home",
                "score": 42,
                "findings": [
                    {"severity": "high", "component": "Hero/Banner", "issue": "Hero section absent."},
                    {"severity": "low", "issue": "Minor spacing difference."},
                ],
            },
        ],
    }

    items = gaps_from_vision_json(payload)

    assert len(items) == 3
    sitewide = items[0]
    assert sitewide.page == "(sitewide)"
    assert sitewide.severity == "high"
    assert sitewide.suggested_action == "sections.py background resolution"
    hero = items[1]
    assert hero.page == "home"
    assert hero.description == "Hero/Banner: Hero section absent."
    assert items[2].severity == "low"


def test_gaps_from_vision_json_empty_payload():
    assert gaps_from_vision_json({}) == []
