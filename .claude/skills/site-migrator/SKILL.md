---
name: site-migrator
description: Crawls a live source website, extracts content, assets, navigation, and design tokens, then migrates everything to a Vanjaro site using the CLI. Use when the user says "migrate this site", "rebuild this site in Vanjaro", "move this site to Vanjaro", or provides a live URL to replicate.
allowed-tools: Read Write Bash Glob Grep Agent WebFetch
---

<context>
The Vanjaro CLI ships a complete migration pipeline under `vanjaro migrate`. Every
stage below is a real CLI command — no manual `curl`, no hand-written parsers, no
bespoke Python scripts. If a stage says "run command X", run command X. If the CLI
is missing something you need, stop and report it rather than working around it
with a one-off script.

The pipeline is:
```
Source Site (live URL)
  → vanjaro migrate crawl                (Stage 1 — fetch pages, extract sections,
                                           download assets, extract design tokens,
                                           write global/header.json + footer.json)
  → site-builder theme application       (Stage 3.2)
  → vanjaro theme palette-export         (Stage 3.2a — export live theme palette
                                           for color-class mapping in later stages)
  → vanjaro migrate dedup-sections       (Stage 3.3 — detect sections identical
                                           across pages, write global-sections-plan.json,
                                           rewrite member files to {{global:KEY}} stubs)
  → vanjaro blocks build-library         (Stage 3.4 — register content blocks AND
                                           dedup'd global sections; --guids-out writes
                                           the key→GUID manifest for Stage 5.1)
  → vanjaro migrate build-global         (Stage 3.5 — build site-specific
                                           GrapesJS header and footer trees
                                           directly from the crawl — no prefab
                                           template required; embeds live Menu
                                           block by default)
  → vanjaro global-blocks create         (Stage 3.5 — register Site Header and
                                           Site Footer as new global blocks and
                                           capture their GUIDs in block-guids.json)
  → vanjaro migrate create-pages         (Stage 4 — create Vanjaro pages with
                                           hierarchy, collision detection, and
                                           write page-id-map.json)
  → vanjaro migrate assemble-page        (Stage 5.1 — merge sections with
                                           --header-block-guid / --footer-block-guid,
                                           --global-guids for dedup placeholders,
                                           --theme-palette for color-class mapping)
  → vanjaro migrate rewrite-urls         (Stage 5.1 — rewrite image + link URLs)
  → vanjaro content update/publish       (Stage 5.2 — push and publish; the
                                           update command auto-generates the
                                           contentHtml string Vanjaro needs)
  → vanjaro migrate verify-all           (Stage 6 — page-by-page verification;
                                           use --output to persist JSON for gap-report)
  → vanjaro migrate audit-structure      (Stage 6 — structural best-practice lint
                                           against the live rendered site)
  → vanjaro migrate visual-capture       (Stage 6.4 — screenshot pairs; then
                                           /skill migration-visual-report for
                                           the vision score gate: ship at ≥85)
  → vanjaro migrate gap-report           (Stage 6.5 — consolidated punch list
                                           merging verify, audit, and visual findings)
```

**Why the wrapping and contentHtml matter:** The Vanjaro AIPage backend stores
three things — ``contentJSON`` (canonical tree), ``styleJSON`` (styles), and
``contentHtml`` (pre-rendered HTML). The server uses ``contentHtml`` at render
time. Without it, pages save correctly but render **blank** to anonymous
visitors. ``vanjaro content update`` auto-generates ``contentHtml`` from the
component tree as of Phase E, so the CLI path is correct by default. But page
content also **must** be top-level-wrapped in ``globalblockwrapper`` components
referencing the **migration-created** ``Site Header`` and ``Site Footer``
global blocks — not the default install's Header and Footer, which are generic
Vanjaro chrome and have nothing to do with the source site. Stage 3.5 is where
the migration creates those site-specific global blocks from the crawled
``global/header.json`` and ``global/footer.json``; Stage 5.1 then wraps every
page with the GUIDs from Stage 3.5.

All artifacts go to `artifacts/migration/{site-slug}/` in a resumable layout.
</context>

<role>
You are a website migration specialist who drives the `vanjaro migrate` command
pipeline end-to-end. You crawl source sites, extract structure, and coordinate
with the site-builder pipeline for theme and block work. You understand that
content fidelity matters — the migrated site should have the same text, images,
navigation, and visual feel as the source. You prefer shipped commands over
ad-hoc scripts.
</role>

<instructions>

## Before Starting

Load the reference docs:
```
${CLAUDE_SKILL_DIR}/references/crawl-output-format.md
${CLAUDE_SKILL_DIR}/references/url-rewriting.md
```

Also load the site-builder references for the execution stages:
```
.claude/skills/site-builder/references/workflow-checklist.md
.claude/skills/site-builder/references/cli-quick-reference.md
```

### Sanity-check the CLI before you do anything else

A stale `.venv` (missing `beautifulsoup4` or other deps) will crash every `vanjaro`
command on import. Catch this before you spend time crawling:

```bash
vanjaro migrate --help
```

If that prints command help, you're good. If it errors (ImportError / ModuleNotFound)
or prints `"migrate commands need additional dependencies"`, run:

```bash
pip install -e ".[dev]"
```

and re-check. Do not proceed until `vanjaro migrate crawl --help` works.

### Verify the target session is actually live — don't trust `auth status`

`vanjaro auth status` only checks that cookies exist in the local config file. It
does **not** verify the session is live server-side. Use `site health` as the real
liveness check:

```bash
vanjaro site health --json
```

If that errors with "Session expired", re-authenticate non-interactively with
`vanjaro auth login --url <base-url> -u <user> -p <password> --profile <profile>`
using credentials the user has provided (e.g. the repo `.env`). Only ask the
user to log in themselves when no credentials are available to you.

## Overview

The migration has 6 stages:

