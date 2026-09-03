"""Scoped secret scanning tests using synthetic canaries only."""

from __future__ import annotations

from pathlib import Path

from vanjaro_cli.reliability.secret_scan import scan_declared_files


def test_clean_declared_files_produce_stable_pass_report(tmp_path: Path) -> None:
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "report.json").write_text(
        '{"schema_version":"1.0","status":"passed"}\n', encoding="utf-8"
    )
    first = scan_declared_files(tmp_path, ("qa/report.json",))
    second = scan_declared_files(tmp_path, ("qa/report.json",))

    assert first == second
    assert first.status == "passed"
    assert first.scanned_file_count == 1


def test_scan_reports_locations_but_never_secret_values(tmp_path: Path) -> None:
    (tmp_path / "qa").mkdir()
    canary = "synthetic-do-not-emit"
    (tmp_path / "qa" / "report.json").write_text(
        '{"nested":{"api_key":"' + canary + '"},'
        '"url":"https://example.test/?signature=' + canary + '"}',
        encoding="utf-8",
    )
    report = scan_declared_files(tmp_path, ("qa/report.json",))

    assert report.status == "failed"
    assert {item.rule_id for item in report.findings} == {
        "sensitive-json-key",
        "sensitive-url-query",
    }
    assert canary not in report.model_dump_json()


def test_scan_detects_sensitive_url_fragments_without_echoing_them(tmp_path: Path) -> None:
    canary = "synthetic-fragment-canary"
    (tmp_path / "report.txt").write_text(
        f"https://example.test/callback#access_token={canary}\n", encoding="utf-8"
    )

    report = scan_declared_files(tmp_path, ("report.txt",))

    assert {item.rule_id for item in report.findings} == {"sensitive-url-fragment"}
    assert canary not in report.model_dump_json()


def test_text_rules_find_authorization_and_private_key_headers(tmp_path: Path) -> None:
    (tmp_path / "report.log").write_text(
        "Authorization: Bearer synthetic-token\n-----BEGIN PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    report = scan_declared_files(tmp_path, ("report.log",))

    assert {item.rule_id for item in report.findings} == {
        "authorization-value",
        "private-key-header",
    }
    assert "synthetic-token" not in report.model_dump_json()


def test_forbidden_and_malformed_declared_inputs_fail_closed(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PASSWORD=synthetic", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    report = scan_declared_files(tmp_path, (".env", "broken.json", "../escape.json"))

    assert report.status == "failed"
    assert {item.code for item in report.errors} == {
        "forbidden-scope",
        "invalid-json",
        "path-escape",
    }


def test_parent_symlink_and_normalized_traversal_are_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "report.json").write_text('{"status":"passed"}', encoding="utf-8")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        import pytest

        pytest.skip("directory symlinks are unavailable on this Windows host")

    report = scan_declared_files(
        tmp_path,
        ("alias/report.json", "real/../real/report.json", "real/report.json"),
    )

    assert report.status == "failed"
    assert {(item.path, item.code) for item in report.errors} == {
        ("alias/report.json", "symlink"),
        ("real/../real/report.json", "path-escape"),
    }
    assert report.scanned_file_count == 1
