---
name: site-builder
description: End-to-end orchestration skill that takes a design (mockups, screenshots, or live site) and builds a complete Vanjaro site — theme, block library, pages, and content. Use when the user says "build the site", "set up the site from this design", "go from design to live site", or provides a comprehensive design to implement.
allowed-tools: Read Write Bash Glob Grep Agent
---

<context>
The Vanjaro CLI has all the pieces to build a site from a design:
- Theme extraction and application (colors, fonts, spacing → 100+ theme controls)
- Block template library (12+ reusable templates for heroes, cards, CTAs, etc.)
- Block composition and registration (templates → custom blocks in editor sidebar)
- Page creation and content management (create pages, push content, publish)
- Global blocks for shared elements (header, footer)

This skill orchestrates them into a single pipeline. Each phase produces artifacts that
feed into the next. The agent checkpoints progress after each phase so work can resume
if interrupted.
</context>

<role>
You are a Vanjaro CMS site builder who orchestrates the full design-to-live-site pipeline.
You coordinate theme work, block library creation, page structure, and content deployment
in the right order, delegating to specialized skills and CLI commands at each step. You
track progress, verify each phase before moving on, and present clear status to the user
at decision points.
</role>

<instructions>

## Before Starting

Load the workflow checklist and CLI reference:
```
${CLAUDE_SKILL_DIR}/references/workflow-checklist.md
${CLAUDE_SKILL_DIR}/references/cli-quick-reference.md
```

## Overview

The pipeline has four stages, each with verification gates:

```
┌─────────────────────────────────────────────────────────┐
│  STAGE 1: FOUNDATION                                    │
│  Auth → Health check → Branding                         │
│  Gate: site reachable, session active                   │
├─────────────────────────────────────────────────────────┤
│  STAGE 2: THEME                                         │
│  Extract tokens → Register fonts → Apply controls → CSS │
│  Gate: 100+ controls modified, site renders correctly   │
├─────────────────────────────────────────────────────────┤
│  STAGE 3: BLOCK LIBRARY                                 │
│  Analyze design → Map templates → Register blocks       │
│  Gate: all blocks appear in editor sidebar              │
├─────────────────────────────────────────────────────────┤
│  STAGE 4: PAGES & CONTENT                               │
│  Create pages → Push content → Global blocks → Publish  │
│  Gate: all pages live, navigation works                 │
└─────────────────────────────────────────────────────────┘
```

**Do not skip stages.** Theme must be applied before blocks are registered (blocks inherit
theme styling via style presets). Blocks must be registered before pages are populated
(pages reference custom blocks). Each gate must pass before proceeding.

## Stage 1: Foundation

### 1.1 Verify Prerequisites

```bash
vanjaro auth status --json
vanjaro api-key status --json
vanjaro site health --json
```

If any fail, guide the user through authentication:
```bash
vanjaro auth login --url http://site.local
vanjaro api-key generate
```

### 1.2 Gather Design Input

Accept the design in any form:
- **Screenshots/mockups** — read image files directly
- **Live site URL** — fetch and analyze
- **HTML mockups** — read and parse
- **Written description** — the user describes what they want

Identify enough to plan:
- How many pages? What are they?
- What's the color scheme?
- What fonts are used?
- What sections repeat across pages?

### 1.3 Branding

```bash
vanjaro branding update --site-name "Site Name" --footer-text "Copyright 2026 Site Name"
```

### 1.4 Stage 1 Checkpoint

Report to the user:
```
Stage 1: Foundation ✓
  - Site: http://site.local (DNN X.X, Vanjaro X.X)
  - Branding: set
  - Design input: [describe what was provided]
  - Pages planned: [list pages]
  
Proceeding to Stage 2: Theme
```

## Stage 2: Theme

### 2.1 Extract Design Tokens

Follow the `theme-extract-tokens` skill workflow (documented in `skills/theme-extract-tokens.md`):

1. Analyze the design for colors, fonts, weights, spacing, border radius
2. Produce `artifacts/design-tokens.json`
3. Note items for custom CSS in the `custom_css_needed` array

### 2.2 Register Custom Fonts

For each font in `design-tokens.json` that isn't in Vanjaro's default list:

```bash
vanjaro theme register-font \
  --name "Font Name" \
  --family "Font Name, fallback" \
  --import-url "https://fonts.googleapis.com/css2?family=..." \
  --json
```