```
┌─────────────────────────────────────────────────────────┐
│  STAGE 1: CRAWL SOURCE SITE                             │
│  vanjaro migrate crawl                                  │
│  Gate: site-inventory.json + page-url-map.json written  │
├─────────────────────────────────────────────────────────┤
│  STAGE 2: ANALYZE & PLAN                                │
│  Review extracted sections → library plan              │
│  Gate: library-plan.json ready                          │
├─────────────────────────────────────────────────────────┤
│  STAGE 3: SET UP VANJARO TARGET                         │
│  Auth → branding → theme → palette-export → assets →   │
│  dedup-sections → block library (incl. global-sections) │
│  → create site-specific Site Header + Site Footer blocks│
│  Gate: theme applied, palette exported, assets uploaded,│
│        blocks registered, global-guids.json written,    │
│        block-guids.json written with Site Header/Footer  │
├─────────────────────────────────────────────────────────┤
│  STAGE 4: CREATE PAGES                                  │
│  Page hierarchy → shells → SEO → build-id-map           │
│  Gate: all pages created, page-id-map.json written      │
├─────────────────────────────────────────────────────────┤
│  STAGE 5: MIGRATE CONTENT                               │
│  assemble-page (--global-guids + --theme-palette) →     │
│  rewrite-urls → content update/publish                  │
│  Gate: all pages populated with source content          │
├─────────────────────────────────────────────────────────┤
│  STAGE 6: VERIFY                                        │
│  verify-all (--output) → audit-structure → visual QA → │
│  gap-report                                             │
│  Gate: gap-report.md delivered; user accepts gaps       │
└─────────────────────────────────────────────────────────┘
```

## Stage 1: Crawl Source Site

The entire Stage 1 work is one command:

```bash
vanjaro migrate crawl https://example.com \
  --output-dir artifacts/migration/example-com \
  --max-pages 20 \
  --json
```

`vanjaro migrate crawl` does all of the following automatically:

- **Discovers pages** — starts from the homepage, follows same-origin nav links,
  respects `--max-pages`, `--include-paths` and `--exclude-paths` glob filters.
- **Extracts sections per page** — writes one JSON file per section to
  `pages/{slug}/section-{NNN}-{type}.json`, along with a `template` hint mapping
  the section to the closest known block template.
- **Extracts global elements** — writes `global/header.json` and `global/footer.json`
  from the homepage markup.
- **Extracts design tokens** — writes `design-tokens.json` (colors, fonts,
  spacing; schema in `references/crawl-output-format.md`).
- **Downloads assets** — writes `assets/manifest.json` (source URL → local file,
  plus placeholders for the Vanjaro URL that Stage 3 will populate).
- **Writes the master inventory** — `site-inventory.json` with all pages, sections,
  titles, paths, and slugs.
- **Writes the source→Vanjaro URL map** — `page-url-map.json` seeded with the
  crawler's best-guess Vanjaro paths (e.g. `https://example.com/about → /about`).
  Stage 5 uses this for link rewriting.

### Options you'll actually use

| Flag | Purpose |
|------|---------|
| `--max-pages N` | Cap the crawl (default 50). Use a small number like 10–20 for smoke tests. |
| `--include-paths '/services/*'` | Glob patterns (repeatable) to include only matching paths. |
| `--exclude-paths '/blog/*'` | Glob patterns (repeatable) to skip paths. |
| `--skip-assets` | Don't download images. Useful for dry runs. |
| `--json` | Structured output — required for scripting. |

### Stage 1 Gate

Verify the output:

```bash
ls artifacts/migration/example-com/
# Expect: site-inventory.json, page-url-map.json, design-tokens.json,
#         pages/, global/, assets/
```

Open `site-inventory.json` and confirm the page list with the user before
proceeding. They may want to re-run with tighter `--include-paths` or
`--exclude-paths` to narrow scope.

Check `warnings[]` in the crawl output — it is the extraction health signal.
A "yielded 0 sections" warning means the extractor could not read that page's
markup; "no global header or footer" means chrome extraction failed. Also
sanity-check that every `pages/<slug>/` directory contains `section-*.json`
files. If pages extract empty on a site that clearly has content, that is a
CLI bug — report it rather than working around it, and do not proceed to
Stage 2 with empty artifacts.

**Report to the user:**
```
Stage 1: Source Site Crawled ✓
  Source: https://example.com
  Pages found: 5
  Assets downloaded: 24
  Design tokens: extracted
  Artifacts: artifacts/migration/example-com/

  Confirm pages to migrate before proceeding.
```

**Wait for user confirmation** before Stage 2.

## Stage 2: Analyze & Plan

This stage is still judgment-heavy — the CLI crawler tags sections with a
best-guess `template` field, but you need to curate the library plan.

### 2.1 Review the Crawler's Template Hints

Each `pages/{slug}/section-{NNN}-{type}.json` file has a `template` field from
the crawler. Scan them:

```bash
# List all unique section/template pairs
python -c "
import json, glob
pairs = set()
for f in glob.glob('artifacts/migration/example-com/pages/*/section-*.json'):
    d = json.load(open(f))
    pairs.add((d.get('type'), d.get('template')))
for t, tmpl in sorted(pairs):
    print(f'{t:20} -> {tmpl}')
"
```

Review the pairs. The crawler's template hints are starting suggestions, not
decisions — you still decide which ones to accept, adjust, or reject.

### 2.2 Generate Library Plan

Follow the `block-composer` skill workflow to build `library-plan.json` from the
reviewed sections. Use the extracted content (headings, paragraphs, button
labels, list items) as the overrides for each block so the final library
contains real copy, not placeholders.

**List-item overrides**: The crawler now extracts `list_items` from `<ul>`/`<ol>`
elements. Include `list-item_N` overrides in the library plan for any template
that has list components (footers, pricing cards, feature lists). Numbering is
continuous across the entire template — use `--list-slots` to check slot indices.

**Card limit handling**: When a source section has more items than a template
supports (e.g., 6 portfolio items but a 3-up card template), split it into
multiple plan entries:

1. Check how many items the template holds: `vanjaro blocks compose "<name>" --list-slots`
2. Divide the source content into N-item chunks matching the template capacity
3. Create one plan entry per chunk, naming them sequentially: "Portfolio Row 1",
   "Portfolio Row 2"
4. Each entry gets its own section heading (`heading_1`) — repeat the original
   or use a variation like "More Projects"

If `assemble-page` detects overflow it warns on stderr with the dropped keys,
but it's better to split at plan time so nothing is lost.

### 2.3 Identify New Templates Needed

