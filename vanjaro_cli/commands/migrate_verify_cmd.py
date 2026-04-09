"""vanjaro migrate verify / verify-all — compare migrated pages against crawl artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.commands.helpers import (
    exit_error,
    get_client,
    parse_json_field,
    read_json_array,
    read_json_file,
    read_json_object,
)
from vanjaro_cli.config import ConfigError
from vanjaro_cli.migration.text_match import TextMatchResult
from vanjaro_cli.migration.verify import (
    GlobalBlockReport,
    ImageReport,
    LinkReport,
    MetadataReport,
    PageReport,
    StructureReport,
    verify_global_block,
    verify_page,
)

__all__ = ["verify", "verify_all"]


_GET_CONTENT = "/API/VanjaroAI/AIPage/Get"
_GET_PAGE_DETAILS = "/API/PersonaBar/Pages/GetPageDetails"
_LIST_GLOBAL_BLOCKS = "/API/VanjaroAI/AIGlobalBlock/List"
_GET_GLOBAL_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Get"


@click.command("verify")
@click.option(
    "--inventory",
    "inventory_file",
    type=click.Path(),
    required=True,
    help="site-inventory.json from a completed crawl.",
)
@click.option("--source-url", required=True, help="Source URL of the page to verify.")
@click.option("--page-id", type=int, required=True, help="Vanjaro page ID to verify.")
@click.option(
    "--page-id-map",
    "page_id_map_file",
    type=click.Path(),
    default=None,
    help="JSON map {source_url: vanjaro_page_id}. Optional for single-page verify.",
)
@click.option(
    "--header-block-name",
    default=None,
    help="Global block name to compare against global/header.json.",
)
@click.option(
    "--footer-block-name",
    default=None,
    help="Global block name to compare against global/footer.json.",
)
@click.option(
    "--threshold",
    type=float,
    default=0.9,
    show_default=True,
    help="Minimum text match score (0.0-1.0).",
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(),
    default=None,
    help="Write the gap report as JSON to this file.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def verify(
    inventory_file: str,
    source_url: str,
    page_id: int,
    page_id_map_file: str | None,
    header_block_name: str | None,
    footer_block_name: str | None,
    threshold: float,
    output_file: str | None,
    as_json: bool,
) -> None:
    """Verify a single migrated page against its source crawl artifacts.

    Exits non-zero on any hard image/link gap or a text score below the
    threshold. Header/footer block comparison is informational only — a
    mismatch is reported but does not change the exit code.
    """
    inventory_path = Path(inventory_file)
    inventory, inventory_root = _load_inventory(inventory_path, as_json)

    source_page = _find_source_page(inventory, source_url)
    if source_page is None:
        exit_error(
            f"Source URL {source_url} not found in inventory {inventory_path}.",
            as_json,
        )

    asset_manifest = _load_asset_manifest(inventory, inventory_root, as_json)
    known_paths = _load_known_vanjaro_paths(inventory_root)
    source_sections = _load_source_sections(source_page, inventory_root, as_json)

    client, _ = get_client()
    migrated_components = _fetch_migrated_content(client, page_id, as_json)
    migrated_page = _fetch_page_details(client, page_id, as_json)

    report = verify_page(
        source_sections=source_sections,
        migrated_components=migrated_components,
        asset_manifest=asset_manifest,
        source_page=source_page,
        migrated_page=migrated_page,
        text_threshold=threshold,
        page_id=page_id,
        source_url=source_url,
        known_vanjaro_paths=known_paths,
    )

    _attach_global_block_reports(
        client,
        report,
        inventory_root,
        header_block_name,
        footer_block_name,
        as_json,
    )

    _emit_single_report(report, output_file, as_json)
    if report.status != "passed":
        raise click.exceptions.Exit(1)


@click.command("verify-all")
@click.option(
    "--inventory",
    "inventory_file",
    type=click.Path(),
    required=True,
    help="site-inventory.json from a completed crawl.",
)
@click.option(
    "--page-id-map",
    "page_id_map_file",
    type=click.Path(),
    required=True,
    help="JSON map {source_url: vanjaro_page_id}. Required for batch verification.",
)
@click.option("--header-block-name", default=None)
@click.option("--footer-block-name", default=None)
@click.option(
    "--threshold",
    type=float,
    default=0.9,
    show_default=True,
    help="Minimum text match score (0.0-1.0).",
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(),
    default=None,
    help="Write the aggregated report JSON to this file.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def verify_all(
    inventory_file: str,
    page_id_map_file: str,
    header_block_name: str | None,
    footer_block_name: str | None,
    threshold: float,
    output_file: str | None,
    as_json: bool,
) -> None:
    """Verify every migrated page listed in an inventory."""
    inventory_path = Path(inventory_file)
    inventory, inventory_root = _load_inventory(inventory_path, as_json)
    page_id_map = _load_page_id_map(Path(page_id_map_file), as_json)

    asset_manifest = _load_asset_manifest(inventory, inventory_root, as_json)
    known_paths = _load_known_vanjaro_paths(inventory_root)

    client, _ = get_client()

    # Global blocks are constant across the batch — fetch + compare once and
    # attach the same report to every page instead of hitting the API N times.
    shared_header = (
        _compare_named_global_block(
            client,
            header_block_name,
            inventory_root / "global" / "header.json",
            as_json,
        )
        if header_block_name
        else None
    )
    shared_footer = (
        _compare_named_global_block(
            client,
            footer_block_name,
            inventory_root / "global" / "footer.json",
            as_json,
        )
        if footer_block_name
        else None
    )

    reports: list[PageReport] = []
    passed = failed = skipped = 0

    for source_page in inventory.get("pages", []) or []:
        if not isinstance(source_page, dict):
            continue

        source_url = source_page.get("url", "")
        page_id = page_id_map.get(source_url)
        if page_id is None:
            if not as_json:
                click.echo(
                    f"warning: {source_url} has no entry in --page-id-map; skipping.",
                    err=True,
                )
            reports.append(_skipped_report(source_url))
            skipped += 1
            continue

        source_sections = _load_source_sections(source_page, inventory_root, as_json)
        migrated_components = _fetch_migrated_content(client, page_id, as_json)
        migrated_page = _fetch_page_details(client, page_id, as_json)

        report = verify_page(
            source_sections=source_sections,
            migrated_components=migrated_components,
            asset_manifest=asset_manifest,
            source_page=source_page,
            migrated_page=migrated_page,
            text_threshold=threshold,
            page_id=page_id,
            source_url=source_url,
            known_vanjaro_paths=known_paths,
        )
        report.header = shared_header
        report.footer = shared_footer

        if report.status == "passed":
            passed += 1
        else:
            failed += 1
        reports.append(report)

    summary = {
        "inventory": str(inventory_path),
        "pages": {"passed": passed, "failed": failed, "skipped": skipped},
        "reports": [report.as_dict() for report in reports],
    }

    _emit_batch_summary(summary, output_file, as_json)
    if failed:
        raise click.exceptions.Exit(1)


# ------------------------------------------------------------------
# Loading helpers
# ------------------------------------------------------------------


def _load_inventory(inventory_path: Path, as_json: bool) -> tuple[dict, Path]:
    data = read_json_object(inventory_path, "Inventory", as_json)
    return data, inventory_path.parent


def _find_source_page(inventory: dict, source_url: str) -> dict | None:
    for page in inventory.get("pages", []) or []:
        if isinstance(page, dict) and page.get("url") == source_url:
            return page
    return None


def _load_page_id_map(path: Path, as_json: bool) -> dict[str, int]:
    raw = read_json_object(path, "Page ID map", as_json)

    result: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            result[key] = int(value)
        except (TypeError, ValueError):
            exit_error(
                f"Page ID map {path} has a non-integer value for '{key}'.",
                as_json,
            )
    return result


def _load_asset_manifest(
    inventory: dict, inventory_root: Path, as_json: bool
) -> list[dict]:
    assets = inventory.get("assets") or {}
    if not isinstance(assets, dict):
        return []
    manifest_rel = assets.get("manifest")
    if not isinstance(manifest_rel, str) or not manifest_rel:
        return []
    manifest_path = inventory_root / manifest_rel
    return read_json_array(manifest_path, "Asset manifest", as_json)


def _load_known_vanjaro_paths(inventory_root: Path) -> set[str] | None:
    """Read ``page-url-map.json`` from the inventory directory if present.

    The crawler emits this file alongside ``site-inventory.json`` as a map
    from source URL to Vanjaro path. We use the set of paths to validate
    internal link targets during verify.
    """
    candidate = inventory_root / "page-url-map.json"
    if not candidate.exists():
        return None
    try:
        raw = json.loads(candidate.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None

    paths: set[str] = set()
    for value in raw.values():
        if isinstance(value, str) and value:
            trimmed = value.rstrip("/") or "/"
            paths.add(trimmed)
    return paths or None


def _load_source_sections(
    source_page: dict, inventory_root: Path, as_json: bool
) -> list[dict]:
    entries = source_page.get("sections") or []
    if not isinstance(entries, list):
        exit_error(
            f"Inventory page {source_page.get('url', '?')} has a non-list 'sections' entry.",
            as_json,
        )

    sections: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rel_path = entry.get("file")
        if not isinstance(rel_path, str) or not rel_path:
            continue
        section_path = inventory_root / rel_path
        sections.append(read_json_object(section_path, "Section file", as_json))

    if not sections:
        exit_error(
            f"No section files found for {source_page.get('url', '?')} — cannot verify without a source to compare.",
            as_json,
        )
    return sections


# ------------------------------------------------------------------
# Vanjaro fetch helpers
# ------------------------------------------------------------------


def _fetch_migrated_content(
    client: VanjaroClient, page_id: int, as_json: bool
) -> list[dict]:
    try:
        response = client.get(
            _GET_CONTENT,
            params={"pageId": page_id, "includeDraft": "true", "locale": "en-US"},
        )
    except (ApiError, ConfigError) as exc:
        exit_error(f"Cannot fetch content for page {page_id}: {exc}", as_json)

    data = response.json()
    if data is None:
        exit_error(f"No migrated content returned for page {page_id}.", as_json)

    components = parse_json_field(data, "contentJSON")
    if not isinstance(components, list):
        return []
    return components


def _fetch_page_details(
    client: VanjaroClient, page_id: int, as_json: bool
) -> dict:
    try:
        response = client.get(_GET_PAGE_DETAILS, params={"pageId": page_id})
    except ApiError as exc:
        if exc.status_code == 404:
            exit_error(f"Vanjaro page {page_id} not found.", as_json)
        else:
            exit_error(f"Cannot fetch page {page_id} details: {exc}", as_json)
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    if isinstance(data, dict) and isinstance(data.get("page"), dict):
        return data["page"]
    return data if isinstance(data, dict) else {}


def _fetch_global_block_content(
    client: VanjaroClient, name: str, as_json: bool
) -> list[dict]:
    try:
        list_response = client.get(_LIST_GLOBAL_BLOCKS)
    except (ApiError, ConfigError) as exc:
        exit_error(f"Cannot list global blocks: {exc}", as_json)

    blocks = list_response.json() or {}
    guid: str | None = None
    for block in blocks.get("blocks", []) or []:
        if isinstance(block, dict) and block.get("name") == name:
            guid = block.get("guid")
            break
    if not guid:
        exit_error(f"Global block '{name}' not found on the target site.", as_json)

    try:
        get_response = client.get(_GET_GLOBAL_BLOCK, params={"guid": guid})
    except (ApiError, ConfigError) as exc:
        exit_error(f"Cannot fetch global block '{name}': {exc}", as_json)

    detail = get_response.json() or {}
    components = parse_json_field(detail, "contentJSON")
    if not isinstance(components, list):
        return []
    return components


def _attach_global_block_reports(
    client: VanjaroClient,
    report: PageReport,
    inventory_root: Path,
    header_block_name: str | None,
    footer_block_name: str | None,
    as_json: bool,
) -> None:
    """Fetch + compare header/footer global blocks for single-page verify.

    Only used by the single-page ``verify`` command — ``verify-all`` fetches
    these blocks once before its page loop and shares the same reports
    across every page.
    """
    if header_block_name:
        report.header = _compare_named_global_block(
            client,
            header_block_name,
            inventory_root / "global" / "header.json",
            as_json,
        )
    if footer_block_name:
        report.footer = _compare_named_global_block(
            client,
            footer_block_name,
            inventory_root / "global" / "footer.json",
            as_json,
        )


def _compare_named_global_block(
    client: VanjaroClient,
    block_name: str,
    source_file: Path,
    as_json: bool,
) -> GlobalBlockReport:
    source_global = read_json_object(source_file, "Global block file", as_json)
    migrated_components = _fetch_global_block_content(client, block_name, as_json)
    return verify_global_block(source_global, migrated_components)


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------


def _skipped_report(source_url: str) -> PageReport:
    return PageReport(
        source_url=source_url,
        page_id=None,
        status="skipped",
        text=TextMatchResult(),
        images=ImageReport(),
        links=LinkReport(),
        structure=StructureReport(),
        metadata=MetadataReport(),
        notes=["No page_id mapping; skipped."],
    )


def _emit_single_report(
    report: PageReport, output_file: str | None, as_json: bool
) -> None:
    payload = report.as_dict()

    if output_file:
        _write_json(Path(output_file), payload, as_json)

    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    _print_human_page_report(report)


def _emit_batch_summary(
    summary: dict, output_file: str | None, as_json: bool
) -> None:
    if output_file:
        _write_json(Path(output_file), summary, as_json)

    if as_json:
        click.echo(json.dumps(summary, indent=2))
        return

    pages = summary["pages"]
    click.echo(
        f"Verified {pages['passed'] + pages['failed'] + pages['skipped']} page(s): "
        f"{pages['passed']} passed, {pages['failed']} failed, {pages['skipped']} skipped."
    )
    for entry in summary["reports"]:
        marker = {"passed": "ok", "failed": "FAIL", "skipped": "skip"}.get(
            entry["status"], "?"
        )
        click.echo(f"  [{marker}] {entry['source_url']}")


def _print_human_page_report(report: PageReport) -> None:
    click.echo(f"Page: {report.source_url}")
    click.echo(f"Status: {report.status}")
    click.echo(
        f"Text:  score={report.text.score:.3f} threshold={report.text.threshold} "
        f"(matched H={report.text.matched_headings} P={report.text.matched_paragraphs})"
    )
    if report.text.missing_headings:
        click.echo(f"  missing headings: {len(report.text.missing_headings)}")
    if report.text.missing_paragraphs:
        click.echo(f"  missing paragraphs: {len(report.text.missing_paragraphs)}")

    if report.images.hard_gaps:
        click.echo(f"Images (hard): {len(report.images.hard_gaps)}")
        for gap in report.images.hard_gaps:
            click.echo(f"  - {gap.type}: {gap.src}")
    if report.images.soft_gaps:
        click.echo(f"Images (soft): {len(report.images.soft_gaps)}")

    if report.links.hard_gaps:
        click.echo(f"Links (hard): {len(report.links.hard_gaps)}")
        for gap in report.links.hard_gaps:
            click.echo(f"  - {gap.type}: {gap.href}")

    click.echo(
        f"Structure: source={report.structure.source_sections} "
        f"migrated={report.structure.migrated_sections} "
        f"tolerance={'ok' if report.structure.within_tolerance else 'drift'}"
    )
    click.echo(
        f"Metadata: title={'ok' if report.metadata.title_match else 'mismatch'} "
        f"description={'ok' if report.metadata.description_match else 'mismatch'}"
    )
    if report.header is not None:
        click.echo(f"Header: {report.header.status}")
    if report.footer is not None:
        click.echo(f"Footer: {report.footer.status}")


def _write_json(path: Path, payload: object, as_json: bool) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {path}: {exc}", as_json)
