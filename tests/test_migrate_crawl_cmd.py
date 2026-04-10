"""Tests for vanjaro migrate crawl command."""

from __future__ import annotations

import json
from pathlib import Path

import responses

from vanjaro_cli.cli import cli

SOURCE_URL = "https://source-site.test"

HOMEPAGE_HTML = """<!doctype html>
<html>
<head>
  <title>Source Site</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header>
    <nav><a href="/">Home</a><a href="/about">About</a></nav>
  </header>
  <main>
    <section class="hero">
      <h1>Welcome to Source</h1>
      <p>Tagline copy here.</p>
      <img src="/hero.jpg" alt="Hero image">
      <a class="btn" href="/signup">Sign Up</a>
    </section>
    <section class="features">
      <h2>Features</h2>
      <div class="card"><h3>Fast</h3><img src="/fast.jpg" alt=""></div>
      <div class="card"><h3>Safe</h3><img src="/safe.jpg" alt=""></div>
      <div class="card"><h3>Fun</h3><img src="/fun.jpg" alt=""></div>
    </section>
  </main>
  <footer><p>Copyright 2026</p></footer>
</body>
</html>
"""

ABOUT_HTML = """<!doctype html>
<html>
<head><title>About Us</title></head>
<body>
  <main>
    <section>
      <h1>About Us</h1>
      <p>Who we are.</p>
    </section>
  </main>
</body>
</html>
"""

STYLES_CSS = """
body { color: #333333; background: #ffffff; font-family: 'Inter', sans-serif; }
h1 { color: #ff5500; margin: 16px; padding: 8px; }
.btn { background: #333333; padding: 12px 24px; }
"""

FAKE_IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfakepngdata"


def _register_site(rsps: responses.RequestsMock, with_assets: bool = True) -> None:
    """Register mock responses for a two-page fake site."""
    rsps.add(responses.GET, f"{SOURCE_URL}/", body=HOMEPAGE_HTML, status=200)
    rsps.add(responses.GET, f"{SOURCE_URL}/about", body=ABOUT_HTML, status=200)
    rsps.add(responses.GET, f"{SOURCE_URL}/sitemap.xml", status=404)
    rsps.add(responses.GET, f"{SOURCE_URL}/styles.css", body=STYLES_CSS, status=200)
    if with_assets:
        for image_path in ("/hero.jpg", "/fast.jpg", "/safe.jpg", "/fun.jpg"):
            rsps.add(
                responses.GET,
                f"{SOURCE_URL}{image_path}",
                body=FAKE_IMAGE_BYTES,
                status=200,
                content_type="image/jpeg",
            )


@responses.activate
def test_migrate_crawl_writes_inventory_and_sections(runner, tmp_path: Path):
    _register_site(responses.mock)
    output = tmp_path / "artifacts"

    result = runner.invoke(
        cli,
        ["migrate", "crawl", SOURCE_URL, "--output-dir", str(output)],
    )

    assert result.exit_code == 0, result.output

    inventory_path = output / "site-inventory.json"
    assert inventory_path.exists()
    inventory = json.loads(inventory_path.read_text())
    assert inventory["source_url"] == SOURCE_URL
    assert len(inventory["pages"]) == 2
    home_entry = inventory["pages"][0]
    assert home_entry["slug"] == "home"
    assert any(s["type"] == "hero" for s in home_entry["sections"])

    hero_file = output / "pages" / "home" / "section-001-hero.json"
    assert hero_file.exists()
    hero = json.loads(hero_file.read_text())
    assert hero["type"] == "hero"
    assert hero["template"] == "Hero (Centered)"
    assert "Welcome to Source" in hero["content"]["headings"]
    assert hero["content"]["buttons"][0]["text"] == "Sign Up"

    manifest = json.loads((output / "assets" / "manifest.json").read_text())
    assert len(manifest) == 4
    assert all(entry["uploaded"] is False for entry in manifest)
    assert all(entry["vanjaro_url"] is None for entry in manifest)
    assert (output / "assets" / manifest[0]["local_file"]).exists()

    url_map = json.loads((output / "page-url-map.json").read_text())
    assert url_map[f"{SOURCE_URL}/"] == "/"
    assert url_map[f"{SOURCE_URL}/about"] == "/about"

    tokens = json.loads((output / "design-tokens.json").read_text())
    assert "#333333" in tokens["colors"]
    assert "Inter" in tokens["fonts"]

    header_file = output / "global" / "header.json"
    footer_file = output / "global" / "footer.json"
    assert header_file.exists()
    assert footer_file.exists()


