# Site Migration Tooling

## Goal

Enable an agent to take a live website URL, crawl it, extract everything needed, and rebuild it on Vanjaro CMS — with minimal manual intervention. The migration should preserve content, images, navigation structure, SEO metadata, and visual design.

## Current State

### What Exists

The block composition system (see `plan-reusable-block-system.md`) provides the foundation:

| Capability | CLI Commands | Skills |
|-----------|-------------|--------|
| Theme extraction & application | `theme set-bulk`, `theme register-font`, `theme css update` | `theme-extract-tokens`, `theme-apply` |
| Block template library | 15 templates across 6 categories | `block-template-author` |
| Block composition & registration | `blocks compose`, `blocks build-library`, `custom-blocks create` | `block-composer` |
| Page management | `pages create`, `content update`, `content publish` | `build-page` |
| Asset management | `assets upload`, `assets list` | — |
| End-to-end site building | All of the above | `site-builder` |
| Migration orchestration | — | `site-migrator` (skill only, no CLI tooling) |

### What's Missing

The `site-migrator` skill describes a 6-stage migration pipeline, but stages 1 and 5 have no CLI tooling. The agent has to do everything manually — fetching pages, parsing HTML, downloading images one by one, rewriting URLs by hand. This is slow, error-prone, and not repeatable.

| Gap | Impact | Phase |
|-----|--------|-------|
| No site crawler — no structured way to fetch pages and extract content | Blocks Stage 1 entirely | Phase 1 |
| No batch asset upload — `assets upload` is one file at a time | Slow for 20+ images | Phase 2 |
| No URL rewriting — no utility to replace source URLs with Vanjaro paths | Error-prone, easy to miss references | Phase 3 |
| No content assembly — no way to merge per-section JSONs into a page | Agent has to construct JSON manually | Phase 4 |
| No visual comparison — no automated way to compare source vs migrated | Verification is manual and slow | Phase 5 |

---

## Implementation Phases

### Phase 1: Site Crawler

**Goal**: A CLI command that fetches a source site and produces structured migration artifacts.

**New command**:
```bash
# Crawl a site, extract content and assets
vanjaro migrate crawl https://example.com \
  --output-dir artifacts/migration/example-com \
  --max-pages 20
```

**What it does**:

1. **Discover pages** — Fetch the homepage, extract navigation links, optionally read `/sitemap.xml`
2. **Extract page content** — For each page, parse the HTML and identify sections (hero, cards, CTA, etc.) with their text content, images, and links
3. **Extract global elements** — Identify header and footer content shared across pages
4. **Download assets** — Save all referenced images to `assets/` subdirectory
5. **Extract design tokens** — Analyze the site's CSS for colors, fonts, spacing
6. **Write inventory** — Produce `site-inventory.json` as the master manifest

**Output structure**:
```
artifacts/migration/example-com/
  site-inventory.json          — master manifest (pages, sections, assets)
  design-tokens.json           — extracted colors, fonts, spacing
  pages/
    home/
      section-1-hero.json      — per-section content
      section-2-cards.json
    about/
      section-1-hero.json
  global/
    header.json                — nav items, logo
    footer.json                — footer columns, links
  assets/
    manifest.json              — source URL → local file mapping
    hero-bg.jpg
    team-photo-1.jpg
```

**Technical approach**:
- Use `requests` (already a dependency) to fetch HTML pages
- Use `BeautifulSoup` for HTML parsing (new dependency — lightweight, stdlib-adjacent)
- Download images with `requests` to local files
- CSS parsing for design tokens: regex-based extraction from `<link>` stylesheets or inline `<style>` tags — no need for a full CSS parser

**Section detection strategy**:
- Identify `<section>`, `<div>` with landmark roles, or major structural elements
- Classify each by content pattern: hero (large heading + CTA in first section), cards (repeated grid items), testimonial (blockquotes), CTA (short section with button), footer (bottom landmark)
- Extract headings, paragraphs, images, buttons, and links from each section
- Map to the closest block template from the library

**Options**:
- `--max-pages N` — limit crawl depth (default: 50)
- `--include-paths GLOB` — only crawl pages matching pattern
- `--exclude-paths GLOB` — skip pages matching pattern
- `--skip-assets` — extract content only, don't download images
- `--json` — structured output for scripting

**Acceptance**: Running `migrate crawl <url>` produces a complete `site-inventory.json` with per-page section files, downloaded assets, and design tokens. Agent can use the output directly with existing skills.

### Phase 2: Batch Asset Upload

**Goal**: Upload an entire directory of assets to Vanjaro in one command, producing a manifest that maps source filenames to Vanjaro URLs.

**New command**:
```bash
# Upload all assets from the migration directory
vanjaro assets upload-dir artifacts/migration/example-com/assets/ \
  --folder "Images/Migration/" \
  --manifest artifacts/migration/example-com/assets/manifest.json
```

**What it does**:

