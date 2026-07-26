"""Focused tests for the read-only project draft verification gate."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.sources import HtmlSourceRequest, analyze_source
from vanjaro_cli.orchestration import project_verify
from vanjaro_cli.project import ProjectSource, create_manifest
from vanjaro_cli.project.models import ProjectStage
from vanjaro_cli.project.stage_engine import StageContext


HEADER_GUID = "header-guid"
FOOTER_GUID = "footer-guid"


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(
        self,
        *,
        page: dict[str, object],
        header: dict[str, object] | None = None,
        footer: dict[str, object] | None = None,
    ) -> None:
        self.page = page
        self.globals = {
            HEADER_GUID: header or _global_detail("header", HEADER_GUID, 2),
            FOOTER_GUID: footer or _global_detail("footer", FOOTER_GUID, 2),
        }
        self.gets: list[tuple[str, dict[str, object]]] = []

    def get(self, path: str, *, params: dict[str, object]) -> _Response:
        self.gets.append((path, params))
        if path == project_verify.GET_PAGE:
            return _Response(self.page)
        if path == project_verify.GET_GLOBAL:
            return _Response(self.globals[str(params["guid"])])
        raise AssertionError(f"unexpected GET {path}")


def _global_detail(
    kind: str,
    guid: str,
    version: int,
    *,
    published: bool = False,
) -> dict[str, object]:
    return {
        "guid": guid,
        "name": kind.title(),
        "version": version,
        "isPublished": published,
        "contentJSON": [
            {
                "type": "section",
                "attributes": {"id": f"global-{kind}"},
                "components": [
                    {"type": "text", "content": f"{kind.title()} chrome"}
                ],
            }
        ],
        "styleJSON": [],
    }


def _page_detail(
    *,
    version: int = 3,
    published: bool = False,
    header_guid: str = HEADER_GUID,
    footer_guid: str = FOOTER_GUID,
    text: tuple[str, ...] = ("Welcome", "Real body copy", "Contact"),
) -> dict[str, object]:
    components: list[dict[str, object]] = [
        _wrapper("Header", header_guid, "wrapper-header"),
        {
            "type": "section",
            "attributes": {"id": "body-section"},
            "components": [
                {
                    "type": "text",
                    "attributes": {"id": f"body-text-{index}"},
                    "content": value,
                }
                for index, value in enumerate(text, 1)
            ],
        },
        _wrapper("Footer", footer_guid, "wrapper-footer"),
    ]
    return {
        "tabId": 41,
        "version": version,
        "isPublished": published,
        "contentJSON": components,
        "styleJSON": [],
        "contentHtml": "<section>draft</section>",
    }


def _wrapper(name: str, guid: str, identifier: str) -> dict[str, object]:
    return {
        "type": "globalblockwrapper",
        "name": f"Global: {name}",
        "attributes": {"id": identifier, "data-guid": guid},
        "components": [],
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _context(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: _Client,
    *,
    include_sample_copy: bool = False,
    mapped_action: bool = True,
) -> StageContext:
    action = (
        '<a href="/contact">Contact</a>'
        if mapped_action
        else '<a href="">Contact</a>'
    )
    sample = "<p>Lorem ipsum placeholder text</p>" if include_sample_copy else ""
    document = analyze_source(
        HtmlSourceRequest(
            html=(
                "<html><body><main><section><h1>Welcome</h1>"
                "<p>Real body copy</p>"
                f"{sample}{action}</section></main></body></html>"
            ),
            source_url="https://source.example/",
            slug="home",
        )
    )
    design_path = root / "build/design-document.json"
    design_path.parent.mkdir(parents=True, exist_ok=True)
    design_path.write_text(serialize_design_document(document), encoding="utf-8")
    _write_json(
        root / "build/global-page-manifest.json",
        {
            "schema_version": "1.0",
            "pages": [
                {
                    "key": "home",
                    "page_id": 41,
                    "path": "/agency-home",
                    "observed_version": 3,
                }
            ],
        },
    )
    _write_json(
        root / "build/global-block-manifest.json",
        {
            "schema_version": "1.0",
            "blocks": [
                {
                    "key": "global-header",
                    "kind": "header",
                    "guid": HEADER_GUID,
                    "observed_version": 2,
                    "warnings": [],
                },
                {
                    "key": "global-footer",
                    "kind": "footer",
                    "guid": FOOTER_GUID,
                    "observed_version": 2,
                    "warnings": [],
                },
            ],
        },
    )
    manifest = create_manifest(
        name="Verify",
        target_profile="verify-profile",
        expected_base_url="https://target.example",
        expected_portal_id=7,
        sources=[
            ProjectSource(
                id="html-1",
                kind=SourceKind.LIVE_HTML,
                reference="https://source.example/",
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1",
        clock=lambda: datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    verified = SimpleNamespace(
        portal_id=7,
        as_dict=lambda: {
            "profile": "verify-profile",
            "base_url": "https://target.example",
            "portal_id": 7,
        },
    )
    monkeypatch.setattr(
        project_verify,
        "verify_project_portal",
        lambda _manifest: (client, verified),
    )
    monkeypatch.setattr(
        project_verify,
        "audit_page",
        lambda _path, _html: {"score": 100, "findings": []},
    )
    return StageContext(
        root=root,
        stage=ProjectStage.VERIFY,
        manifest=manifest,
        input_fingerprint="a" * 64,
        attempt=1,
    )


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: _Client,
    **context_options: object,
) -> dict[str, object]:
    context = _context(tmp_path, monkeypatch, client, **context_options)
    result = project_verify.verify_project_drafts(context)
    assert result.artifacts == ("verify/draft-verification.json",)
    return json.loads(
        (tmp_path / "verify/draft-verification.json").read_text(encoding="utf-8")
    )


def test_verify_project_drafts_accepts_complete_unpublished_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _Client(page=_page_detail())

    report = _run(tmp_path, monkeypatch, client)

    assert report["valid"] is True
    assert report["blocker_count"] == 0
    assert report["source_text_coverage"] == 1.0
    assert report["missing_action_url_count"] == 0
    assert report["pages"][0]["global_wrappers"] == 2
    assert [path for path, _ in client.gets] == [
        project_verify.GET_GLOBAL,
        project_verify.GET_GLOBAL,
        project_verify.GET_PAGE,
    ]


def test_verify_project_drafts_blocks_source_action_without_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _Client(page=_page_detail())

    report = _run(
        tmp_path,
        monkeypatch,
        client,
        mapped_action=False,
    )

    assert report["valid"] is False
    assert report["missing_action_url_count"] == 1
    assert len(report["missing_action_url_element_ids"]) == 1
    assert "1 source action(s) have no URL mapping" in report["blockers"]


def test_verify_project_drafts_excludes_sample_copy_from_text_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _Client(page=_page_detail())

    report = _run(
        tmp_path,
        monkeypatch,
        client,
        include_sample_copy=True,
    )

    assert report["valid"] is True
    assert report["source_text_total"] == 3
    assert report["source_text_matched"] == 3
    assert report["missing_source_text"] == []


def test_verify_project_drafts_blocks_wrapper_version_and_publish_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _Client(
        page=_page_detail(
            version=4,
            published=True,
            header_guid="wrong-header-guid",
        ),
        header=_global_detail(
            "header", HEADER_GUID, 2, published=True
        ),
        footer=_global_detail("footer", FOOTER_GUID, 3),
    )

    report = _run(tmp_path, monkeypatch, client)

    assert report["valid"] is False
    blockers = report["blockers"]
    assert "page 41: page is already published" in blockers
    assert "page 41: draft version differs from the managed manifest" in blockers
    assert "page 41: global wrapper GUIDs do not match the managed globals" in blockers
    assert "global header: desired version is already published" in blockers
    assert "global footer: version differs from the managed manifest" in blockers
