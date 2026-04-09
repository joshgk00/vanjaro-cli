---
name: site-migrator
description: Crawls a live source website, extracts content, assets, navigation, and design tokens, then migrates everything to a Vanjaro site using the CLI. Use when the user says "migrate this site", "rebuild this site in Vanjaro", "move this site to Vanjaro", or provides a live URL to replicate.
allowed-tools: Read Write Bash Glob Grep Agent WebFetch
---

<context>
The Vanjaro CLI can build a complete site from design artifacts — theme controls, block
templates, page content, and assets. This skill adds the missing "Stage 0": crawling a
live source website to extract those artifacts automatically.

The pipeline becomes:
```
Source Site (live URL)
  → Crawl & extract (this skill)
  → Theme application (site-builder Stage 2)
  → Block library creation (site-builder Stage 3)
  → Page creation & content (site-builder Stage 4)
  → Live Vanjaro site
```

All crawl output goes to `artifacts/migration/{site-slug}/` as structured JSON files
that feed directly into the existing skills and CLI commands.
</context>

<role>
You are a website migration specialist who crawls source sites, extracts their structure
and content, and orchestrates the rebuild on Vanjaro CMS. You produce clean, structured
migration artifacts and coordinate with the site-builder pipeline for execution. You
understand that content fidelity matters — the migrated site should have the same text,
images, navigation, and visual feel as the source.
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

## Overview

The migration has 6 stages:

```
┌─────────────────────────────────────────────────────────┐
│  STAGE 1: CRAWL SOURCE SITE                             │
│  Fetch pages → extract structure → download assets      │
│  Gate: site-inventory.json complete, all assets saved   │
├─────────────────────────────────────────────────────────┤
│  STAGE 2: ANALYZE & PLAN                                │
│  Design tokens → block patterns → library plan          │
│  Gate: design-tokens.json + library-plan.json ready     │
├─────────────────────────────────────────────────────────┤
│  STAGE 3: SET UP VANJARO TARGET                         │
│  Auth → branding → theme → upload assets → register     │
│  Gate: theme applied, assets uploaded, blocks registered │
├─────────────────────────────────────────────────────────┤
│  STAGE 4: CREATE PAGES                                  │
│  Page hierarchy → shells → SEO metadata                 │
│  Gate: all pages created with correct hierarchy         │
├─────────────────────────────────────────────────────────┤
│  STAGE 5: MIGRATE CONTENT                               │
│  Assemble content → rewrite URLs → push → publish       │
│  Gate: all pages populated with source content          │
├─────────────────────────────────────────────────────────┤
│  STAGE 6: VERIFY                                        │
│  Page-by-page comparison → fix gaps → final publish     │
│  Gate: user confirms migration is acceptable            │
└─────────────────────────────────────────────────────────┘
```

## Stage 1: Crawl Source Site

### 1.1 Discover Pages

Start from the source URL. Identify all pages to migrate:

- **Fetch the homepage** and extract the navigation menu to find top-level pages
- **Follow nav links** one level deep to find subpages
- **Check the sitemap** at `/sitemap.xml` if available for additional pages
- **Ask the user** to confirm the page list — they may want to exclude some pages

Don't crawl infinitely. Stick to pages the user wants migrated. Blog archives, search
results, and login pages are usually excluded.

### 1.2 Extract Page Content

For each page, fetch the HTML and extract:

**Structure — identify sections top to bottom:**
- What UI pattern is each section? (hero, cards, CTA, testimonials, etc.)
- How many columns? What's the layout?
- What content types are in each section? (headings, text, images, buttons, lists)

**Text content — pull out the actual copy:**
- Headings (preserve hierarchy: h1, h2, h3)
- Paragraph text (preserve line breaks and formatting)
- Button labels and link targets
- List items
- Any structured data (prices, dates, addresses, phone numbers)

**Images — identify all visual assets:**
- Hero/background images
- Content images (photos, illustrations)
- Icons (note: Vanjaro has built-in icon blocks — may not need to migrate icon images)
- Logo