@responses.activate
def test_migrate_crawl_skip_assets_downloads_nothing(runner, tmp_path: Path):
    _register_site(responses.mock, with_assets=False)
    output = tmp_path / "artifacts"

    result = runner.invoke(
        cli,
        [
            "migrate", "crawl", SOURCE_URL,
            "--output-dir", str(output),
            "--skip-assets",
        ],
    )

    assert result.exit_code == 0, result.output

    manifest = json.loads((output / "assets" / "manifest.json").read_text())
    assert manifest == []

    image_files = [p for p in (output / "assets").iterdir() if p.name != "manifest.json"]
    assert image_files == []


@responses.activate
def test_migrate_crawl_max_pages_limits_crawl(runner, tmp_path: Path):
    _register_site(responses.mock)
    output = tmp_path / "artifacts"

    result = runner.invoke(
        cli,
        [
            "migrate", "crawl", SOURCE_URL,
            "--output-dir", str(output),
            "--max-pages", "1",
        ],
    )

    assert result.exit_code == 0, result.output

    inventory = json.loads((output / "site-inventory.json").read_text())
    assert len(inventory["pages"]) == 1
    assert inventory["pages"][0]["slug"] == "home"
    assert not (output / "pages" / "about").exists()


@responses.activate
def test_migrate_crawl_json_output_shape(runner, tmp_path: Path):
    _register_site(responses.mock)
    output = tmp_path / "artifacts"

    result = runner.invoke(
        cli,
        [
            "migrate", "crawl", SOURCE_URL,
            "--output-dir", str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["pages_crawled"] == 2
    assert payload["assets_downloaded"] == 4
    assert payload["output_dir"] == str(output)
    assert isinstance(payload["warnings"], list)


def test_migrate_crawl_invalid_url(runner, tmp_path: Path):
    result = runner.invoke(
        cli,
        [
            "migrate", "crawl", "not-a-url",
            "--output-dir", str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert "Invalid URL" in result.output


GALLERY_HOMEPAGE_HTML = """<!doctype html>
<html>
<head><title>Portfolio Site</title></head>
<body>
  <main>
    <section class="hero">
      <h1>My Portfolio</h1>
      <p>Designer.</p>
    </section>
    <section class="gallery">
      <a href="/assets/shot-1.jpg"><img src="/assets/shot-1-thumb.jpg" alt="Shot 1"></a>
      <a href="/assets/shot-2.jpg"><img src="/assets/shot-2-thumb.jpg" alt="Shot 2"></a>
      <a href="/brochure.pdf">Download brochure</a>
      <a href="/archive.zip">Download archive</a>
      <a href="/about.html">About the designer</a>
    </section>
  </main>
</body>
</html>
"""

ABOUT_HTML_PAGE = """<!doctype html>
<html>
<head><title>About the designer</title></head>
<body><main><section><h1>About</h1><p>Bio.</p></section></main></body>
</html>
"""


@responses.activate
def test_migrate_crawl_skips_direct_asset_links(runner, tmp_path: Path):
    """Regression: `<a href="image.jpg">` must not be treated as a page.

    Found during end-to-end migration of a portfolio site whose gallery
    section wrapped each image in an `<a>` pointing directly at the full-size
    JPG. The crawler fetched each binary, failed to extract sections, and
    crowded out the real HTML pages under the --max-pages cap.
    """
    responses.add(responses.GET, f"{SOURCE_URL}/", body=GALLERY_HOMEPAGE_HTML, status=200)
    responses.add(responses.GET, f"{SOURCE_URL}/about.html", body=ABOUT_HTML_PAGE, status=200)
    responses.add(responses.GET, f"{SOURCE_URL}/sitemap.xml", status=404)
    # Thumbnails are downloaded as assets (via <img src>), not followed as pages.
    for thumb in ("/assets/shot-1-thumb.jpg", "/assets/shot-2-thumb.jpg"):
        responses.add(
            responses.GET,
            f"{SOURCE_URL}{thumb}",
            body=FAKE_IMAGE_BYTES,
            status=200,
            content_type="image/jpeg",
        )

    output = tmp_path / "artifacts"
    result = runner.invoke(
        cli,
        ["migrate", "crawl", SOURCE_URL, "--output-dir", str(output)],
    )

    assert result.exit_code == 0, result.output

    inventory = json.loads((output / "site-inventory.json").read_text())
    slugs = [page["slug"] for page in inventory["pages"]]

    # Only real HTML pages should show up — the gallery JPGs, PDF, and ZIP
    # must be filtered out of page discovery.
    assert slugs == ["home", "about-html"], f"unexpected pages: {slugs}"
    assert not any("shot-1" in slug or "shot-2" in slug for slug in slugs)
    assert not any("brochure" in slug for slug in slugs)
    assert not any("archive" in slug for slug in slugs)