If the source has patterns the existing templates don't cover, recommend:
1. Adapt an existing template (medium confidence match)
2. Create a new template with `block-template-author`
3. Use Custom Code blocks for complex interactive patterns

### 2.4 Stage 2 Gate

```
Stage 2: Analysis Complete ✓
  Unique patterns found: 8
  Matched to existing templates: 6/8
  New templates needed: 2 (Blog Post Card, Team Grid)
  Library plan: artifacts/migration/example-com/library-plan.json
```

Create any needed templates, then move on.

## Stage 2.5: Single-Page Source → Multi-Page Target (when applicable)

Skip this section if the source site already has one URL per nav entry. It
only applies when the source is a **single-page site with anchor
navigation** (e.g. `#home`, `#about`, `#portfolio`, `#blog`, `#contact`) that
the user wants migrated into discrete Vanjaro pages.

### Why it needs manual handling

`vanjaro migrate crawl` sees discrete URLs. For a single-page site it
produces:

- **One** `pages/home/` directory containing every section (hero, about,
  portfolio, blog, contact — all in one folder).
- Exactly one inventory entry keyed by the home URL.
- A `page-url-map.json` with one entry: `"https://source.com/": "/"`.

`vanjaro migrate build-id-map` in Stage 4 will happily match that one entry
to the Vanjaro home page, but there's nothing to map the `#about` anchor to
the separate `/About` page you intend to create. Stage 5's `rewrite-urls`
similarly has no way to rewrite `https://source.com/#portfolio` to the new
Vanjaro `/Portfolio` path.

### How to extend the maps

After Stage 4 creates the Vanjaro pages for the split targets, **hand-edit
both `page-url-map.json` and `page-id-map.json`** to add fragment-keyed
entries for each anchor section:

**`page-url-map.json`** — source fragment URL → Vanjaro path:
```json
{
  "https://source.com/": "/",
  "https://source.com/#home": "/",
  "https://source.com/#about": "/About",
  "https://source.com/#portfolio": "/Portfolio",
  "https://source.com/#blog": "/Blog",
  "https://source.com/#contact": "/Contact"
}
```

**`page-id-map.json`** — source fragment URL → Vanjaro page ID:
```json
{
  "https://source.com/": 21,
  "https://source.com/#home": 21,
  "https://source.com/#about": 35,
  "https://source.com/#portfolio": 36,
  "https://source.com/#blog": 37,
  "https://source.com/#contact": 38
}
```

`vanjaro migrate rewrite-urls` tries exact URL match first, so fragment-
keyed entries resolve before the path-only fallback (which would incorrectly
fold every anchor to the home page). `verify-all` will use the extended
`page-id-map.json` to verify each split page against its matching source
section.

### How to split the content across the new pages

The crawl put every home section in `pages/home/section-NNN-*.json`. For
each target page you need to:

1. Identify which source section file corresponds to which target page.
   For the typical single-page layout:
   - `section-001-hero.json` → Home page
   - `section-002-*.json` (about) → About page
   - `section-003-*.json` (portfolio / gallery) → Portfolio page
   - `section-004-*.json` (blog / cards) → Blog page
   - `section-005-*.json` (contact) → Contact page
2. Reference each section's content as the override source when composing
   the corresponding block in the library plan — not a single "Home" entry
   with five blocks.
3. In Stage 5, assemble each target page from its specific section file
   rather than using a glob over the whole `pages/home/` directory.

### Verification caveat

`vanjaro migrate verify-all` iterates the crawl **inventory**, not the
Vanjaro page list. Since the split target pages (About, Contact, etc.)
don't have their own inventory entries, they're not automatically verified.
Run `vanjaro migrate verify` per-page with `--source-url` pointing at the
fragment URL and `--page-id` at the split target to verify each split page
individually.

## Stage 3: Set Up Vanjaro Target

This maps to site-builder Stages 1-3.

### 3.1 Foundation

```bash
vanjaro site health --json        # real liveness check (don't trust auth status)
vanjaro api-key status --json
vanjaro branding update --site-name "Site Name" --footer-text "Copyright..."
```

**Branding and theme are PORTAL-WIDE singletons.** Like the theme (Stage 3.2),
`branding update` changes the site name and footer text for every page on the
portal — on a shared portal this restyles/renames other migrated sites. Check
`vanjaro site info` first, and on a shared target call the blast radius out to
the user before applying.

### 3.2 Apply Theme

Using `design-tokens.json` from Stage 1:

1. Register custom fonts
2. Apply colors, site globals, heading typography, paragraph typography, button styling, menu, links
3. Apply custom CSS for anything beyond theme controls

Follow `references/theme-apply.md` (in this skill) for the variable-discovery
workflow (`vanjaro theme get --json`), the `Site`/`Styles:*` category map, and
the set-bulk file format.

### 3.2a Export the Theme Palette

After the theme is applied, export the live palette so later stages can emit
theme classes instead of inline colors:

```bash
vanjaro theme palette-export \
  --output artifacts/migration/example-com/theme-palette.json
```

This reads the ten Bootstrap palette slots (primary, secondary, tertiary, …)
from the live theme settings and writes a `{slot: hex}` JSON file. Two
downstream commands consume it:

- `migrate assemble-page --theme-palette <file>` — maps matching section
  background colors to `bg-primary`, `bg-secondary`, etc. rather than baking
  in `style="background-color:#..."` inline rules.
- `migrate build-global --theme-palette <file>` — does the same for header
  and footer band colors.

The palette must be exported **after** `theme set-bulk` / `theme apply`
completes, because it reads the currently saved theme values. If the theme
changes later (e.g., a color tweak), re-export and re-run assemble-page.

### 3.3 Upload Assets and Update the Manifest

The crawler writes `assets/manifest.json` with one entry per downloaded file.
Each entry starts with empty `vanjaro_url` / `vanjaro_file_id` fields.

Use `vanjaro assets upload-dir` to bulk-upload every asset in the crawl's
assets directory and auto-patch the manifest in place:

```bash
# Dry-run first to see what would be uploaded
vanjaro assets upload-dir artifacts/migration/example-com/assets \
  --folder "Images/" --dry-run

# Real upload — writes vanjaro_url + vanjaro_file_id back to manifest.json
vanjaro assets upload-dir artifacts/migration/example-com/assets \
  --folder "Images/" --json
```

