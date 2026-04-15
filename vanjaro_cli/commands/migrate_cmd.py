"""vanjaro migrate commands for crawling source sites and producing migration artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import click
from bs4 import BeautifulSoup

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.commands.migrate_assemble_cmd import assemble_page
from vanjaro_cli.commands.migrate_build_global_cmd import build_global
from vanjaro_cli.commands.migrate_build_id_map_cmd import build_id_map
from vanjaro_cli.commands.migrate_create_pages_cmd import create_pages
from vanjaro_cli.commands.migrate_rewrite_cmd import rewrite_urls
from vanjaro_cli.commands.migrate_verify_cmd import verify, verify_all
from vanjaro_cli.migration.assets import download_assets
from vanjaro_cli.migration.crawler import (
    CrawlError,
    discover_pages,
    fetch_url_text,
    infer_page_hierarchy,
    slugify_path,
)
from vanjaro_cli.migration.sections import (
    collect_image_urls,
    extract_global_element,
    extract_page_title,
    extract_sections,
)
from vanjaro_cli.migration.tokens import extract_design_tokens

__all__ = ["migrate"]


@click.group()
def migrate() -> None:
    """Migrate a live site into Vanjaro."""


migrate.add_command(assemble_page)
migrate.add_command(build_global)
migrate.add_command(build_id_map)
migrate.add_command(create_pages)
migrate.add_command(rewrite_urls)
migrate.add_command(verify)
migrate.add_command(verify_all)


def _write_json(path: Path, data: object) -> None:
    """Write `data` as pretty-printed UTF-8 JSON."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@migrate.command("crawl")
@click.argument("url")
@click.option(
    "--output-dir",
    type=click.Path(),
    required=True,
    help="Directory to write migration artifacts into.",
)
@click.option("--max-pages", type=int, default=50, help="Maximum number of pages to crawl.")
@click.option(
    "--include-paths",
    multiple=True,
    help="Glob pattern (repeatable) — only crawl matching paths.",
)
@click.option(
    "--exclude-paths",
    multiple=True,
    help="Glob pattern (repeatable) — skip matching paths.",
)
@click.option("--skip-assets", is_flag=True, help="Don't download images.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def crawl(
    url: str,
    output_dir: str,
    max_pages: int,
    include_paths: tuple[str, ...],
    exclude_paths: tuple[str, ...],
    skip_assets: bool,
    as_json: bool,
) -> None:
    """Crawl a site at URL and write migration artifacts to OUTPUT_DIR."""
    if max_pages < 1:
        exit_error("--max-pages must be at least 1.", as_json)

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        exit_error(f"Invalid URL: {url}", as_json)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    def _warn(message: str) -> None:
        warnings.append(message)
        if not as_json:
            click.echo(f"warning: {message}", err=True)

    try:
        page_urls, homepage_html = discover_pages(
            url, max_pages, include_paths, exclude_paths, on_warning=_warn
        )
    except CrawlError as exc:
        exit_error(str(exc), as_json)

    pages_summary: list[dict] = []
    url_map: dict[str, str] = {}
    all_image_urls: list[str] = []
    seen_images: set[str] = set()

    pages_root = destination / "pages"
    pages_root.mkdir(exist_ok=True)

    for page_url in page_urls:
        try:
            html = homepage_html if page_url == page_urls[0] else fetch_url_text(page_url)
        except CrawlError as exc:
            _warn(str(exc))
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = extract_page_title(soup)
        page_path = urlparse(page_url).path or "/"
        slug = slugify_path(page_path)

        sections = extract_sections(html, page_url)
        page_dir = pages_root / slug
        page_dir.mkdir(exist_ok=True)

        section_entries: list[dict] = []
        for index, section in enumerate(sections, start=1):
            file_name = f"section-{index:03d}-{section['type']}.json"
            _write_json(page_dir / file_name, section)
            section_entries.append({
                "file": f"pages/{slug}/{file_name}",
                "type": section["type"],
                "template": section["template"],
            })

        pages_summary.append({
            "url": page_url,
            "path": page_path,
            "title": title,
            "slug": slug,
            "sections": section_entries,
        })

        url_map[page_url] = "/" if slug == "home" else f"/{slug}"

        for image_url in collect_image_urls(sections):
            if image_url not in seen_images:
                seen_images.add(image_url)
                all_image_urls.append(image_url)

    infer_page_hierarchy(pages_summary)

    global_dir = destination / "global"
    global_dir.mkdir(exist_ok=True)
    global_manifest: dict[str, str] = {}
    for element_name in ("header", "footer"):
        global_section = extract_global_element(homepage_html, url, element_name)
        if global_section:
            _write_json(global_dir / f"{element_name}.json", global_section)
            global_manifest[element_name] = f"global/{element_name}.json"
            for image in global_section["content"].get("images", []):
                src = image.get("src")
                if src and src not in seen_images:
                    seen_images.add(src)
                    all_image_urls.append(src)

    tokens = extract_design_tokens(homepage_html, url, on_warning=_warn)
    _write_json(destination / "design-tokens.json", tokens)

    if skip_assets:
        (destination / "assets").mkdir(exist_ok=True)
        asset_manifest: list[dict] = []
    else:
        asset_manifest = download_assets(all_image_urls, destination, _warn)

    _write_json(destination / "assets" / "manifest.json", asset_manifest)

    inventory = {
        "source_url": url,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages_summary,
        "assets": {
            "count": len(asset_manifest),
            "manifest": "assets/manifest.json",
        },
        "global": global_manifest,
    }
    _write_json(destination / "site-inventory.json", inventory)
    _write_json(destination / "page-url-map.json", url_map)

    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Crawled {len(pages_summary)} page(s) from {url}. "
            f"Assets: {len(asset_manifest)}. Output: {destination}"
        ),
        output_dir=str(destination),
        pages_crawled=len(pages_summary),
        assets_downloaded=len(asset_manifest),
        warnings=warnings,
    )
