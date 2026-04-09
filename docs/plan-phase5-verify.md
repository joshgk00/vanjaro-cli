# Phase 5: Migration Verification

Implementation plan for `vanjaro migrate verify` and `vanjaro migrate verify-all`.

Parent plan: `plan-site-migration.md` — this document expands Phase 5 into a buildable spec.

## Goal

After a site migration completes, give the agent (and any human reviewer) an automated way to compare the migrated Vanjaro pages against the source crawl artifacts and surface anything that didn't make it across: missing text, unreferenced or unuploaded images, unrewritten links, structural drift, and metadata mismatches.

Verify is the last line of defense before a migration is declared done.

## Decisions from spec interview

| Decision | Answer |
|---|---|
| Source-to-Vanjaro page ID mapping | New `--page-id-map` JSON file (`{source_url: vanjaro_page_id}`). Caller generates from `pages list`. |
| Text comparison unit | Per-heading + per-paragraph **set match** with fuzzy scoring. Reordering is OK; missing blocks are named in the report. |
| Migrated content fetch | `content get` (GrapesJS tree) walked for text/images/links. No HTTP fetch of rendered HTML. |
| Source fetch strategy | Read from crawl artifacts (`pages/{slug}/section-*.json`). No live re-crawl at verify time. |
| Metadata source (Vanjaro side) | `pages get` for title + description. |
| Header/footer comparison | `global-blocks get <name>` compared against `global/header.json` / `global/footer.json`. Takes `--header-block-name` / `--footer-block-name` flags. |
| Text normalization | Whitespace collapse + HTML entity decode. Case- and punctuation-sensitive. |
| Threshold model | Single `--threshold` (default 0.9) gates text_match only. Everything else is rule-based with tiered severity. |
| Exit code | `verify` exits 1 on hard-gap failures or below-threshold text match. `verify-all` continues through every page, exits 1 at end if any page failed. |
| Image gap severity | Hard (fail): unuploaded source asset, source URL in migrated tree, source image unreferenced. Soft (warn): extra image added by agent. |
| Report output | stdout (human or `--json`), opt-in `--output FILE` for persisted JSON. |

## Architecture

```
vanjaro_cli/
  migration/
    verify.py              — pure comparator logic + gap report models
    content_walk.py        — walks a GrapesJS JSON tree; collects text, images, links
    text_match.py          — normalization + set-match scoring (stdlib only)
  commands/
    migrate_verify_cmd.py  — Click commands: verify, verify-all
tests/
  test_migrate_verify_cmd.py
  test_verify.py           — pure comparator tests
  test_content_walk.py     — tree extractor tests
```

**Why three modules, not one**: `content_walk.py` mirrors `migration/sections.py` on the opposite side of the migration (HTML vs. GrapesJS JSON) and will be reused if verify grows. `text_match.py` is stdlib-only scoring logic that's easy to unit-test in isolation. `verify.py` orchestrates the comparators and owns the gap report shape. Keeping them apart means tests don't have to set up Vanjaro clients to exercise scoring.

**Why not reuse `url_rewrite._walk`**: it mutates attributes; verify collects them. The traversal shape is superficially similar but the per-node action is different, and unifying would need a visitor pattern that costs more than the 20 lines of duplication.

## Data contracts

### Inputs

**`verify` (single page)**
```bash
vanjaro migrate verify \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --source-url https://example.com/about \
  --page-id 36 \
  [--page-id-map artifacts/migration/example-com/page-id-map.json] \
  [--header-block-name "Site Header"] \
  [--footer-block-name "Site Footer"] \
  [--threshold 0.9] \
  [--output report.json] \
  [--json]
```

- `--inventory` + `--source-url` locates the crawl artifacts for this source page.
- `--page-id` identifies the Vanjaro page to fetch.
- `--page-id-map` is required only for link validation (resolving internal links). Omitted → link resolution falls back to "any non-source-URL is fine."

**`verify-all` (batch)**
```bash
vanjaro migrate verify-all \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --page-id-map artifacts/migration/example-com/page-id-map.json \
  [--header-block-name ...] [--footer-block-name ...] \
  [--threshold 0.9] \
  [--output report.json] \
  [--json]
```