`upload-dir` features:
- Recursively finds every supported media file (jpg, png, gif, webp, svg, mp4, webm, pdf).
- Reuses the existing `manifest.json` if present — new entries are added, old ones are updated with upload status.
- `--skip-existing` — skip files already marked uploaded (idempotent re-runs).
- `--dry-run` — list files without uploading.
- Writes the manifest after every successful upload so a mid-run failure
  still preserves progress.

**Do not** use `vanjaro assets upload <file>` in a shell loop. `upload-dir` is
the canonical bulk path and handles the manifest accounting for you.

Stage 5 (`vanjaro migrate rewrite-urls`) reads the patched manifest to rewrite
image `src` attributes in the migrated content.

### 3.3a Detect and Collapse Cross-Page Duplicate Sections

Before registering the block library, run the dedup pass. Sections that are
identical across two or more pages get promoted to global blocks automatically
— one registered block, updated everywhere:

```bash
# Dry run to preview groups before committing
vanjaro migrate dedup-sections artifacts/migration/example-com --dry-run

# Write global-sections-plan.json and rewrite member section files to stubs
vanjaro migrate dedup-sections artifacts/migration/example-com --json
```

What this does:

- Scans every `pages/*/section-*.json` file and identifies groups with
  identical normalized content across two or more distinct pages.
- Writes `global-sections-plan.json` at the migration root — a build-library
  plan where each entry has `"type": "global"` and `"category": "Global Sections"`.
- Rewrites each duplicate section file **in place** to a stub containing a
  `{{global:KEY}}` placeholder. The original content is preserved under
  `"original_backup"` in the same file so the rewrite is reversible.

If the command reports "No cross-page duplicate sections found", skip 3.4a and
proceed normally — there's nothing to dedup.

### 3.4 Register Block Library

```bash
# Dry run
vanjaro blocks build-library --plan artifacts/migration/example-com/library-plan.json --dry-run

# Register content blocks
vanjaro blocks build-library --plan artifacts/migration/example-com/library-plan.json
```

### 3.4a Register Global Sections and Write the GUID Manifest

If dedup-sections produced a `global-sections-plan.json`, register those global
blocks separately and capture the key→GUID manifest that Stage 5.1 needs:

```bash
vanjaro blocks build-library \
  --plan artifacts/migration/example-com/global-sections-plan.json \
  --guids-out artifacts/migration/example-com/global-guids.json
```

`--guids-out` writes a `{key: guid}` JSON file. Stage 5.1's `assemble-page
--global-guids` reads this file to swap `{{global:KEY}}` stubs in the rewritten
section files for the real registered GUIDs. Without this file, assemble-page
will error when it encounters a stub with an unresolved placeholder.

### 3.5 Create Site-Specific Global Header and Footer Blocks

**This step is mandatory for content fidelity** — the crawled source has its
own header (logo, nav, branding) and footer (copyright, links, social).
Stage 5 will wrap every migrated page with ``globalblockwrapper`` components
referencing these blocks, so they have to exist **before** Stage 5 content
assembly starts.

Do **not** wrap pages with the default Vanjaro install's ``Header`` and
``Footer`` global blocks — those represent the fresh-install theme's chrome,
not the migrated site's. Using them means the migrated site will render with
the source's page content sandwiched between Vanjaro's default chrome, which
is a fidelity failure.

#### 3.5.1 Build From the Crawled Header/Footer

Every source site has a different header and footer design — prefab
block templates are always a fidelity compromise. ``vanjaro migrate
build-global`` builds the GrapesJS component tree directly from the
crawled content, no template step required.

The crawler writes ``global/header.json`` and ``global/footer.json`` during
Stage 1. Each file is a section-shaped object with ``type`` and
``content`` (headings, paragraphs, images, links, buttons, list_items,
nav_items). ``build-global`` reads one of those files, dispatches to the
right builder based on ``--kind``, and writes a ``{components, styles}``
JSON ready for ``global-blocks create --file``:

```bash
# Inspect what the crawler captured
cat artifacts/migration/example-com/global/header.json
cat artifacts/migration/example-com/global/footer.json

# Build the header — embeds Vanjaro's live Menu block by default so the nav
# reflects the actual DNN page tree at render time.
# Pass --theme-palette to emit bg-*/text-* classes instead of inline colors.
vanjaro migrate build-global \
  --source artifacts/migration/example-com/global/header.json \
  --kind header \
  --theme-palette artifacts/migration/example-com/theme-palette.json \
  --output artifacts/migration/example-com/global/header-built.json \
  --json

# Build the footer (section > container > columns from headings+list_items,
# optional about/copyright row, optional badges row)
vanjaro migrate build-global \
  --source artifacts/migration/example-com/global/footer.json \
  --kind footer \
  --theme-palette artifacts/migration/example-com/theme-palette.json \
  --output artifacts/migration/example-com/global/footer-built.json \
  --json
```

**Rewrite asset URLs in the built globals BEFORE registering.** `build-global`
copies crawled image `src` values verbatim, so the header logo and footer
badges still point at the SOURCE site's CDN. After assets are uploaded
(manifest has `vanjaro_url` values), run the built files through rewrite-urls,
then register the rewritten output:

```bash
vanjaro migrate rewrite-urls \
  --content artifacts/migration/example-com/global/header-built.json \
  --asset-manifest artifacts/migration/example-com/assets/manifest.json \
  --json
# repeat for footer-built.json, then global-blocks create --file <rewritten>
```

**Live Menu vs. static nav**: By default `build-global` embeds Vanjaro's
native Menu blockwrapper in the header — the nav items shown to visitors are
pulled live from the DNN page tree at render time, not from the crawled
`nav_items`. This means the pages you create in Stage 4 will appear in the nav
automatically. Because the Menu renders real page data, **create pages (Stage 4)
before the header renders meaningfully** for the first time.

**On a SHARED portal, `--static-nav` is the correct default, not the
exception**: the live Menu renders the ENTIRE portal page tree, so a portal
hosting multiple migrated sites puts every other site's pages in your nav.
Also use `--static-nav` when the DNN page tree doesn't match the source site's
intended navigation (specific link order, external links DNN won't manage):

```bash
vanjaro migrate build-global \
  --source artifacts/migration/example-com/global/header.json \
  --kind header \
  --static-nav \
  --output artifacts/migration/example-com/global/header-built.json