Save per-section content to `artifacts/migration/{site-slug}/pages/{page-slug}/section-{n}-{type}.json`.

### 1.3 Extract Global Elements

Identify elements shared across all pages:

- **Header**: logo, navigation items, any top bar content
- **Footer**: column content, links, copyright text, social links
- **Sidebar**: if the source site has a persistent sidebar

Save to `artifacts/migration/{site-slug}/global/header.json` and `footer.json`.

### 1.4 Download Assets

Download all images and media referenced in the extracted content:

```bash
# Create assets directory
mkdir -p artifacts/migration/{site-slug}/assets

# Download each image (use curl or wget)
curl -L -o artifacts/migration/{site-slug}/assets/hero-bg.jpg "https://source.com/images/hero-bg.jpg"
```

Build the asset manifest at `artifacts/migration/{site-slug}/assets/manifest.json`.
Track: source URL, local file path, filename, size, content type, upload status.

**Skip these:**
- Tracking pixels and analytics images
- SVG icons that can be replaced with Vanjaro icon blocks
- Favicons (Vanjaro manages its own)
- Images from third-party widgets (chat, social embeds)

### 1.5 Extract Design Tokens

Analyze the source site's visual design. You can:

- **Read computed styles** from the fetched HTML/CSS
- **Inspect the stylesheet** linked in the `<head>`
- **Use screenshots** if CSS isn't accessible (e.g., JavaScript-rendered sites)

Extract into the standard design tokens format:
- Colors (primary, secondary, tertiary, light, dark)
- Fonts (families, weights, sizes)
- Spacing (border radius, button padding)
- Menu styling

Save to `artifacts/migration/{site-slug}/design-tokens.json`.

Follow the `theme-extract-tokens` skill format (documented in `skills/theme-extract-tokens.md`).

### 1.6 Stage 1 Gate

Write the master inventory to `artifacts/migration/{site-slug}/site-inventory.json`.

Report to the user:
```
Stage 1: Source Site Crawled ✓
  Source: https://example.com
  Pages found: 5 (Home, About, Services, Blog, Contact)
  Sections extracted: 22 total across all pages
  Images downloaded: 24 files (3.2 MB)
  Global elements: header + footer
  Design tokens: extracted (5 colors, 2 fonts)

  Review artifacts/migration/example-com/site-inventory.json
  Confirm pages to migrate before proceeding.
```

**Wait for user confirmation** before proceeding. They may want to adjust the page list
or exclude certain sections.

## Stage 2: Analyze & Plan

### 2.1 Map Patterns to Block Templates

Using the extracted section data, follow the `block-composer` skill workflow:

1. Review all sections across all pages
2. Deduplicate — same pattern on multiple pages = one custom block
3. Map each pattern to the closest block template from `artifacts/block-templates/`
4. For patterns that don't match, flag for new template creation

### 2.2 Generate Library Plan

Write `artifacts/migration/{site-slug}/library-plan.json` using the extracted content
as overrides. The overrides should contain the actual text from the source site, not
placeholders.

### 2.3 Identify New Templates Needed

If the source site has patterns not covered by the 12 existing templates, list them.
Common migration-specific patterns:
- Blog post cards (different from feature cards — may have dates, categories)
- Team member grid (photos + names + roles)
- Logo bar / partner logos
- Accordion FAQ
- Tab panels
- Sidebar layouts

For each, recommend whether to:
a) Adapt an existing template (medium confidence match)
b) Create a new template with `block-template-author`
c) Use Custom Code blocks for complex interactive patterns

### 2.4 Stage 2 Gate

```
Stage 2: Analysis Complete ✓
  Unique patterns found: 8
  Matched to existing templates: 6/8
  New templates needed: 2 (Blog Post Card, Team Grid)
  Library plan: artifacts/migration/example-com/library-plan.json

  Creating 2 new templates before proceeding...
```

Create any needed templates, then move on.

## Stage 3: Set Up Vanjaro Target

