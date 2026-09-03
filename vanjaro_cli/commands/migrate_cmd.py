"""vanjaro migrate commands for crawling source sites and producing migration artifacts."""

from __future__ import annotations

import json
from contextlib import ExitStack
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
from vanjaro_cli.commands.migrate_dedup_cmd import dedup_sections
from vanjaro_cli.commands.migrate_rewrite_cmd import rewrite_urls
from vanjaro_cli.commands.migrate_audit_cmd import audit_structure
from vanjaro_cli.commands.migrate_gap_report_cmd import gap_report
from vanjaro_cli.commands.migrate_verify_cmd import verify, verify_all
from vanjaro_cli.commands.migrate_visual_cmd import visual_capture
from vanjaro_cli.commands.migrate_analyze_cmd import analyze
from vanjaro_cli.commands.migrate_benchmark_all_cmd import benchmark_all
from vanjaro_cli.commands.migrate_benchmark_cmd import benchmark
from vanjaro_cli.design.html_adapter import HtmlAdapterError, convert_legacy_crawl
from vanjaro_cli.design.serialization import write_design_document
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
from vanjaro_cli.migration.tokens import extract_design_tokens, fetch_stylesheets

__all__ = ["migrate"]


@click.group()
def migrate() -> None:
    """Migrate a live site into Vanjaro."""


migrate.add_command(assemble_page)
migrate.add_command(audit_structure)
migrate.add_command(build_global)
migrate.add_command(gap_report)
migrate.add_command(build_id_map)
migrate.add_command(create_pages)
migrate.add_command(dedup_sections)
migrate.add_command(rewrite_urls)
migrate.add_command(verify)
migrate.add_command(verify_all)
migrate.add_command(visual_capture)
migrate.add_command(analyze)
migrate.add_command(benchmark)
migrate.add_command(benchmark_all)