```

**Layout produced**:
- **Header**: section.vj-section.py-3 > container > row.align-items-center >
  col-md-3 (first crawled image, as logo) + col-md-9 (nav list built from
  ``nav_items`` → ``list_items`` → ``links``, first non-empty source wins).
- **Footer**: section.vj-section.py-5.bg-light > container >
  - row: N columns (one per crawled heading) with list_items split evenly,
    or one col-12 column if no headings exist
  - optional row (``mt-4 text-center``) with the first paragraph as the
    copyright/about text
  - optional row (``mt-4 justify-content-center``) with up to 6 images as
    badges (chamber memberships, partner logos, etc.)

If the crawler captured nothing, the builders produce a placeholder section
with an explanatory text so the registered block is still a valid GrapesJS
tree — you can edit it in the Vanjaro UI afterward. If the source site has
a layout the builders don't handle well (nested dropdowns in the header,
multi-row grid footer, etc.), hand-edit the output JSON before running
``global-blocks create``, or extend the builder in
``vanjaro_cli/migration/global_blocks.py``.

#### 3.5.2 Register and Capture the GUIDs

Register each built file as a new global block. **Save the returned GUIDs**
— they're what Stage 5.1 needs for the ``--header-block-guid`` /
``--footer-block-guid`` flags:

```bash
# Register and capture
HEADER_GUID=$(vanjaro global-blocks create \
  --name "Site Header" --category "Navigation" \
  --file artifacts/migration/example-com/global/header-built.json \
  --json | python -c "import json, sys; print(json.load(sys.stdin)['guid'])")
vanjaro global-blocks publish "$HEADER_GUID"

FOOTER_GUID=$(vanjaro global-blocks create \
  --name "Site Footer" --category "Navigation" \
  --file artifacts/migration/example-com/global/footer-built.json \
  --json | python -c "import json, sys; print(json.load(sys.stdin)['guid'])")
vanjaro global-blocks publish "$FOOTER_GUID"

# Persist them so Stage 5 can pick them up without re-deriving
cat > artifacts/migration/example-com/global/block-guids.json <<EOF
{
  "header": "$HEADER_GUID",
  "footer": "$FOOTER_GUID"
}
EOF
```

Re-runs: if the blocks already exist from a previous attempt, use
``vanjaro global-blocks update GUID --file ...`` to refresh their content
instead of creating duplicates. Check ``vanjaro global-blocks list --json``
first.

### 3.6 Stage 3 Gate

```bash
vanjaro theme get --modified --json | jq '.total'
vanjaro custom-blocks list --json
vanjaro assets list --json
vanjaro global-blocks list --json | jq '.[] | {name, guid}'  # Site Header + Site Footer present
cat artifacts/migration/example-com/global/block-guids.json   # header + footer guids saved
cat artifacts/migration/example-com/theme-palette.json        # palette exported
# If dedup ran:
cat artifacts/migration/example-com/global-guids.json         # dedup key→guid manifest
```

## Stage 4: Create Pages

### 4.1 Create Pages From the Inventory

One command creates every page from the crawl inventory, respects hierarchy,
skips existing pages by name, and writes both ``page-id-map.json`` and
``page-url-map.json`` with the actual server-assigned URLs:

```bash
vanjaro migrate create-pages \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --json
```

What it does automatically:

- **Pre-flight collision check** — lists existing Vanjaro pages and skips any
  whose slug (case-insensitive) already exists. The existing page id is still
  registered for child parenting, so e.g. a migrated ``blog-post-1`` will be
  parented to an existing ``Blog`` page.
- **Topological sort** — parents are always created before their children, so
  each child's ``parentId`` points at the freshly returned tab id.
- **``isVisible`` from nav** — pages linked from the crawled header
  ``nav_items`` are created visible in the menu; pages not in the nav default
  to hidden. (The AIPage/Create endpoint silently ignores ``includeInMenu``
  and accepts ``isVisible`` — the CLI uses the right field.)
- **Writes ``page-id-map.json``** — source URL → Vanjaro page id.
- **Overwrites ``page-url-map.json``** — source URL → the actual DNN path
  returned by the API, including parent-aware nesting (e.g.
  ``/blog/blog-post-1`` for a child of blog). The crawler's original flat-slug
  version is replaced.

### 4.2 Dry Run First (Optional but Recommended)

```bash
vanjaro migrate create-pages \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --dry-run
```

The dry run prints the planned creation order, parent slugs, and menu
visibility without calling the API. Good for sanity-checking the hierarchy
before writing to the live instance.

### 4.3 Alternative: Build-ID-Map for Existing Pages

If the migration target already has all the pages created manually and you
only want to map source URLs to existing Vanjaro page ids, use
``build-id-map`` instead of ``create-pages``:

```bash
vanjaro migrate build-id-map \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --output artifacts/migration/example-com/page-id-map.json \
  --json
```

The command matches inventory pages to Vanjaro pages by path, portal home,
title, and slug — in that order. Any unmatched pages are reported as warnings;
hand-edit the resulting JSON to fix them.

### 4.4 Audit Shells and Set SEO

```bash
vanjaro pages shell PAGE_ID --fix --json
vanjaro pages seo-update PAGE_ID \
  --title "Source Page Title" \
  --description "Source meta description" \
  --keywords "source, keywords"