For `verify-all`, `--page-id-map` is required (can't iterate without it). Pages in the inventory with no entry in the map are **skipped with a warning** and the command continues.

### Page ID map format

```json
{
  "https://example.com/": 35,
  "https://example.com/about": 36,
  "https://example.com/services": 37
}
```

Keys match `site-inventory.json` → `pages[].url` exactly. Values are Vanjaro page IDs. The caller is expected to build this from `pages list --json` output; verify doesn't generate it.

### Gap report shape

```json
{
  "source_url": "https://example.com/about",
  "page_id": 36,
  "status": "failed",
  "text": {
    "score": 0.87,
    "threshold": 0.9,
    "passed": false,
    "matched_headings": 3,
    "missing_headings": ["Our Team"],
    "matched_paragraphs": 8,
    "missing_paragraphs": ["Founded in 1998, we..."]
  },
  "images": {
    "hard_gaps": [
      {"type": "not_uploaded", "src": "https://example.com/team.jpg"},
      {"type": "not_referenced", "src": "https://example.com/hero.jpg"},
      {"type": "source_url_in_migrated", "src": "https://example.com/logo.png"}
    ],
    "soft_gaps": [
      {"type": "extra_in_migrated", "src": "/Portals/0/Images/placeholder.jpg"}
    ]
  },
  "links": {
    "hard_gaps": [
      {"type": "source_url_in_migrated", "href": "https://example.com/blog"},
      {"type": "broken_internal", "href": "/unknown-page"}
    ]
  },
  "structure": {
    "source_sections": 5,
    "migrated_sections": 4,
    "within_tolerance": false
  },
  "metadata": {
    "title_match": true,
    "description_match": false,
    "source_description": "Learn about our team",
    "migrated_description": ""
  },
  "header": {"status": "match"},
  "footer": {"status": "mismatch", "missing_links": ["Careers"]}
}
```

- `status`: `"passed"` | `"failed"` | `"skipped"` (no entry in page-id-map).
- Hard gaps flip `status` to `"failed"`; soft gaps never do.
- Below-threshold text score flips `status` to `"failed"`.
- `structure.within_tolerance`: `True` if `|source - migrated| <= 1` (tolerate small agent merges).

`verify-all` wraps per-page reports in:
```json
{
  "inventory": "artifacts/migration/example-com/site-inventory.json",
  "pages": {
    "passed": 4,
    "failed": 2,
    "skipped": 1
  },
  "reports": [ { ...single page... }, ... ]
}
```

## Module-by-module specification

### `migration/content_walk.py`

Mirror of `sections.py` for the migrated side. Walks a GrapesJS tree, collects flat lists of text/images/links the same way the crawler collects them from HTML.

```python
from dataclasses import dataclass, field

@dataclass
class WalkedContent:
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)  # src values
    links: list[str] = field(default_factory=list)   # href values
    section_count: int = 0

def walk_grapesjs_tree(components: list[dict]) -> WalkedContent: ...
```

Detection rules (mirroring url_rewrite and crawler conventions):
- **Heading**: `type == "heading"` or `tagName in {"h1","h2","h3","h4","h5","h6"}`. Text from `content` field.
- **Paragraph**: `type == "text"` or `tagName == "p"`. Text from `content`.
- **Image**: `type == "image"`. src from `attributes.src`.
- **Link**: `type in {"link","button"}` or `tagName == "a"`. href from `attributes.href`. Skip anchors (`#...`) and non-http schemes.
- **Section**: `type == "section"` — increment `section_count`. Only count top-level sections (don't recurse into a section to count nested ones).

Recurses through `components` arrays. No mutation.

### `migration/text_match.py`

```python
def normalize_text(raw: str) -> str:
    """Collapse whitespace, decode HTML entities, trim. Preserve case and punctuation."""

def fuzzy_set_match(
    source_items: list[str],
    migrated_items: list[str],
    min_ratio: float = 0.85,
) -> tuple[list[str], list[str]]:
    """Return (matched_source_items, missing_source_items).

    For each source item, find the best migrated item via
    difflib.SequenceMatcher.ratio() >= min_ratio. Greedy, not optimal —
    each migrated item can match at most one source item.
    """

def score_text_match(
    source_headings: list[str],
    source_paragraphs: list[str],
    migrated_headings: list[str],
    migrated_paragraphs: list[str],
) -> TextMatchResult:
    """Runs fuzzy_set_match on headings and paragraphs separately,
    produces combined score = (headings_matched + paragraphs_matched) /
    (total_source_headings + total_source_paragraphs)."""
```

`min_ratio = 0.85` is the per-item fuzzy threshold (used to decide "is this paragraph the same one, reordered"); it's separate from the page-level `--threshold` that gates overall pass/fail.

### `migration/verify.py`

Top-level orchestrator. Takes loaded inputs, returns a `PageReport` dataclass. Pure — does no I/O or Vanjaro client calls.

```python
@dataclass
class PageReport:
    source_url: str
    page_id: int | None
    status: Literal["passed", "failed", "skipped"]
    text: TextMatchResult
    images: ImageReport
    links: LinkReport
    structure: StructureReport
    metadata: MetadataReport
    header: GlobalBlockReport | None
    footer: GlobalBlockReport | None

    def as_dict(self) -> dict: ...

def verify_page(
    source_sections: list[dict],              # loaded from pages/{slug}/section-*.json
    migrated_components: list[dict],          # from `content get`
    asset_manifest: list[dict],
    source_page: dict,                         # slug, title, meta from inventory
    migrated_page: dict,                       # title, description from `pages get`
    page_id_map: dict[str, str] | None,
    text_threshold: float,
) -> PageReport: ...

def verify_global_block(
    source_global: dict,                       # from global/header.json or footer.json
    migrated_global_components: list[dict],    # from `global-blocks get`
) -> GlobalBlockReport: ...
```

Each comparator is a small function:
- `_compare_text` → calls `text_match.score_text_match`, applies threshold.
- `_compare_images` → walks source (from asset_manifest + source section images) and migrated (from `WalkedContent.images`), categorizes into the four gap types, tiers them hard/soft.
- `_compare_links` → checks every href in `WalkedContent.links` against the page_id_map; flags source-URL leakage and broken internal refs.
- `_compare_structure` → counts sections on each side, `within_tolerance = abs(diff) <= 1`.
- `_compare_metadata` → normalized string comparison on title + description.

### `commands/migrate_verify_cmd.py`

Two Click commands: `verify` and `verify_all`. Both:

1. Load inputs (inventory, crawl section files, asset manifest, page-id-map).
2. Fetch migrated data via the Vanjaro client:
   - `content get <page_id>` for the GrapesJS tree
   - `pages get <page_id>` for title/description (separate API call)
   - `global-blocks get <name>` for header/footer if the flags are set
3. Call `verify.verify_page` and `verify.verify_global_block`.
4. Serialize the report, print to stdout, optionally write to `--output`.
5. Exit 0 if passed, 1 if any hard gap or below-threshold text match.

**HTTP calls are wrapped in `try/except ApiError`** — a network failure during verify is a hard error that bubbles out via `exit_error`, not a per-check soft gap.

`verify-all` iterates `inventory["pages"]`, calls `verify_page` for each, aggregates results, applies skip-with-warning for pages absent from the page-id-map.

### `commands/migrate_cmd.py` (modified)

```python
from vanjaro_cli.commands.migrate_verify_cmd import verify, verify_all
...
migrate.add_command(verify)
migrate.add_command(verify_all)
```

## Error handling

| Condition | Behavior |
|---|---|
| Inventory file missing | `exit_error` with path |
| Source sections directory missing for a page | Hard fail — verify can't run without a source to compare against |
| Migrated page `content get` returns empty/null | Hard fail, reported as "no migrated content" |
| Migrated page `pages get` returns 404 | Hard fail, reported as "page_id not found" |
| ApiError during any fetch | Hard fail, propagate the API error message |
| `--page-id-map` missing entry (`verify-all`) | Skip with warning; `status: "skipped"` in report; doesn't fail the batch |
| `--header-block-name` specified but global block not found | Hard fail (user asked for the check, can't silently drop) |
| Source image not in asset manifest at all | Hard gap: `"type": "not_in_manifest"` (edge case — treat same as `not_uploaded`) |
| Empty headings/paragraphs on both sides | `text.score = 1.0` (trivially passes), no missing items |

## Test plan

Three test files, mirroring the module structure.

### `test_content_walk.py`
- Extract headings from `type: heading` and `tagName: h1..h6` variants
- Extract paragraphs from `type: text` and `tagName: p`
- Extract image src values (with and without `src`, skipping empty)
- Extract link href values (skipping anchors and `mailto:`)
- Count top-level sections, not nested ones
- Empty tree → empty `WalkedContent`
- Deeply nested tree doesn't hit recursion limit

### `test_verify.py` (pure logic)
- `normalize_text`: collapses whitespace, decodes entities, preserves case/punctuation
- `fuzzy_set_match`: exact matches, fuzzy matches above threshold, misses below threshold, greedy one-to-one pairing
- `score_text_match`: combined headings + paragraphs score, empty both sides
- `_compare_images`: each of the 4 gap types in isolation, tiered severity
- `_compare_links`: source URL leakage flagged, broken internal ref flagged, external/anchor left alone
- `_compare_structure`: within-tolerance and outside-tolerance cases
- `_compare_metadata`: title and description match/mismatch
- `verify_page` integration: a fully clean page (all passing), a page with a text gap, a page with an image hard gap, a page with everything failing
- `verify_global_block`: matching and mismatching global blocks

### `test_migrate_verify_cmd.py` (CLI)
- Uses `responses` to mock the Vanjaro client endpoints (`content get`, `pages get`, `global-blocks get`)
- Uses `tmp_path` for inventory + section files + manifest + page-id-map
- `verify` happy path: exit 0, correct JSON shape
- `verify` with text gap: exit 1, gap report includes missing heading
- `verify` with hard image gap: exit 1
- `verify` with `--output`: writes JSON to file
- `verify-all` all passing: exit 0, summary shows N passed
- `verify-all` one failing: exit 1, summary shows N passed + 1 failed, all reports present
- `verify-all` with missing page-id-map entry: warning + skipped status, doesn't fail batch
- Missing `--inventory` file: clean error
- `content get` returns 404: hard fail with clear message
- Header/footer block not found when requested: hard fail
- `--threshold` override accepted

Test helpers at top of file: `_make_source_section(slug, headings, paragraphs)`, `_make_migrated_tree(headings, paragraphs)`, `_make_manifest_entry(src, vanjaro_url)`, `_make_page_id_map(...)`.

## Build order

Three independent layers plus one integration layer. No serial dependencies within a layer.

1. **Layer 1 — pure logic (no Click, no client)**
   - `migration/content_walk.py` + `test_content_walk.py`
   - `migration/text_match.py` (fold into verify.py if small; separate is cleaner for tests)
   - `migration/verify.py` (comparators + report dataclasses) + `test_verify.py`

2. **Layer 2 — CLI command**
   - `commands/migrate_verify_cmd.py` — reads files, calls the client, invokes layer-1 functions
   - `test_migrate_verify_cmd.py` — uses `responses` + `tmp_path`
   - Register with migrate group in `commands/migrate_cmd.py`

3. **Layer 3 — verification** (per project workflow)
   - Run full pytest suite
   - `/simplify` pass over the diff
   - Re-run tests
   - `/commit` + push

## Acceptance criteria

1. `vanjaro migrate verify --inventory X --source-url Y --page-id N` runs against a crawled site and produces a gap report in either human or JSON format.
2. Exit code is 0 when text score >= threshold AND no hard gaps exist.
3. Exit code is 1 for any hard gap or below-threshold text score.
4. `verify-all` iterates every page in the inventory, skips pages missing from the `--page-id-map` with a warning, and reports a summary.
5. Text comparison tolerates section reordering (set-based match).
6. Image check catches unuploaded assets, unreferenced assets, and source-URL leakage as hard failures; extra images as soft warnings.
7. Link check flags any remaining source-site URLs in the migrated tree.
8. Metadata check compares title and description.
9. Header/footer check runs when `--header-block-name` / `--footer-block-name` are provided and compares against named global blocks.
10. Full test suite passes (target: +25 tests for Phase 5, suite around 430).

## Out of scope for Phase 5

- Re-crawling the source site at verify time (use artifacts only)
- Visual/CSS/styling comparison (belongs in site-builder visual-qa skill)
- Per-check thresholds (single `--threshold` only)
- Fail-fast in batch mode (always run all pages)
- Auto-generating the `--page-id-map` (caller builds from `pages list`)
- Modifying the Phase 1 crawl artifact shape
- Cross-page link checks (e.g., "page A links to page B, does page B exist" is covered; "is page A reachable from the nav" is not)
- Performance/load testing (this is a CLI tool, run locally)

## New dependencies

None. All comparators use stdlib (`difflib`, `html`, `re`, `urllib.parse`). BeautifulSoup is already a dependency for Phase 1 and is not needed here since verify reads the crawler's extracted JSON, not HTML.