def _write_json(path: Path, data: object) -> None:
    """Write `data` as pretty-printed UTF-8 JSON."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _looks_shell_mangled(pattern: str) -> bool:
    """Return True if a path filter may have been rewritten by Git Bash.

    MSYS path conversion turns a leading-slash glob like '/services/*' into
    an absolute Windows path such as 'C:/Program Files/Git/services/*'.
    """
    has_drive_letter = len(pattern) >= 2 and pattern[0].isalpha() and pattern[1] == ":"
    return (
        pattern.startswith("/")
        or has_drive_letter
        or "program files/git" in pattern.lower()
    )


def _zero_pages_message(url: str, filters: tuple[str, ...]) -> str:
    """Build the error message for a crawl that discovered no pages."""
    message = (
        f"0 pages discovered at {url}. Check your --include-paths/--exclude-paths "
        "filters — no crawled URL path matched them."
    )
    if any(_looks_shell_mangled(pattern) for pattern in filters):
        message += (
            " Git Bash rewrites leading-slash arguments into Windows paths "
            "(MSYS path conversion) — set MSYS_NO_PATHCONV=1 or run the "
            "command from PowerShell."
        )
    return message


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
@click.option(
    "--legacy-only",
    is_flag=True,
    help="Write only established crawl artifacts; skip design-document.json.",
)
@click.option(
    "--rendered",
    is_flag=True,
    help=(
        "Fetch pages with a real browser (Playwright): captures JS-rendered "
        "sections (sliders, carousels) and computed section backgrounds that "
        "static fetching misses. Requires the [visual] extra."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def crawl(
    url: str,
    output_dir: str,
    max_pages: int,
    include_paths: tuple[str, ...],
    exclude_paths: tuple[str, ...],
    skip_assets: bool,
    legacy_only: bool,
    rendered: bool,
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

    # Stand the browser up before discovery: WAF-protected sites reset the
    # plain HTTP client, so rendered crawls must discover links through the
    # browser too, not just render content pages.
    rendered_stack = ExitStack()
    browser_page = None
    render_page_html = None
    if rendered:
        from vanjaro_cli.migration.visual import (
            VisualCaptureError,
            render_page_html as _render_page_html,
            rendered_page_session,
        )

        render_page_html = _render_page_html
        try:
            browser_page = rendered_stack.enter_context(rendered_page_session())
        except VisualCaptureError as exc:
            exit_error(str(exc), as_json)

    discovery_fetch = (
        (lambda target: render_page_html(browser_page, target))
        if browser_page is not None
        else None
    )

    try:
        page_urls, homepage_html = discover_pages(
            url, max_pages, include_paths, exclude_paths,
            on_warning=_warn, fetch=discovery_fetch,
        )
    except CrawlError as exc:
        rendered_stack.close()
        exit_error(str(exc), as_json)

    if not page_urls:
        rendered_stack.close()
        exit_error(_zero_pages_message(url, include_paths + exclude_paths), as_json)

    pages_summary: list[dict] = []
    url_map: dict[str, str] = {}
    all_image_urls: list[str] = []
    seen_images: set[str] = set()

    # Pages on a site share stylesheets — fetch once from the homepage and
    # reuse for section background/color resolution on every page.
    site_css = fetch_stylesheets(homepage_html, page_urls[0], _warn)

    pages_root = destination / "pages"
    pages_root.mkdir(exist_ok=True)

    for page_url in page_urls:
        try:
            if page_url == page_urls[0]:
                html = homepage_html  # already fetched/rendered during discovery
            elif browser_page is not None:
                html = render_page_html(browser_page, page_url)
            else:
                html = fetch_url_text(page_url)
        except CrawlError as exc:
            _warn(str(exc))
            continue
        except Exception as exc:  # noqa: BLE001 — playwright raises many navigation error types
            _warn(f"Rendered fetch failed for {page_url}: {exc}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = extract_page_title(soup)
        page_path = urlparse(page_url).path or "/"
        slug = slugify_path(page_path)

        sections = extract_sections(html, page_url, css_text=site_css)
        page_dir = pages_root / slug
        page_dir.mkdir(exist_ok=True)

        # Remove sections from previous crawls — extraction changes shift the
        # numbering/types, and downstream assemble globs section-*.json, so a
        # stale file would silently merge old content into the new page.
        for stale in page_dir.glob("section-*.json"):
            stale.unlink()

        section_entries: list[dict] = []
        for index, section in enumerate(sections, start=1):
            file_name = f"section-{index:03d}-{section['type']}.json"
            _write_json(page_dir / file_name, section)
            section_entries.append({
                "file": f"pages/{slug}/{file_name}",
                "type": section["type"],
                "template": section["template"],
            })
        if not section_entries:
            # A page with zero extracted sections means the extractor could
            # not read this site's markup — a silent `status: ok` here sends
            # the migration into Stages 2+ building a site out of nothing.
            _warn(
                f"page '{slug}' yielded 0 sections — extraction failed for "
                f"{page_url}; the site's markup may be unsupported"
            )

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

    rendered_stack.close()

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

    if not global_manifest:
        _warn("no global header or footer extracted from the homepage")

    tokens = extract_design_tokens(homepage_html, url, on_warning=_warn)
    _write_json(destination / "design-tokens.json", tokens)

    assets_dir = destination / "assets"
    assets_dir.mkdir(exist_ok=True)
    if skip_assets:
        asset_manifest: list[dict] = []
    else:
        # Clear files from previous crawls — collision-suffixed duplicates
        # accumulate across runs and `assets upload-dir` scans the directory,
        # so strays balloon the manifest and the upload batch. Upload state
        # survives via the manifest merge keyed on source_url.
        for stale in assets_dir.iterdir():
            if stale.is_file() and stale.name != "manifest.json":
                stale.unlink()
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

    design_document_path = destination / "design-document.json"
    design_document_written = False
    if not legacy_only:
        try:
            design_document = convert_legacy_crawl(destination)
            write_design_document(design_document_path, design_document)
            design_document_written = True
        except (HtmlAdapterError, OSError, ValueError) as exc:
            _warn(
                "Design Document generation failed after legacy crawl artifacts "
                f"were written: {exc}. Run `vanjaro migrate analyze "
                f"{destination}` after correcting the artifact."
            )

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
        design_document=(str(design_document_path) if design_document_written else None),
        warnings=warnings,
    )
