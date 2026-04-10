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
  → vanjaro migrate crawl          (Stage 1 — fetch pages, extract sections,
                                     download assets, extract design tokens)
  → site-builder theme application (Stage 3.2)
  → vanjaro migrate build-id-map   (Stage 4 — match crawled pages to Vanjaro IDs)
  → vanjaro migrate assemble-page  (Stage 5.1 — merge section JSONs into page content)
  → vanjaro migrate rewrite-urls   (Stage 5.1 — rewrite image + link URLs)
  → vanjaro content update/publish (Stage 5.2 — push and publish)
  → vanjaro migrate verify-all     (Stage 6 — page-by-page verification)
```

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

If that errors with "Session expired", ask the user to run `vanjaro auth login`
themselves — it's interactive and cannot be driven from this session.

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
│  Auth → branding → theme → upload assets → register     │
│  Gate: theme applied, assets uploaded, blocks registered │
├─────────────────────────────────────────────────────────┤
│  STAGE 4: CREATE PAGES                                  │
│  Page hierarchy → shells → SEO → build-id-map           │
│  Gate: all pages created, page-id-map.json written      │
├─────────────────────────────────────────────────────────┤
│  STAGE 5: MIGRATE CONTENT                               │
│  assemble-page → rewrite-urls → content update/publish  │
│  Gate: all pages populated with source content          │
├─────────────────────────────────────────────────────────┤
│  STAGE 6: VERIFY                                        │
│  vanjaro migrate verify-all → fix gaps → final publish  │
│  Gate: user confirms migration is acceptable            │
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
- **Extracts design tokens** — writes `design-tokens.json` using the same format
  as `theme-extract-tokens`.
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
labels) as the overrides for each block so the final library contains real copy,
not placeholders.

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

### 3.2 Apply Theme

Using `design-tokens.json` from Stage 1:

1. Register custom fonts
2. Apply colors, site globals, heading typography, paragraph typography, button styling, menu, links
3. Apply custom CSS for anything beyond theme controls

Follow `.claude/skills/theme-apply/SKILL.md` for exact commands and order.

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

### 3.4 Register Block Library

```bash
# Dry run
vanjaro blocks build-library --plan artifacts/migration/example-com/library-plan.json --dry-run

# Register
vanjaro blocks build-library --plan artifacts/migration/example-com/library-plan.json
```

### 3.5 Stage 3 Gate

```bash
vanjaro theme get --modified --json | jq '.total'
vanjaro custom-blocks list --json
vanjaro assets list --json
```

## Stage 4: Create Pages

### 4.1 Build Page Hierarchy

Create pages in parent-before-child order, matching the source site's structure:

```bash
vanjaro pages create --title "Home" --name "home" --json
vanjaro pages create --title "About" --name "about" --json
vanjaro pages create --title "Services" --name "services" --json
```

### 4.2 Audit Shells

```bash
vanjaro pages shell PAGE_ID --fix --json
```

### 4.3 Set SEO Metadata

Transfer meta data from the source to each Vanjaro page. The crawler saved
`meta_description` and other SEO fields on each page entry in `site-inventory.json`.

```bash
vanjaro pages seo-update PAGE_ID \
  --title "Source Page Title" \
  --description "Source meta description" \
  --keywords "source, keywords"
```

### 4.4 Build the Page ID Map

Once all pages exist, generate the source-URL → Vanjaro-page-ID mapping that
Stages 5 and 6 need:

```bash
vanjaro migrate build-id-map \
  --inventory artifacts/migration/example-com/site-inventory.json \
  --output artifacts/migration/example-com/page-id-map.json \
  --json
