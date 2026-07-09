"""`vanjaro migrate audit-structure` — structural best-practice audit."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

import click
import requests

from vanjaro_cli.commands.helpers import exit_error, get_client, output_result
from vanjaro_cli.commands.pages_cmd import GET_PAGES, _walk_page_tree
from vanjaro_cli.config import ConfigError, load_config
from vanjaro_cli.migration.audit import audit_site
from vanjaro_cli.migration.crawler import DEFAULT_TIMEOUT, USER_AGENT

__all__ = ["audit_structure"]

# DNN ships these pages on every install. The `isspecial` API field covers
# Activity-Feed and Signin; Search Results and 404 Error Page have
# `isspecial: false` in the PersonaBar API, so they must be matched by tabpath.
_DNN_SYSTEM_TABPATHS: frozenset[str] = frozenset(
    {"/SearchResults", "/404ErrorPage"}
)


def _strip_alias_path(path: str, base_path: str) -> str:
    """Return ``path`` relative to the portal-alias path prefix.

    Child portals carry the alias in every page URL (``/keys-to-success/about``
    on base URL ``http://host/keys-to-success``); joining that onto the base
    URL would double the alias. Root-alias portals pass through unchanged.
    """
    clean = "/" + (path or "").strip("/")
    prefix = "/" + base_path.strip("/")
    if prefix == "/":
        return clean
    if clean == prefix:
        return "/"
    if clean.startswith(prefix + "/"):
        return clean[len(prefix):]
    return clean


def _is_system_page(page: dict, page_path: str) -> bool:
    """Return True when a page is a DNN system/admin page, not migrated content.

    ``page_path`` is the page's URL path relative to the portal alias.
    Detection uses two complementary signals from the PersonaBar GetPageList
    response:
    - ``isspecial: true`` — set by DNN on Activity-Feed, Signin, and similar
      framework pages. The portal home page is also ``isspecial`` but has
      ``parentId == -1`` and a bare ``/`` alias-relative path, so we leave it
      through; in practice the home page is always a content page worth
      auditing.
    - tabpath in ``_DNN_SYSTEM_TABPATHS`` — catches Search Results and 404
      Error Page, which DNN does not mark ``isspecial``.
    """
    if page.get("isspecial") and page_path not in ("", "/"):
        return True
    tabpath = page.get("tabpath") or ""
    return tabpath in _DNN_SYSTEM_TABPATHS


def _fetch_rendered_html(base_url: str, path: str) -> str:
    """Fetch a published Vanjaro page as anonymous HTML — no auth required."""
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def _discover_page_paths(
    base_url: str, as_json: bool, include_system: bool = False
) -> list[str]:
    """Return published page paths, relative to the portal alias in ``base_url``.

    DNN system pages (Activity-Feed, Signin, Search Results, 404 Error Page)
    are excluded by default; pass ``include_system=True`` to keep them.
    """
    try:
        client, _ = get_client()
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    try:
        response = client.get(GET_PAGES)
    except Exception as exc:
        exit_error(f"Failed to list pages: {exc}", as_json)

    base_path = urlparse(base_url).path
    raw_pages = _walk_page_tree(client, response.json())
    paths: list[str] = []
    for page in raw_pages:
        if not isinstance(page, dict):
            continue
        url = page.get("url") or page.get("tabpath") or ""
        if not url:
            continue
        page_path = _strip_alias_path(urlparse(url).path, base_path)
        if not include_system and _is_system_page(page, page_path):
            continue
        paths.append(page_path)
    return paths


def _print_report(report: dict, base_url: str) -> None:
    site_score = report.get("score", 0)
    click.echo(f"\nSite composite score: {site_score:.1f}/100")
    click.echo("")

    site_checks = report.get("site_checks", {})
    if site_checks:
        click.echo("Site-wide checks:")
        click.echo("-" * 60)
        for check_name, finding in site_checks.items():
            click.echo(f"  {check_name:<22} {finding['score']:>3}/100  {finding['summary']}")
            for detail in finding.get("details", []):
                click.echo(f"    - {detail}")
        click.echo("")

    pages = report.get("pages", [])
    if not pages:
        return

    click.echo(f"Per-page results ({len(pages)} page(s)):")
    click.echo("-" * 60)

    checks_order = ["inline-styles", "theme-classes", "responsive-images", "composition"]
    header = f"  {'URL':<35} {'Score':>5}  " + "  ".join(f"{c:<18}" for c in checks_order)
    click.echo(header)
    click.echo("-" * len(header))

    for page_audit in pages:
        url = page_audit.get("url", "")
        display_url = url.replace(base_url, "")[:34] or "/"
        page_score = page_audit.get("score", 0)
        checks = page_audit.get("checks", {})
        check_cols = "  ".join(
            f"{checks.get(c, {}).get('score', 0):>3}/100          "[:18]
            for c in checks_order
        )
        click.echo(f"  {display_url:<35} {page_score:>5.1f}  {check_cols}")

    click.echo("")
    click.echo("Findings (worst offenders):")
    click.echo("-" * 60)
    for page_audit in pages:
        url = page_audit.get("url", "")
        display_url = url.replace(base_url, "") or "/"
        for check_name in checks_order:
            finding = page_audit.get("checks", {}).get(check_name, {})
            for detail in finding.get("details", []):
                if not detail.startswith("Raw <section>"):
                    click.echo(f"  [{display_url}] {check_name}: {detail}")


@click.command("audit-structure")
@click.option(
    "--page",
    "page_paths",
    multiple=True,
    metavar="PATH",
    help="Page slug or path to audit (repeatable). Omit to use --all.",
)
@click.option(
    "--all",
    "audit_all",
    is_flag=True,
    help="Discover and audit all published pages via the API.",
)
@click.option(
    "--include-system",
    "include_system",
    is_flag=True,
    help="Include DNN system pages (Activity-Feed, Signin, Search Results, 404) in --all discovery.",
)
@click.option(
    "--json",
    "output_json_path",
    default=None,
    type=click.Path(),
    help="Write machine-readable JSON report to this path.",
)
@click.option("--as-json", "as_json", is_flag=True, help="Print JSON report to stdout.")
def audit_structure(
    page_paths: tuple[str, ...],
    audit_all: bool,
    include_system: bool,
    output_json_path: str | None,
    as_json: bool,
) -> None:
    """Audit the structural quality of migrated Vanjaro pages.

    Checks inline-style hygiene, global-block usage, theme-class coverage,
    responsive-image wrapping, and DOM composition — scored 0-100 per check
    with a composite site score.
    """
    if not page_paths and not audit_all:
        exit_error("Provide at least one --page PATH or use --all.", as_json)

    try:
        config = load_config()
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    base_url = config.base_url

    paths: list[str] = []
    if audit_all:
        paths = _discover_page_paths(base_url, as_json, include_system=include_system)
        if not paths:
            exit_error("No published pages found via API.", as_json)
    else:
        for path in page_paths:
            parsed = urlparse(path)
            paths.append(parsed.path if parsed.scheme else path)

    pages: list[tuple[str, str]] = []
    fetch_errors: list[str] = []

    for path in paths:
        full_url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        try:
            html = _fetch_rendered_html(base_url, path)
            pages.append((full_url, html))
        except requests.HTTPError as exc:
            fetch_errors.append(f"{full_url}: HTTP {exc.response.status_code}")
        except requests.RequestException as exc:
            fetch_errors.append(f"{full_url}: {exc}")

    if not pages:
        exit_error(
            "No pages could be fetched. Errors: " + "; ".join(fetch_errors),
            as_json,
        )

    report = audit_site(pages)

    if fetch_errors:
        report["fetch_errors"] = fetch_errors

    if output_json_path:
        Path(output_json_path).write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        if not as_json:
            click.echo(f"JSON report written to {output_json_path}")

    if as_json:
        click.echo(json.dumps(report, indent=2))
        return

    _print_report(report, base_url)

    if fetch_errors:
        click.echo("Fetch errors:")
        for error in fetch_errors:
            click.echo(f"  - {error}", err=True)