```

The crawler saves ``meta_description`` and other SEO fields on each page
entry in ``site-inventory.json`` — use those as the inputs.

### 4.5 Stage 4 Gate

```bash
vanjaro pages list --json                            # includes parent_id now
vanjaro site nav --json
cat artifacts/migration/example-com/page-id-map.json # every page mapped
```

## Stage 5: Migrate Content

### 5.0 Load the Global Block GUIDs From Stage 3.5

Stage 3.5 created and registered site-specific ``Site Header`` and ``Site
Footer`` global blocks from the crawled content, and wrote their GUIDs to
``global/block-guids.json``. Load them now so Stage 5.1 can wrap every
page with the correct wrappers:

```bash
HEADER_GUID=$(python -c "import json; print(json.load(open('artifacts/migration/example-com/global/block-guids.json'))['header'])")
FOOTER_GUID=$(python -c "import json; print(json.load(open('artifacts/migration/example-com/global/block-guids.json'))['footer'])")
```

**Use the Stage-3.5 GUIDs, not the default install's ``Header``/``Footer``
GUIDs from ``vanjaro global-blocks list``.** The defaults represent the
fresh-install Vanjaro theme chrome and have nothing to do with the source
site. Wrapping with them produces a migrated site that has the source's
page content between Vanjaro's default chrome — a fidelity failure you
won't catch until visual QA.

If Stage 3.5 wasn't run (or the ``block-guids.json`` file is missing), stop
and go back to Stage 3.5 rather than falling back to the install defaults.

``assemble-page`` needs these GUIDs to wrap each page with
``globalblockwrapper`` components. Without wrapping, migrated pages store
correctly but render blank to anonymous visitors because Vanjaro's renderer
has no site chrome to emit around page content.

### 5.1 Assemble and Rewrite Each Page

For each page, two commands do the heavy lifting:

```bash
# 1. Merge the per-section files and wrap with global header/footer.
#    --global-guids resolves {{global:KEY}} stubs from dedup-sections.
#    --theme-palette maps matching band colors to bg-*/text-* theme classes.
vanjaro migrate assemble-page \
  --sections "artifacts/migration/example-com/pages/home/section-*.json" \
  --output artifacts/migration/example-com/pages/home/content.json \
  --header-block-guid "$HEADER_GUID" \
  --footer-block-guid "$FOOTER_GUID" \
  --global-guids artifacts/migration/example-com/global-guids.json \
  --theme-palette artifacts/migration/example-com/theme-palette.json \
  --json

# 2. Rewrite image + internal link URLs to Vanjaro paths
vanjaro migrate rewrite-urls \
  --content artifacts/migration/example-com/pages/home/content.json \
  --asset-manifest artifacts/migration/example-com/assets/manifest.json \
  --page-map artifacts/migration/example-com/page-url-map.json \
  --report --json
```

`assemble-page` walks section files in natural-sort order (so `section-2-*`
comes before `section-10-*`), composes each one against the block template it
references, applies extracted content as overrides, and emits a single
`content.json`. When the ``--header-block-guid`` / ``--footer-block-guid``
flags are provided, it prepends and appends ``globalblockwrapper`` components
referencing those global block instances so Vanjaro's server-side renderer
can emit the site chrome.

**Don't skip the wrapping flags for migrations.** A page assembled without
them pushes successfully and is stored correctly in the AIPage backend, but
``content update`` will also generate a matching empty-chrome ``contentHtml``
and the rendered page will have only the page sections with no header/footer.
Anonymous visitors see a broken layout.

`rewrite-urls` walks the resulting component tree and replaces:
- image `src` attributes → Vanjaro asset URLs from `assets/manifest.json`
- internal `href` attributes → Vanjaro page paths from `page-url-map.json`
- External links, anchors, `mailto:`, and `tel:` are left untouched.

### 5.2 Push and Publish

For each page:

```bash
# Snapshot the current state before overwriting
vanjaro content snapshot PAGE_ID

# Push as draft (does NOT publish yet).
# content update auto-generates the contentHtml Vanjaro needs at render
# time — it walks the component tree and serializes top-level nodes. You
# don't need to pre-render HTML yourself, but the component tree MUST
# already be wrapped with global header/footer from Stage 5.1.
vanjaro content update PAGE_ID --file artifacts/migration/example-com/pages/home/content.json

# Verify structure
vanjaro blocks tree PAGE_ID

# Review draft vs. published
vanjaro content diff PAGE_ID

# Publish
vanjaro content publish PAGE_ID
```

### 5.2a Smoke-Test Anonymous Render

After publishing each page, fetch it as an unauthenticated visitor to
verify the server actually renders the migrated content:

```bash
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" \
  http://site.local/page-path
```

A healthy page returns HTTP 200 with 15–30 KB of body. A blank page
(under 5 KB) means the ``contentHtml`` path didn't work — most likely
the assembled file was missing the global header/footer wrappers.
Re-run Stage 5.1 with ``--header-block-guid`` / ``--footer-block-guid``
and push again.

### 5.3 Refine Global Blocks (Optional)

The ``Site Header`` and ``Site Footer`` global blocks were already created
in Stage 3.5 and wrapped into every migrated page by Stage 5.1. If the
smoke test in Stage 5.2a reveals that the header or footer is wrong (wrong
logo, missing links, outdated copy), iterate here using
``vanjaro global-blocks update``:

```bash
# Re-compose with updated overrides
vanjaro blocks compose "Site Header (centered logo)" \
  --set logo_src="/Portals/0/logo-v2.png" \
  --output artifacts/migration/example-com/global/header-composed.json

# Push the new content to the existing block (keeps the same GUID)
vanjaro global-blocks update "$HEADER_GUID" \
  --file artifacts/migration/example-com/global/header-composed.json
vanjaro global-blocks publish "$HEADER_GUID"
```

Every migrated page that wraps ``$HEADER_GUID`` picks up the new content
automatically at render time — no need to re-wrap or re-publish pages.
That's the whole point of the wrapper indirection.

### 5.4 Stage 5 Gate

```
Stage 5: Content Migrated ✓
  Pages populated: 5/5
  Images rewritten: 24 references updated
  Internal links rewritten: 18 references updated
  Global blocks: header + footer published
  All pages published
```

## Stage 6: Verify

### 6.1 Run Automated Verification

The CLI has a verifier that compares each migrated page against its source crawl:

```bash
vanjaro migrate verify-all \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --page-id-map artifacts/migration/example-com/page-id-map.json \
  --threshold 0.9 \
  --output artifacts/migration/example-com/verify-report.json \
  --json
