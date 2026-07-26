"""Re-upload Keys to Success assets to capture their /.versions/ variant lists.

Uploads are idempotent (they overwrite the same portal file), and the
AIAsset/Upload response carries the generated responsive variants. We key the
captured variants by the *stripped* portal path (no ?ver= cache-buster) so the
content transform can match them against the image src values already in
content.json regardless of which ver hash each side happens to hold.

Writes artifacts/keys-to-success/asset-manifest.json in the schema
`vanjaro migrate rewrite-urls` expects (source_url / vanjaro_url / variants).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from vanjaro_cli.client import VanjaroClient
from vanjaro_cli.config import load_config

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "artifacts" / "keys-to-success"
ASSETS = SITE / "assets"
UPLOAD = "/API/VanjaroAI/AIAsset/Upload"
FOLDER = "keys-to-success/"


def _strip_ver(url: str) -> str:
    return url.split("?", 1)[0]


def main() -> None:
    config = load_config(profile_name="keys-to-success")
    client = VanjaroClient(config)

    asset_urls: dict[str, str] = json.loads(
        (SITE / "asset-urls.json").read_text(encoding="utf-8")
    )

    manifest: list[dict] = []
    for filename, old_url in asset_urls.items():
        local = ASSETS / filename
        if not local.exists():
            print(f"MISSING local file, skipping: {filename}")
            continue
        payload = {
            "fileName": filename,
            "folderPath": FOLDER,
            "base64Content": base64.b64encode(local.read_bytes()).decode("ascii"),
        }
        response = client.post(UPLOAD, json=payload)
        body = response.json()
        variants = body.get("variants") or body.get("Variants") or []
        manifest.append(
            {
                "source_url": old_url,
                "vanjaro_url": old_url,
                "stripped_url": _strip_ver(old_url),
                "filename": filename,
                "variants": variants,
            }
        )
        print(f"{filename}: {len(variants)} variant(s)")

    out = SITE / "asset-manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(manifest)} entries)")


if __name__ == "__main__":
    main()