This maps to site-builder Stages 1-3. Verify Vanjaro prerequisites, then:

### 3.1 Foundation

```bash
vanjaro auth status --json
vanjaro api-key status --json
vanjaro site health --json
vanjaro branding update --site-name "Site Name" --footer-text "Copyright..."
```

### 3.2 Apply Theme

Using the design tokens extracted in Stage 1:

1. Register custom fonts
2. Apply colors, site globals, heading typography, paragraph typography, button styling, menu, links
3. Apply custom CSS for anything beyond theme controls

Follow `skills/theme-apply.md` for the exact order and commands.

### 3.3 Upload Assets

Upload all downloaded images to Vanjaro's asset library:

```bash
# Upload each asset
vanjaro assets upload "artifacts/migration/{site-slug}/assets/hero-bg.jpg" --folder "Images/" --json
```

**Update the asset manifest** with the Vanjaro URL and file ID returned from each upload.
This mapping is critical — content assembly in Stage 5 uses it to rewrite image URLs.

### 3.4 Register Block Library

```bash
# Dry run first
vanjaro blocks build-library --plan artifacts/migration/{site-slug}/library-plan.json --dry-run

# Register
vanjaro blocks build-library --plan artifacts/migration/{site-slug}/library-plan.json
```

### 3.5 Stage 3 Gate

```bash
vanjaro theme get --modified --json | jq '.total'
vanjaro custom-blocks list --json
vanjaro assets list --json
```

```
Stage 3: Vanjaro Target Ready ✓
  Theme controls: 108 modified
  Assets uploaded: 24/24
  Custom blocks: 8 registered
  Global blocks: 0 (created in Stage 5)
```

## Stage 4: Create Pages

### 4.1 Build Page Hierarchy

Create pages in order — parents before children:

```bash
vanjaro pages create --title "Home" --name "home" --json
vanjaro pages create --title "About" --name "about" --json
vanjaro pages create --title "Services" --name "services" --json
vanjaro pages create --title "Services" --name "consulting" --parent SERVICES_ID --json
```

Build the **page URL map** — source URLs to new Vanjaro page paths. Save it to
`artifacts/migration/{site-slug}/page-url-map.json`:

```json
{
  "https://example.com/": {"page_id": 35, "path": "/"},
  "https://example.com/about": {"page_id": 36, "path": "/about"},
  "https://example.com/services": {"page_id": 37, "path": "/services"}
}
```

### 4.2 Audit Shells

```bash
vanjaro pages shell PAGE_ID --fix --json
```

### 4.3 Set SEO Metadata

Transfer SEO data from the source site to each Vanjaro page:

```bash
vanjaro pages seo-update PAGE_ID \
  --title "Source Page Title" \
  --description "Source meta description" \
  --keywords "source, keywords"
```

### 4.4 Stage 4 Gate

```bash
vanjaro pages list --json
vanjaro site nav --json
```

```
Stage 4: Pages Created ✓
  Pages: 5 created (matching source site hierarchy)
  SEO: transferred for all pages
  Page URL map: saved for content rewriting
```

## Stage 5: Migrate Content

### 5.1 Assemble Page Content

For each page, combine the per-section content files into a full page component tree:

1. **Read each section file** from `pages/{slug}/section-{n}-{type}.json`
2. **Compose from templates** using `blocks compose` with the extracted content as overrides
3. **Rewrite image URLs** — replace source URLs with Vanjaro asset URLs from the manifest
4. **Rewrite internal links** — replace source URLs with Vanjaro page paths from the URL map
5. **Merge sections** into a single page JSON with `"components": [...]` and `"styles": []`

See `${CLAUDE_SKILL_DIR}/references/url-rewriting.md` for rewriting rules.

### 5.2 Push Content

For each page:

```bash
# Snapshot current state (empty page)
vanjaro content snapshot PAGE_ID

# Push migrated content as draft
vanjaro content update PAGE_ID --file page-content.json

# Verify structure
vanjaro blocks tree PAGE_ID
```

### 5.3 Set Up Global Blocks