```

**Important**: always pass `--output` to persist the JSON report to disk.
`gap-report` (Stage 6.5) reads it via `--verify-json`. Without `--output`,
the JSON is only printed to stdout and cannot be passed downstream.

`verify-all` checks, per page:
- **Text match** — paragraphs and headings against the source, scored against `--threshold`
- **Structure** — section counts and types
- **Images** — every source image URL is present in the migrated content (via the asset manifest)
- **Links** — internal links resolve to Vanjaro pages
- **Metadata** — title, description, keywords

For single-page verification use `vanjaro migrate verify` with
`--source-url`, `--page-id`, and optional `--header-block-name` /
`--footer-block-name` to also check global blocks.

### 6.2 Audit Structure

After content verification passes, run the structural audit against the live
rendered site. This checks things `verify-all` can't see — whether the migrated
pages use theme classes rather than inline styles, whether global blocks are
referenced correctly, and whether images have responsive wrappers:

```bash
# Audit all published pages at once (dedicated portal only)
vanjaro migrate audit-structure --all \
  --json artifacts/migration/example-com/audit-report.json

# Or target specific paths
vanjaro migrate audit-structure \
  --page /home --page /about \
  --json artifacts/migration/example-com/audit-report.json
```

On a SHARED portal use `--page` targeting for this migration's pages only —
`--all` audits every published page on the portal, so the report (and any
gap-report built from it) gets polluted with other sites' findings.

The audit scores each page 0–100 across four checks: `inline-styles`,
`theme-classes`, `responsive-images`, and `composition`. A site composite score
is also emitted. Findings in the console report call out the worst offenders.

Save the JSON output — Stage 6.5 (`gap-report`) reads it via `--audit-json`.

### 6.3 Report Gaps

Review the verify report. Common gaps to expect:

| Gap | Why | Recommended Fix |
|-----|-----|-----------------|
| Interactive elements (accordions, tabs) | No Vanjaro primitive for these | Custom Code block or skip |
| Animations/transitions | CSS-only, not in theme controls | Add to custom CSS |
| Forms | Source form provider differs | Rebuild with DNN form module |
| Blog / dynamic content | Static migration only | Set up DNN blog module separately |
| Video embeds | Different embed format | Re-embed using Vanjaro video block |
| Maps | API key differs | Re-embed with new API key |

### 6.4 Fix Loop

For each gap the user wants fixed:
1. Identify the fix approach
2. Apply the fix (often re-running `assemble-page` + `rewrite-urls` + `content update`)
3. Re-run `vanjaro migrate verify` for that page
4. Move to the next gap

### 6.5 Visual QA Gate (REQUIRED — text verification alone is not enough)

`verify-all` compares stored content, not what visitors see. Pages can pass
text verification while rendering blank, showing wrong sections, or wearing
the default theme. Every migration must pass the visual gate before it is
declared done:

```bash
vanjaro migrate visual-capture --dir artifacts/migration/{site-slug} --json
```

This screenshots every source/migrated page pair (anonymous, so screenshots
show what visitors see) into `{dir}/visual-report/` with a `manifest.json`.
Treat its warnings as findings: HTTP errors, error-page markers, and migrated
pages that render identically (empty-content signal).

Then run the vision comparison and fix loop:

1. `/skill migration-visual-report artifacts/migration/{site-slug}` — reads
   the screenshot pairs with Claude Vision, writes
   `visual-report/vision-report.json` with per-page scores and systemic
   findings mapped to pipeline code.
2. If `overall_score < 85` or any high-severity systemic finding exists, run
   `/skill migration-visual-fix artifacts/migration/{site-slug}` to iterate.

**The migration is shippable at overall_score ≥ 85 with no high-severity
systemic findings.** Include the final score in the migration report.

### 6.6 Gap Report — the Human Deliverable

After visual QA, merge all three verification sources into a single
severity-sorted punch list. This is the artifact you hand to the user that
describes what manual work remains:

```bash
vanjaro migrate gap-report artifacts/migration/example-com \
  --verify-json artifacts/migration/example-com/verify-report.json \
  --audit-json artifacts/migration/example-com/audit-report.json \
  --visual-report artifacts/migration/example-com/visual-report/vision-report.md \
  --output artifacts/migration/example-com/gap-report.md \
  --json artifacts/migration/example-com/gaps.json
```

Flags:
- `--verify-json` — path to the `verify-all --output` JSON (required for content gaps)
- `--audit-json` — path to the `audit-structure --json` report (required for structural gaps)
- `--visual-report` — optional path to the visual report markdown from `/skill migration-visual-report`
- `--output` — where to write the markdown punch list (defaults to `{root}/gap-report.md`)
- `--json` — also write a machine-readable JSON with severity counts

At least one of `--verify-json` or `--audit-json` is required. The output is a
human-readable markdown file sorted by severity (high → medium → low) with a
suggested action for each item.

### 6.7 Final Report

```
Migration Complete
═══════════════════════════════════════════════════
Source:   https://example.com
Target:   http://site.local

Pages migrated:     5/5
Sections migrated:  22/22
Images migrated:    24/24
Theme controls:     108 applied
Custom blocks:      8 in editor sidebar
Global blocks:      2 (header + footer)

Verify report:  artifacts/migration/example-com/verify-report.json
Audit score:    87/100 (artifacts/migration/example-com/audit-report.json)
Visual score:   91/100 (visual-report/vision-report.json)
Gap report:     artifacts/migration/example-com/gap-report.md

Known gaps:
  - Forms are deliberately NOT migrated as working or lookalike HTML forms
    — the site owner builds forms with the platform's forms plugin, which
    needs manual setup. Where the source had a form (including JS-widget
    forms captured by a --rendered crawl), the migrated page shows a
    dashed-border placeholder listing the detected fields (required ones
    starred) so the manual pass knows exactly what to configure and where.
    Never emit raw <form>/<input> markup or wire a form module yourself.
  - Blog page is static snapshot (no dynamic posts)

Artifacts:
  artifacts/migration/example-com/
    site-inventory.json      — master manifest
    design-tokens.json       — extracted theme data
    library-plan.json        — block composition plan
    page-url-map.json        — source URL → Vanjaro path
    page-id-map.json         — source URL → Vanjaro page ID
    assets/manifest.json     — image upload mapping
    pages/                   — per-page section + content JSON
    global/                  — header/footer content
    theme-palette.json       — exported palette slot→hex mapping
    global-sections-plan.json — dedup'd sections plan (if any)
    global-guids.json        — dedup key→GUID manifest (if any)
    verify-report.json       — verification gap report
    audit-report.json        — structural best-practice audit
    visual-report/           — screenshot pairs + manifest + vision-report.json
    gap-report.md            — consolidated human-readable punch list
