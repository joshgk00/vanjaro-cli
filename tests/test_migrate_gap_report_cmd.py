"""Tests for vanjaro migrate gap-report command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.cli import cli


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_verify_json(
    *,
    reports: list[dict] | None = None,
    passed: int = 1,
    failed: int = 0,
) -> dict:
    return {
        "inventory": "site-inventory.json",
        "pages": {"passed": passed, "failed": failed, "skipped": 0},
        "reports": reports or [],
    }


def _make_page_report(
    source_url: str,
    status: str = "passed",
    *,
    text_passed: bool = True,
    text_score: float = 1.0,
    image_hard_gaps: list[dict] | None = None,
    link_hard_gaps: list[dict] | None = None,
    title_match: bool = True,
    within_tolerance: bool = True,
) -> dict:
    return {
        "source_url": source_url,
        "page_id": 1,
        "status": status,
        "text": {
            "score": text_score,
            "threshold": 0.9,
            "passed": text_passed,
            "matched_headings": 1,
            "missing_headings": [],
            "matched_paragraphs": 1,
            "missing_paragraphs": [],
        },
        "images": {"hard_gaps": image_hard_gaps or [], "soft_gaps": []},
        "links": {"hard_gaps": link_hard_gaps or []},
        "structure": {
            "source_sections": 3,
            "migrated_sections": 3 if within_tolerance else 1,
            "within_tolerance": within_tolerance,
        },
        "metadata": {
            "title_match": title_match,
            "description_match": True,
            "source_title": "Source Title",
            "migrated_title": "Different Title" if not title_match else "Source Title",
            "source_description": "",
            "migrated_description": "",
        },
    }


def _make_audit_json(score: float = 85.0, page_url: str = "https://vanjaro.local/") -> dict:
    return {
        "pages": [
            {
                "url": page_url,
                "score": 75.0,
                "checks": {
                    "inline-styles": {
                        "check": "inline-styles",
                        "score": 70,
                        "summary": "3 inline style attributes",
                        "details": ["div.hero"],
                    },
                    "theme-classes": {
                        "check": "theme-classes",
                        "score": 100,
                        "summary": "Theme-class coverage: 100%",
                        "details": [],
                    },
                    "responsive-images": {
                        "check": "responsive-images",
                        "score": 100,
                        "summary": "All images responsive",
                        "details": [],
                    },
                    "composition": {
                        "check": "composition",
                        "score": 100,
                        "summary": "Good composition",
                        "details": [],
                    },
                },
            }
        ],
        "site_checks": {
            "global-blocks": {
                "check": "global-blocks",
                "score": 80,
                "summary": "1 sitewide global block",
                "details": [],
            }
        },
        "score": score,
    }


def _build_migration_root(tmp_path: Path) -> Path:
    root = tmp_path / "migration"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_gap_report_requires_at_least_one_input(runner, mock_config, tmp_path):
    root = _build_migration_root(tmp_path)
    result = runner.invoke(cli, ["migrate", "gap-report", str(root)])
    assert result.exit_code != 0
    assert "At least one" in result.output or "At least one" in str(result.exception)


def test_gap_report_missing_verify_json_file(runner, mock_config, tmp_path):
    root = _build_migration_root(tmp_path)
    result = runner.invoke(
        cli,
        ["migrate", "gap-report", str(root), "--verify-json", str(tmp_path / "nonexistent.json")],
    )
    assert result.exit_code != 0


def test_gap_report_missing_audit_json_file(runner, mock_config, tmp_path):
    root = _build_migration_root(tmp_path)
    result = runner.invoke(
        cli,
        ["migrate", "gap-report", str(root), "--audit-json", str(tmp_path / "nonexistent.json")],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Happy path: verify-only
# ---------------------------------------------------------------------------


def test_gap_report_verify_only_no_gaps(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=[_make_page_report("https://example.com/", "passed")]),
    )

    result = runner.invoke(
        cli,
        ["migrate", "gap-report", str(root), "--verify-json", str(verify_path)],
    )
    assert result.exit_code == 0, result.output
    assert "0 gap" in result.output or "gap(s)" in result.output

    md_path = root / "gap-report.md"
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "# Migration Gap Report" in content


def test_gap_report_verify_only_with_failures(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    failed_report = _make_page_report(
        "https://example.com/",
        status="failed",
        text_passed=False,
        text_score=0.65,
        image_hard_gaps=[{"type": "not_in_manifest", "src": "https://example.com/hero.jpg"}],
    )
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=[failed_report], passed=0, failed=1),
    )

    result = runner.invoke(
        cli,
        ["migrate", "gap-report", str(root), "--verify-json", str(verify_path)],
    )
    assert result.exit_code == 0, result.output
    # At least 2 gaps: text gap + image gap
    assert "2 gap" in result.output or "3 gap" in result.output or "gap(s)" in result.output

    md_path = root / "gap-report.md"
    content = md_path.read_text(encoding="utf-8")
    assert "[HIGH]" in content
    assert "https://example.com/" in content


# ---------------------------------------------------------------------------
# Happy path: audit-only
# ---------------------------------------------------------------------------


def test_gap_report_audit_only(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    audit_path = write_json(tmp_path / "audit.json", _make_audit_json())

    result = runner.invoke(
        cli,
        ["migrate", "gap-report", str(root), "--audit-json", str(audit_path)],
    )
    assert result.exit_code == 0, result.output

    md_path = root / "gap-report.md"
    content = md_path.read_text(encoding="utf-8")
    assert "inline-styles" in content
    assert "82.5/100" in content or "85.0/100" in content


# ---------------------------------------------------------------------------
# Happy path: both inputs
# ---------------------------------------------------------------------------


def test_gap_report_verify_and_audit(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(
            reports=[_make_page_report("https://example.com/", title_match=False)],
        ),
    )
    audit_path = write_json(tmp_path / "audit.json", _make_audit_json())

    result = runner.invoke(
        cli,
        [
            "migrate", "gap-report", str(root),
            "--verify-json", str(verify_path),
            "--audit-json", str(audit_path),
        ],
    )
    assert result.exit_code == 0, result.output

    md_path = root / "gap-report.md"
    content = md_path.read_text(encoding="utf-8")
    assert "## Summary" in content
    # Verify score line present
    assert "Content fidelity score" in content
    # Audit score line present
    assert "Structure quality score" in content


# ---------------------------------------------------------------------------
# Visual report input (optional)
# ---------------------------------------------------------------------------


_SAMPLE_VISUAL_MD = """\
# Visual Report