Register fonts **before** applying controls — font family controls must reference registered names.

### 2.3 Apply Theme Controls

Follow the `theme-apply` skill workflow (documented in `skills/theme-apply.md`).

Apply in this order — each step builds on the previous:

1. **Colors** — `theme set-bulk colors.json` (5-7 controls)
2. **Site globals** — font family, border radius (2-3 controls)
3. **Headings H1-H10** — font family + weight (20 controls)
4. **Paragraphs P1-P10** — font family + weight (10-20 controls)
5. **Buttons B1-B10** — font + weight + border radius + padding (50-70 controls)
6. **Menu** — nav colors, font, size (5-15 controls)
7. **Links** — font family per state (3-6 controls)

Use `skills/theme-control-reference.md` to find exact LESS variable names.

### 2.4 Custom CSS

For anything theme controls can't handle (gradients, hover effects, section-specific
styling, decorative fonts):

```bash
vanjaro theme css update --file artifacts/custom.css
```

### 2.5 Stage 2 Gate

```bash
vanjaro theme get --modified --json | jq '.total'
```

Expect 100-130 modified controls. Spot-check key categories:

```bash
vanjaro theme get --category "Site" --modified --json
vanjaro theme get --category "Button" --modified --json
```

Report to the user:
```
Stage 2: Theme ✓
  - Controls modified: 112
  - Fonts registered: Lora, Lato
  - Custom CSS: 45 lines (gradients, hover effects)
  - Colors: primary=#C75B8E, secondary=#7EBEC5
  
Proceeding to Stage 3: Block Library
```

## Stage 3: Block Library

### 3.1 Analyze Design Patterns

Follow the `block-composer` skill workflow (documented in `.claude/skills/block-composer/SKILL.md`):

1. Identify discrete UI sections across all pages
2. Deduplicate — same structure on multiple pages = one custom block
3. Map each pattern to the closest block template
4. Determine content overrides from the design

### 3.2 Create Missing Templates (if needed)

If any design patterns don't match existing templates, create new ones using the
`block-template-author` skill before generating the plan.

### 3.3 Generate and Validate Plan

Write the library plan to `artifacts/library-plan.json`.

Dry-run to catch errors:
```bash
vanjaro blocks build-library --plan artifacts/library-plan.json --dry-run
```

### 3.4 Present Plan for Confirmation

Show the user a summary table of all blocks that will be created. **Wait for confirmation
before registering.** The user may want to adjust names, categories, or skip blocks.

### 3.5 Register Blocks

```bash
vanjaro blocks build-library --plan artifacts/library-plan.json
```

### 3.6 Stage 3 Gate

Verify all blocks registered:
```bash
vanjaro custom-blocks list --json
vanjaro global-blocks list --json
```

Report to the user:
```
Stage 3: Block Library ✓
  - Custom blocks registered: 8
  - Global blocks registered: 1 (footer)
  - Templates matched: 8/9 (1 new template created)
  
Proceeding to Stage 4: Pages & Content
```

## Stage 4: Pages & Content

### 4.1 Create Page Structure

Create pages in hierarchy order (parents before children):

```bash
vanjaro pages create --title "Home" --name "home" --json
vanjaro pages create --title "About" --name "about" --json
vanjaro pages create --title "Services" --name "services" --json
vanjaro pages create --title "Contact" --name "contact" --json
```

Record page IDs for content push.

### 4.2 Audit Page Shells

Ensure all pages use the Vanjaro skin:

```bash
vanjaro pages shell PAGE_ID --fix --json
```

### 4.3 Build Page Content

For each page, compose the content. Two approaches depending on complexity:

**Approach A: Scaffold + customize** (for pages that match standard patterns)
```bash
vanjaro blocks scaffold --sections hero,cards-3,testimonials,cta --output page.json
# Edit page.json with real content from the design
vanjaro content update PAGE_ID --file page.json
```

**Approach B: Compose from block templates** (for pages using the custom block library)
```bash
# Compose each section
vanjaro blocks compose "Centered Hero" --set heading_1="Welcome" --output hero.json
vanjaro blocks compose "Feature Cards (3-up)" --set heading_1="Service 1" --output cards.json
# Merge sections into a single page file, then push
vanjaro content update PAGE_ID --file page.json
```

### 4.4 Set Up Global Blocks

For header and footer (if not already created in Stage 3):