```

The command matches inventory pages to Vanjaro pages by path, portal home,
title, and slug — in that order. Any unmatched pages are reported as warnings;
hand-edit the resulting JSON to fix them.

### 4.5 Stage 4 Gate

```bash
vanjaro pages list --json
vanjaro site nav --json
cat artifacts/migration/example-com/page-id-map.json  # verify every page matched
```

## Stage 5: Migrate Content

### 5.1 Assemble and Rewrite Each Page

For each page, two commands do the heavy lifting:

```bash
# 1. Merge the per-section files into a single page content JSON
vanjaro migrate assemble-page \
  --sections "artifacts/migration/example-com/pages/home/section-*.json" \
  --output artifacts/migration/example-com/pages/home/content.json \
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
`content.json` with `"components": [...]`.

`rewrite-urls` walks the resulting component tree and replaces:
- image `src` attributes → Vanjaro asset URLs from `assets/manifest.json`
- internal `href` attributes → Vanjaro page paths from `page-url-map.json`
- External links, anchors, `mailto:`, and `tel:` are left untouched.

### 5.2 Push and Publish

For each page:

```bash
# Snapshot the current state before overwriting
vanjaro content snapshot PAGE_ID

# Push as draft (does NOT publish yet)
vanjaro content update PAGE_ID --file artifacts/migration/example-com/pages/home/content.json

# Verify structure
vanjaro blocks tree PAGE_ID

# Review draft vs. published
vanjaro content diff PAGE_ID

# Publish
vanjaro content publish PAGE_ID
```

### 5.3 Set Up Global Blocks

Assemble and register header and footer using `vanjaro blocks compose`:

```bash
vanjaro blocks compose "Footer (3-column)" \
  --set heading_1="Quick Links" --set heading_2="Contact" --set heading_3="Follow Us" \
  --output artifacts/migration/example-com/global/footer-composed.json

vanjaro global-blocks create --name "Site Footer" --category "Navigation" \
  --file artifacts/migration/example-com/global/footer-composed.json
vanjaro global-blocks publish FOOTER_GUID
```

For headers, Vanjaro's built-in menu block typically handles navigation. The
header global block may just need a logo and branding adjustments.

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

`verify-all` checks, per page:
- **Text match** — paragraphs and headings against the source, scored against `--threshold`
- **Structure** — section counts and types
- **Images** — every source image URL is present in the migrated content (via the asset manifest)
- **Links** — internal links resolve to Vanjaro pages
- **Metadata** — title, description, keywords

For single-page verification use `vanjaro migrate verify` with
`--source-url`, `--page-id`, and optional `--header-block-name` /
`--footer-block-name` to also check global blocks.

### 6.2 Report Gaps

Review the verify report. Common gaps to expect:

| Gap | Why | Recommended Fix |
|-----|-----|-----------------|
| Interactive elements (accordions, tabs) | No Vanjaro primitive for these | Custom Code block or skip |
| Animations/transitions | CSS-only, not in theme controls | Add to custom CSS |
| Forms | Source form provider differs | Rebuild with DNN form module |
| Blog / dynamic content | Static migration only | Set up DNN blog module separately |
| Video embeds | Different embed format | Re-embed using Vanjaro video block |
| Maps | API key differs | Re-embed with new API key |

### 6.3 Fix Loop

For each gap the user wants fixed:
1. Identify the fix approach
2. Apply the fix (often re-running `assemble-page` + `rewrite-urls` + `content update`)
3. Re-run `vanjaro migrate verify` for that page
4. Move to the next gap

### 6.4 Final Report

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

Verify report: artifacts/migration/example-com/verify-report.json

Known gaps:
  - Contact form needs DNN module setup
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
    verify-report.json       — verification gap report
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
- Report gaps honestly — don't claim interactive elements migrated if they didn't.
- Keep all migration artifacts in `artifacts/migration/{site-slug}/` — organized and resumable.
- The crawl output matches the format in `references/crawl-output-format.md`.
- If the source site requires authentication to access, ask the user for credentials.
- Don't migrate tracking scripts, analytics, or third-party widget code.
- If `vanjaro migrate --help` errors at startup (stale venv), run `pip install -e ".[dev]"` before continuing. Don't paper over missing deps with a custom script.
</constraints>