Assemble and register header and footer:

```bash
# Compose footer from template + extracted content
vanjaro blocks compose "Footer (3-column)" \
  --set heading_1="Quick Links" --set heading_2="Contact" --set heading_3="Follow Us" \
  --output footer.json

vanjaro global-blocks create --name "Site Footer" --category "Navigation" --file footer.json
vanjaro global-blocks publish FOOTER_GUID
```

For headers, Vanjaro's built-in menu block typically handles navigation. The header
global block may just need a logo and branding adjustments.

### 5.4 Publish Pages

```bash
# Review before publishing
vanjaro content diff PAGE_ID

# Publish each page
vanjaro content publish PAGE_ID
```

### 5.5 Stage 5 Gate

```
Stage 5: Content Migrated ✓
  Pages populated: 5/5
  Images rewritten: 24 references updated
  Internal links rewritten: 18 references updated
  Global blocks: header + footer published
  All pages published
```

## Stage 6: Verify

### 6.1 Page-by-Page Review

For each migrated page, check:
- **Text accuracy** — all headings, paragraphs, and button labels match the source
- **Image display** — all images load from Vanjaro asset library
- **Links work** — internal links point to correct Vanjaro pages
- **Layout matches** — section structure and column layout match the source
- **Theme accuracy** — colors, fonts, spacing match the source design

### 6.2 Report Gaps

Not everything migrates perfectly. Common gaps to report:

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
2. Apply the fix
3. Verify
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

Known gaps:
  - Contact form needs DNN module setup
  - Blog page is static snapshot (no dynamic posts)

Artifacts:
  artifacts/migration/example-com/
    site-inventory.json      — master manifest
    design-tokens.json       — extracted theme data
    library-plan.json        — block composition plan
    page-url-map.json        — source → target URL mapping
    assets/manifest.json     — image upload mapping
    pages/                   — per-page section content
    global/                  — header/footer content
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

</instructions>

<examples>
<example>
<input>Migrate https://example-coaching.com to our Vanjaro site at http://coaching.local</input>
<output>
Starting migration from https://example-coaching.com.

**Stage 1: Crawling source site...**

Fetched 5 pages from the navigation:
  1. Home — hero, about preview, services cards, testimonials, CTA
  2. About — hero, bio section, team cards, values list
  3. Services — hero, 3 service detail sections, pricing cards
  4. Testimonials — hero, 6 testimonial cards
  5. Contact — hero, contact form, map embed, office hours

Downloading 18 images... done (2.1 MB)

Extracted design tokens:
  - Primary: #E8785D (coral), Secondary: #2D4A3E (forest green)
  - Fonts: Playfair Display (headings), Inter (body)
  - Border radius: 8px, Buttons: pill style (30px radius)

Artifacts written to artifacts/migration/example-coaching-com/

Please review the page list. Any pages to exclude before I proceed?
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
- Auth: active
- Theme: 0 controls modified (not yet applied)
- Blocks: none registered
- Pages: none created

Starting at Stage 3: Set Up Vanjaro Target...
</output>
</example>
</examples>

<constraints>
- Always crawl responsibly — respect robots.txt, don't hammer the source with rapid requests
- Download assets to local disk before uploading to Vanjaro — don't hotlink source URLs
- Wait for user confirmation after Stage 1 (page list) and before Stage 5 publishing
- Never overwrite existing Vanjaro content without snapshotting first
- Rewrite ALL image URLs to Vanjaro asset paths — no references to the source site should remain
- Rewrite ALL internal links to Vanjaro page paths
- Leave external links unchanged
- Report gaps honestly — don't claim interactive elements migrated if they didn't
- Keep all migration artifacts in `artifacts/migration/{site-slug}/` — organized and resumable
- The crawl output must match the format in references/crawl-output-format.md
- If the source site requires authentication to access, ask the user for credentials
- Don't migrate tracking scripts, analytics, or third-party widget code
- Images that fail to download should be logged in the manifest with an error, not silently skipped
</constraints>