1. **Scan directory** — find all image/media files
2. **Read existing manifest** — if `manifest.json` exists, skip already-uploaded files (resume support)
3. **Upload each file** — call `assets upload` for each, collect Vanjaro URLs
4. **Update manifest** — write `vanjaro_url` and `vanjaro_file_id` for each uploaded file

**Manifest format** (extends the crawl output):
```json
[
  {
    "source_url": "https://example.com/images/hero.jpg",
    "local_file": "hero.jpg",
    "filename": "hero.jpg",
    "size_bytes": 145320,
    "content_type": "image/jpeg",
    "vanjaro_url": "/Portals/0/Images/Migration/hero.jpg",
    "vanjaro_file_id": 42,
    "uploaded": true
  }
]
```

**Options**:
- `--folder PATH` — Vanjaro folder to upload into (default: `"Images/"`)
- `--manifest FILE` — path to manifest file (default: `{dir}/manifest.json`)
- `--dry-run` — list files that would be uploaded without uploading
- `--skip-existing` — skip files already in the manifest with `uploaded: true`
- `--json` — structured output

**Acceptance**: `assets upload-dir` uploads 20+ files, produces a manifest, and supports resuming from partial uploads.

### Phase 3: URL Rewriting Utility

**Goal**: A CLI command that walks a GrapesJS component tree and rewrites all image `src` and internal `href` attributes using the asset manifest and page URL map.

**New command**:
```bash
# Rewrite URLs in a content JSON file
vanjaro migrate rewrite-urls \
  --content page-content.json \
  --asset-manifest artifacts/migration/example-com/assets/manifest.json \
  --page-map artifacts/migration/example-com/page-url-map.json \
  --output page-content-rewritten.json
```

**What it does**:

1. **Load the component tree** from the content JSON file
2. **Walk all components** recursively
3. **Rewrite image sources** — for each `image` component, look up `attributes.src` in the asset manifest and replace with `vanjaro_url`
4. **Rewrite internal links** — for each `button` or `link` component, look up `attributes.href` in the page URL map and replace with the Vanjaro path
5. **Leave external links unchanged** — URLs not in the page map are kept as-is
6. **Leave anchors unchanged** — `#section-id` references are kept as-is
7. **Write the rewritten file**

**Page URL map format**:
```json
{
  "https://example.com/": "/",
  "https://example.com/about": "/about",
  "https://example.com/services": "/services",
  "/about": "/about",
  "/services": "/services"
}
```

The map includes both absolute and relative source URLs to handle both formats found in the wild.

**Options**:
- `--content FILE` — input content JSON file (required)
- `--asset-manifest FILE` — asset manifest with source → Vanjaro URL mapping (required)
- `--page-map FILE` — page URL map with source → Vanjaro path mapping (optional — skip link rewriting if not provided)
- `--output FILE` — output file (default: overwrite input)
- `--report` — print summary of rewrites (N images, N links, N unchanged)
- `--json` — structured output

**Acceptance**: Given a component tree with source URLs, produces a tree with all URLs pointing to Vanjaro paths. Zero source site references remain in the output.

### Phase 4: Content Assembly

**Goal**: A CLI command that takes multiple per-section JSON files and merges them into a single page content JSON suitable for `content update`.

**New command**:
```bash
# Assemble a page from section files
vanjaro migrate assemble-page \
  --sections artifacts/migration/example-com/pages/home/section-*.json \
  --output home-content.json

# Or specify sections explicitly in order
vanjaro migrate assemble-page \
  --sections hero.json cards.json testimonials.json cta.json \
  --output home-content.json
```

**What it does**:

1. **Read each section file** — each contains a single section's component tree (a template + overrides)
2. **Compose from templates** — for sections that reference a template name, run `blocks compose` with the specified overrides
3. **Concatenate** — combine all sections into a single `{"components": [...], "styles": []}` structure
4. **Validate** — check that each top-level component is a `section` type with required attributes
5. **Write output** — ready for `content update PAGE_ID --file output.json`

**Section file format** (two modes):

Mode A — raw component tree (already composed):
```json
{
  "type": "section",
  "classes": [...],
  "attributes": {"id": "..."},
  "components": [...]
}
```

Mode B — template reference (compose on the fly):
```json
{
  "template": "Feature Cards (3-up)",
  "overrides": {
    "heading_1": "Our Services",
    "text_1": "What we offer"
  }
}
```

**Options**:
- `--sections FILES` — section JSON files in order (glob patterns supported)
- `--output FILE` — output content JSON file (required)
- `--json` — structured output

**Acceptance**: Can take 5-6 section files from a crawl and produce a valid content JSON that `content update` accepts.

### Phase 5: Migration Verification

**Goal**: Automated comparison between source pages and migrated Vanjaro pages to catch content gaps.

**New command**:
```bash
# Compare a source page against the migrated version
vanjaro migrate verify \
  --source-url https://example.com/about \
  --page-id 36 \
  --json

# Verify all pages from the inventory
vanjaro migrate verify-all \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --page-map artifacts/migration/example-com/page-url-map.json
```

**What it does**:

1. **Fetch source page** — get the original HTML
2. **Fetch migrated page** — get the Vanjaro page content via `content get`
3. **Compare text content** — extract all headings and paragraphs from both, diff them
4. **Compare images** — check that all source images have corresponding Vanjaro assets
5. **Compare links** — check that internal links were rewritten correctly
6. **Compare structure** — count sections, verify same number of major blocks
7. **Report gaps** — list missing content, broken images, unrewritten links

**Output**:
```json
{
  "source_url": "https://example.com/about",
  "page_id": 36,
  "status": "partial",
  "text_match": 0.95,
  "images": {"total": 4, "migrated": 4, "missing": 0},
  "links": {"total": 8, "rewritten": 7, "broken": 1},
  "gaps": [
    {"type": "link", "source": "https://example.com/blog", "message": "No matching page in URL map"}
  ]
}
```

**Options**:
- `--source-url URL` — original page URL
- `--page-id ID` — Vanjaro page ID to compare against
- `--inventory FILE` — site inventory for batch verification
- `--page-map FILE` — URL map for batch verification
- `--threshold FLOAT` — minimum text match score to pass (default: 0.9)
- `--json` — structured output

**Acceptance**: Can compare source vs migrated page and produce an actionable gap report. `verify-all` checks every page in the inventory.

---

## Full Migration Pipeline (after all phases)

```bash
# 1. Crawl the source site
vanjaro migrate crawl https://example.com \
  --output-dir artifacts/migration/example-com

# 2. Review the inventory, adjust if needed
cat artifacts/migration/example-com/site-inventory.json | jq '.pages[].title'

# 3. Apply theme from extracted design tokens
vanjaro theme set-bulk artifacts/migration/example-com/theme-colors.json
vanjaro theme set-bulk artifacts/migration/example-com/theme-typography.json
vanjaro theme css update --file artifacts/migration/example-com/custom.css

# 4. Upload assets in batch
vanjaro assets upload-dir artifacts/migration/example-com/assets/ \
  --folder "Images/Migration/"

# 5. Build block library from the analysis
vanjaro blocks build-library \
  --plan artifacts/migration/example-com/library-plan.json

# 6. Create pages
vanjaro pages create --title "Home" --name "home" --json
vanjaro pages create --title "About" --name "about" --json
# ... (or scripted from inventory)

# 7. Assemble and push content for each page
vanjaro migrate assemble-page \
  --sections artifacts/migration/example-com/pages/home/section-*.json \
  --output home-content.json

vanjaro migrate rewrite-urls \
  --content home-content.json \
  --asset-manifest artifacts/migration/example-com/assets/manifest.json \
  --page-map artifacts/migration/example-com/page-url-map.json

vanjaro content update 35 --file home-content.json
vanjaro content publish 35

# 8. Verify
vanjaro migrate verify-all \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --page-map artifacts/migration/example-com/page-url-map.json
```

---

## Skills & CLI Summary

| Component | Type | Status | Phase |
|-----------|------|--------|-------|
| `site-migrator` | skill | CREATED | — |
| `migrate crawl` | CLI command | NOT STARTED | 1 |
| `assets upload-dir` | CLI command | NOT STARTED | 2 |
| `migrate rewrite-urls` | CLI command | NOT STARTED | 3 |
| `migrate assemble-page` | CLI command | NOT STARTED | 4 |
| `migrate verify` / `verify-all` | CLI command | NOT STARTED | 5 |

## Dependencies & Build Order

```
        ┌──────────┐     ┌──────────┐     ┌──────────┐
        │ Phase 1  │     │ Phase 2  │     │ Phase 4  │
        │  Crawl   │     │  Batch   │     │ Assemble │
        │          │     │  Upload  │     │  Page    │
        └────┬─────┘     └────┬─────┘     └──────────┘
             │                │
             │                ▼
             │          ┌──────────┐
             │          │ Phase 3  │
             │          │  Rewrite │
             │          │  URLs    │
             │          └────┬─────┘
             │               │
             ▼               ▼
        ┌─────────────────────────┐
        │       Phase 5           │
        │  Migration Verification │
        └─────────────────────────┘
```

**Phases 1, 2, and 4 can be built in parallel** — they have no dependencies on each other.

- **Phase 1** (crawl) is standalone — produces the migration artifacts that everything else consumes
- **Phase 2** (batch upload) is standalone — extends the existing `assets` command group
- **Phase 4** (content assembly) is standalone — uses existing `blocks compose` internally
- **Phase 3** (URL rewriting) depends on Phase 2 — needs the asset manifest with Vanjaro URLs populated
- **Phase 5** (verification) depends on all previous phases — needs both source and migrated content to compare

## New Dependency

Phase 1 requires `beautifulsoup4` for HTML parsing. This is the only new dependency across all phases.

```bash
pip install beautifulsoup4
```

Justification: stdlib `html.parser` is too low-level for reliably extracting content from arbitrary websites. BeautifulSoup is the standard Python library for this, lightweight (pure Python, no C extensions), and well-maintained.