```

## Resuming Interrupted Work

Check what's been done:

```bash
# What crawl artifacts exist?
ls artifacts/migration/{site-slug}/

# What's on the Vanjaro side?
vanjaro theme get --modified --json | jq '.total'
vanjaro custom-blocks list --json
vanjaro assets list --json
vanjaro pages list --json
```

Each stage's artifacts are self-contained. Resume from the last incomplete stage.

## Anti-patterns — don't do these

- **Don't write a one-off crawler** in `tools/`, inline Python, or shell loops.
  `vanjaro migrate crawl` exists. If it's missing a feature you need, report it
  as a CLI bug instead of duplicating it.
- **Don't use `curl` / `wget`** to download assets. The sandbox may block them,
  and the crawler already handles asset download through `download_assets`.
- **Don't trust `vanjaro auth status`.** It only checks local cookies. Use
  `vanjaro site health --json` as the real liveness check.
- **Don't hand-roll URL rewriting.** `vanjaro migrate rewrite-urls` walks the
  component tree and handles images, internal links, and external-link preservation.
- **Don't publish before snapshotting.** Always `vanjaro content snapshot PAGE_ID`
  before `vanjaro content update` so there's a rollback point.
- **Don't skip the global block wrapping flags.** Running `migrate assemble-page`
  without `--header-block-guid` / `--footer-block-guid` produces a page that
  stores and publishes successfully but renders blank to anonymous visitors
  because Vanjaro's server has no site chrome to emit around the page
  content. Always pass both guids during a migration. If you're pushing
  manual content edits outside the migration flow, the same wrapping rule
  applies — make sure the top-level components include the `globalblockwrapper`
  entries.
- **Don't skip dedup-sections when sections repeat across pages.** If the same
  CTA band, contact section, or "About" blurb appears on multiple pages, it
  should be one registered global block — not N identical custom blocks that
  drift apart when content is edited. `migrate dedup-sections` handles this
  automatically. The resulting `global-sections-plan.json` feeds into
  `blocks build-library --guids-out` and `assemble-page --global-guids`.
- **Don't assemble pages before exporting the theme palette.** Running
  `assemble-page` without `--theme-palette` bakes section band colors as inline
  `style="background-color:#..."` attributes. Those inline styles override theme
  classes and break re-theming. Export the palette after theme application and
  pass it to both `assemble-page` and `build-global`.
- **Don't skip `--output` on `verify-all`.** The JSON report is required by
  `gap-report --verify-json`. Printing to stdout only means the data is lost.
- **Don't wrap with the default install's ``Header``/``Footer`` guids.**
  Those are generic Vanjaro chrome — they have nothing to do with the
  source site. Using them gives you the source's page content sandwiched
  between default Vanjaro chrome, which is a fidelity failure you'll catch
  at visual QA and then have to re-wrap every page to fix. Stage 3.5 exists
  specifically to create migration-owned ``Site Header`` and ``Site Footer``
  blocks from the crawled ``global/header.json`` and ``global/footer.json``.
  Use their GUIDs — not the install defaults.

</instructions>

<examples>
<example>
<input>Migrate https://example-coaching.com to our Vanjaro site at http://coaching.local</input>
<output>
Starting migration from https://example-coaching.com.

First, sanity-check the CLI and target:

```bash
vanjaro migrate --help            # confirm deps are installed
vanjaro site health --json        # confirm session is live
```

**Stage 1: Crawling source site...**

```bash
vanjaro migrate crawl https://example-coaching.com \
  --output-dir artifacts/migration/example-coaching-com \
  --max-pages 15 --json
```

Result: 5 pages, 22 sections, 18 assets, design tokens extracted.

Please review `artifacts/migration/example-coaching-com/site-inventory.json`.
Any pages to exclude before I proceed?
</output>
</example>

<example>
<input>I've already crawled the site. The artifacts are in artifacts/migration/acme-corp/. Pick up from Stage 3.</input>
<output>
Loading existing crawl artifacts...

- site-inventory.json: 7 pages, 31 sections
- design-tokens.json: present
- library-plan.json: present (10 blocks planned)
- assets/manifest.json: 42 images downloaded

Checking Vanjaro target status:
```bash
vanjaro site health --json
vanjaro theme get --modified --json | jq '.total'
vanjaro custom-blocks list --json
vanjaro pages list --json
```

Starting at Stage 3: Set Up Vanjaro Target...
</output>
</example>
</examples>

<constraints>
- Use the `vanjaro migrate` subcommands for every stage that has one. Don't duplicate them with ad-hoc scripts.
- Always crawl responsibly — the CLI crawler already rate-limits and respects robots signals. Don't work around it.
- Download assets via `vanjaro migrate crawl` (which uses the shared `download_assets` helper). Don't use `curl` or `wget`.
- Wait for user confirmation after Stage 1 (page list) and before Stage 5 publishing.
- Never overwrite existing Vanjaro content without snapshotting first.
- Rewrite ALL image URLs and internal links via `vanjaro migrate rewrite-urls`. Leave external links, anchors, mailto, and tel links unchanged.
- **Wrap every assembled page with global header/footer guids.** The `migrate assemble-page` command takes `--header-block-guid` and `--footer-block-guid` — always pass both during migration. A page pushed without wrapping stores and publishes successfully but renders blank to anonymous visitors.
- **Smoke-test anonymous render** after publishing each page — a live fetch under 5 KB is a rendering failure, usually caused by missing global wrappers.
- Report gaps honestly — don't claim interactive elements migrated if they didn't.
- Keep all migration artifacts in `artifacts/migration/{site-slug}/` — organized and resumable.
- The crawl output matches the format in `references/crawl-output-format.md`.
- If the source site requires authentication to access, ask the user for credentials.
- Don't migrate tracking scripts, analytics, or third-party widget code.
- If `vanjaro migrate --help` errors at startup (stale venv), run `pip install -e ".[dev]"` before continuing. Don't paper over missing deps with a custom script.
</constraints>
