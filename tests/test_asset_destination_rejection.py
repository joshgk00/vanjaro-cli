"""Upload-acceptance boundary: reject unsafe or ambiguous asset destinations.

``upload_project_assets`` (vanjaro_cli/portal/assets.py) must never report
success for a destination it cannot vouch for -- neither a freshly uploaded
URL nor a cached manifest record considered for reuse -- and must never
silently pick a winner when two assets share the same original source URL.
These tests exercise that acceptance boundary directly with fake upload
clients only; no live requests are made.

See also artifacts/test_css_asset_upload_rejection_independent.py
(root-owned, immutable) for the acceptance proof this file must also keep
passing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.test_portal_assets import FakeClient, _document
from vanjaro_cli.portal.assets import ProjectAssetError, upload_project_assets


def _manifest_asset_ids(tmp_path: Path) -> list[str]:
    manifest_path = tmp_path / "build" / "asset-manifest.json"
    if not manifest_path.exists():
        return []
    return [
        record["asset_id"]
        for record in json.loads(manifest_path.read_text(encoding="utf-8"))["assets"]
    ]


def test_ambiguous_original_source_url_reports_conflicting_asset_identities(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    alias = "https://source.invalid/shared.png"
    document.assets = [
        asset.model_copy(update={"source_url": alias}) for asset in document.assets
    ]
    client = FakeClient()

    with pytest.raises(ProjectAssetError) as excinfo:
        upload_project_assets(
            client,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=[],
        )
    message = str(excinfo.value)
    assert "ambig" in message.lower()
    # The error names both conflicting asset identities, not just "ambiguous".
    assert "first" in message and "second" in message
    # Ambiguity is detected before any upload is attempted.
    assert client.posts == []


def test_unsafe_first_upload_response_rejected_and_nothing_persisted(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)

    class UnsafeClient(FakeClient):
        def post(self, path: str, *, json: dict):
            response = super().post(path, json=json)
            response.value["url"] = "javascript:alert(1)"
            return response

    client = UnsafeClient()
    with pytest.raises(ProjectAssetError, match="(?i)unsafe|invalid|destination"):
        upload_project_assets(
            client,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=[],
        )
    assert _manifest_asset_ids(tmp_path) == []


def test_unsafe_later_response_rejected_but_earlier_safe_upload_persists_and_retry_skips_it(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)

    class SecondUnsafeClient(FakeClient):
        def post(self, path: str, *, json: dict):
            response = super().post(path, json=json)
            if json["fileName"] == "second.jpg":
                response.value["url"] = "data:text/html,<script>1</script>"
            return response

    interrupted = SecondUnsafeClient()
    with pytest.raises(ProjectAssetError, match="(?i)unsafe|invalid|destination"):
        upload_project_assets(
            interrupted,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=[],
        )
    # The safe first upload was persisted before the second one was rejected.
    assert _manifest_asset_ids(tmp_path) == ["first"]

    retry = FakeClient()
    _, _, records = upload_project_assets(
        retry,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=[],
    )
    # No duplicate upload for the already-safe "first" asset.
    assert len(retry.posts) == 1
    assert retry.posts[0]["json"]["fileName"] == "second.jpg"
    assert [record["asset_id"] for record in records] == ["first", "second"]


def test_cached_unsafe_manifest_record_rejected_not_silently_reused(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    content = (tmp_path / "sources" / "first.png").read_bytes()

    manifest_path = tmp_path / "build" / "asset-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "assets": [
                    {
                        "asset_id": "first",
                        "local_path": "sources/first.png",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                        "folder": "Images/agency/project/",
                        "filename": "first.png",
                        "vanjaro_url": "javascript:alert(1)",
                        "vanjaro_file_id": 1,
                        "variants": [],
                        "uploaded": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    client = FakeClient()
    with pytest.raises(ProjectAssetError, match="(?i)unsafe|invalid|cach"):
        upload_project_assets(
            client,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=[],
        )
    # The poisoned cached record is never silently re-uploaded or exposed.
    assert client.posts == []


def test_safe_destination_and_css_variant_still_succeed(tmp_path: Path) -> None:
    document = _document(tmp_path)
    document.assets[0] = document.assets[0].model_copy(
        update={"source_url": "https://source.invalid/first.png"}
    )
    plan = [
        {
            "name": "Hero",
            "overrides": {"image_1_src": "sources/first.png"},
            "style_scope": ".proj .hero",
            "style_declarations": {
                "background-image": 'url("https://source.invalid/first.png")'
            },
        }
    ]
    client = FakeClient()

    portal_document, rewritten, records = upload_project_assets(
        client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    migrated = next(r["vanjaro_url"] for r in records if r["asset_id"] == "first")
    assert migrated.startswith("/Portals/7/")
    assert rewritten[0]["overrides"]["image_1_src"] == migrated
    assert (
        rewritten[0]["style_declarations"]["background-image"] == f'url("{migrated}")'
    )
    assert portal_document.assets[0].local_path is None

    resumed_client = FakeClient()
    _, resumed, _ = upload_project_assets(
        resumed_client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    assert resumed_client.posts == []
    assert resumed == rewritten