## https://example.com/

- [high] Hero image missing
- Logo color is wrong
"""


def test_gap_report_with_visual_report(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=[_make_page_report("https://example.com/")]),
    )
    visual_path = tmp_path / "visual-report.md"
    visual_path.write_text(_SAMPLE_VISUAL_MD, encoding="utf-8")

    result = runner.invoke(
        cli,
        [
            "migrate", "gap-report", str(root),
            "--verify-json", str(verify_path),
            "--visual-report", str(visual_path),
        ],
    )
    assert result.exit_code == 0, result.output

    md_path = root / "gap-report.md"
    content = md_path.read_text(encoding="utf-8")
    assert "Hero image missing" in content
    assert "visual" in content


# ---------------------------------------------------------------------------
# Custom output paths
# ---------------------------------------------------------------------------


def test_gap_report_custom_output_path(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=[_make_page_report("https://example.com/")]),
    )
    custom_output = tmp_path / "custom" / "my-report.md"

    result = runner.invoke(
        cli,
        [
            "migrate", "gap-report", str(root),
            "--verify-json", str(verify_path),
            "--output", str(custom_output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert custom_output.exists()


def test_gap_report_json_output(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    failed_report = _make_page_report(
        "https://example.com/",
        status="failed",
        text_passed=False,
        text_score=0.5,
    )
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=[failed_report], passed=0, failed=1),
    )
    json_out = tmp_path / "gaps.json"

    result = runner.invoke(
        cli,
        [
            "migrate", "gap-report", str(root),
            "--verify-json", str(verify_path),
            "--json", str(json_out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json_out.exists()

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert "total" in payload
    assert "items" in payload
    assert isinstance(payload["items"], list)
    assert payload["total"] >= 1
    item = payload["items"][0]
    assert "page" in item
    assert "severity" in item
    assert "category" in item
    assert "description" in item
    assert "source" in item
    assert "suggested_action" in item


# ---------------------------------------------------------------------------
# --as-json stdout output
# ---------------------------------------------------------------------------


def test_gap_report_as_json_stdout(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=[_make_page_report("https://example.com/")]),
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "gap-report", str(root),
            "--verify-json", str(verify_path),
            "--as-json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert "total" in payload
    assert "high" in payload
    assert "medium" in payload
    assert "low" in payload
    assert "output" in payload


# ---------------------------------------------------------------------------
# Markdown content assertions
# ---------------------------------------------------------------------------


def test_markdown_contains_severity_badges(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    failed_report = _make_page_report(
        "https://example.com/",
        status="failed",
        text_passed=False,
        text_score=0.4,
        title_match=False,
    )
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=[failed_report], passed=0, failed=1),
    )

    runner.invoke(
        cli,
        ["migrate", "gap-report", str(root), "--verify-json", str(verify_path)],
    )

    content = (root / "gap-report.md").read_text(encoding="utf-8")
    assert "[HIGH]" in content
    assert "[MED]" in content


def test_markdown_per_page_punch_list_structure(runner, mock_config, tmp_path, write_json):
    root = _build_migration_root(tmp_path)
    reports = [
        _make_page_report("https://example.com/", within_tolerance=False),
        _make_page_report("https://example.com/about", title_match=False),
    ]
    verify_path = write_json(
        tmp_path / "verify.json",
        _make_verify_json(reports=reports),
    )

    runner.invoke(
        cli,
        ["migrate", "gap-report", str(root), "--verify-json", str(verify_path)],
    )

    content = (root / "gap-report.md").read_text(encoding="utf-8")
    assert "## Per-Page Punch List" in content
    assert "### https://example.com/" in content
    assert "### https://example.com/about" in content
    assert "*Action*:" in content