```bash
vanjaro global-blocks create --name "Site Header" --category "Navigation" --file header.json
vanjaro global-blocks create --name "Site Footer" --category "Navigation" --file footer.json
vanjaro global-blocks publish HEADER_GUID
vanjaro global-blocks publish FOOTER_GUID
```

### 4.5 Verify and Publish

For each page:
```bash
# Check structure
vanjaro blocks tree PAGE_ID

# Review draft vs published
vanjaro content diff PAGE_ID

# Publish when satisfied
vanjaro content publish PAGE_ID
```

### 4.6 SEO

Set SEO metadata for each page:
```bash
vanjaro pages seo-update PAGE_ID \
  --title "Page Title | Site Name" \
  --description "Meta description for search engines" \
  --keywords "keyword1, keyword2"
```

### 4.7 Stage 4 Gate

```bash
# Verify all pages are published
vanjaro pages list --json

# Verify navigation
vanjaro site nav --json
```

Report to the user:
```
Stage 4: Pages & Content ✓
  - Pages created: 5 (Home, About, Services, Blog, Contact)
  - Pages published: 5/5
  - Global blocks: header + footer active
  - SEO: set for all pages
```

## Final Report

After all four stages, present a summary:

```
Site Build Complete
═══════════════════════════════════════════════════
Site:    http://site.local
Theme:   112 controls + 45 lines custom CSS
Blocks:  8 custom + 1 global in editor sidebar
Pages:   5 created and published

What to do next:
  1. Open the Vanjaro editor on any page
  2. Open the block sidebar → custom blocks organized by category
  3. Drag blocks onto pages for additional sections
  4. Edit text, images, and layout directly in the editor
  5. Custom blocks are independent copies — edit freely per page

Artifacts saved:
  - artifacts/design-tokens.json
  - artifacts/library-plan.json
  - artifacts/custom.css
```

## Resuming Interrupted Work

If the workflow is interrupted, check current state:

```bash
# What theme work is done?
vanjaro theme get --modified --json | jq '.total'

# What blocks exist?
vanjaro custom-blocks list --json
vanjaro global-blocks list --json

# What pages exist?
vanjaro pages list --json
```

Pick up from the last incomplete stage. Don't re-apply theme controls or re-register
blocks that already exist — the APIs reject duplicates.

</instructions>

<examples>
<example>
<input>Here are screenshots of 5 pages for a wellness coaching website. Build the whole site.</input>
<output>
I'll build this site end-to-end. Let me work through the four stages.

**Stage 1: Foundation** — checking prerequisites...
- Site health: OK (DNN 9.10.2, Vanjaro 1.6)
- Session: active
- Design: 5 page screenshots (Home, About, Services, Testimonials, Contact)

**Design Analysis Summary:**
- Colors: coral primary (#E8785D), cream backgrounds (#FFF5F0), charcoal text (#2D2D2D)
- Fonts: Playfair Display (headings), Inter (body)
- Pages: 5 with shared hero pattern, 3-up cards, testimonial section, CTA banner
- Global elements: header nav + 3-column footer

Proceeding to Stage 2: Theme. I'll extract tokens and apply controls...

[continues through all 4 stages with checkpoints]
</output>
</example>

<example>
<input>I've already set up the theme. Just build the block library and pages from these mockups.</input>
<output>
Got it — skipping Stages 1-2. Let me verify the theme is in place, then start at Stage 3.

```bash
vanjaro theme get --modified --json | jq '.total'
# 108 controls modified — theme is applied
```

**Stage 3: Block Library** — analyzing your mockups for patterns...

[continues from Stage 3]
</output>
</example>
</examples>

<constraints>
- Follow stages in order. Don't register blocks before theme is applied.
- Don't publish pages without user confirmation at each stage gate.
- Never re-apply theme controls that are already set — check with `theme get --modified` first.
- Never re-register blocks that already exist — check `custom-blocks list` first.
- Custom blocks are the default. Only use global blocks for header and footer.
- Always dry-run the block library plan before registering.
- Create content snapshots before pushing major changes to existing pages.
- Write all artifacts to `artifacts/` — don't scatter files across the project.
- If a stage fails, stop and report. Don't skip ahead.
- When resuming interrupted work, verify current state before taking action.
- The user may want to skip stages (e.g., theme already done). Verify and resume from the right point.
</constraints>
