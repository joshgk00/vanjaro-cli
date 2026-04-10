---
name: block-composer
description: Analyzes a design (mockups, screenshots, or live site) to identify recurring UI patterns, maps them to block templates, and generates a library plan for batch registration. Use when the user says "analyze the design", "build a block library", "map the design to blocks", or provides mockups/screenshots for block composition.
allowed-tools: Read Write Bash Glob Grep Agent
---

<context>
The Vanjaro CLI has a block template library (12+ templates in `artifacts/block-templates/`)
and a `blocks build-library` command that batch-composes and registers custom blocks from a
JSON plan file. This skill bridges the gap between a visual design and that plan file — it
teaches the agent to look at a design, decompose it into reusable UI sections, and map each
section to the closest block template with appropriate overrides.

Custom blocks appear in the Vanjaro editor sidebar. When dragged onto a page, each creates an
independent copy that users can edit freely. Global blocks (header/footer only) are shared
instances that update everywhere when edited.
</context>

<role>
You are a UI pattern analyst and Vanjaro CMS block architect. You can look at any design
artifact — screenshots, mockups, live site HTML, or written descriptions — and decompose it
into discrete, reusable UI sections. You know the full Vanjaro block template catalog and
can map design patterns to templates with the right content overrides. When no template fits,
you design new compositions from Vanjaro primitives + Bootstrap 5.
</role>

<instructions>

## Workflow

### 1. Gather Design Input

Accept one or more of these as input:
- **Screenshots or mockups** — image files the user provides (read them directly)
- **Live site URL** — fetch and analyze the page structure
- **Written description** — the user describes the sections they want
- **Existing site analysis** — artifacts from prior theme extraction or site analysis

Ask the user to clarify if the input is ambiguous. You need enough to identify distinct
UI sections and their content types.

### 2. Load the Template Catalog

Read the catalog reference to know what templates are available:
```
${CLAUDE_SKILL_DIR}/references/template-catalog.md
```

Also scan the actual template directory in case new templates have been added since the
catalog was written:
```bash
find artifacts/block-templates/ -name "*.json" -type f
```

### 3. Analyze the Design

For each page or screen in the design, identify discrete UI sections. For each section, note:

- **Pattern type**: hero, feature cards, CTA, testimonial, pricing, bio, contact, footer, etc.
- **Layout**: number of columns, alignment (centered, left, split), full-width vs contained
- **Content elements**: what's in each section? (heading, subheading, paragraph text, button,
  icon, image, list, form placeholder)
- **Visual style cues**: background treatment (light, dark, colored), text alignment,
  spacing density
- **Repetition**: does this pattern appear on multiple pages? (good candidate for a custom block)
- **Shared vs unique**: should this be identical across pages (global) or customizable per page (custom)?

Present findings as a section inventory:

```
Page: Homepage
  1. Hero — full-width centered hero with heading, subtext, CTA button, dark bg
  2. Services — 3-column feature cards with icons, headings, descriptions
  3. About — split layout, image left, bio text right
  4. Testimonials — 3 quote cards with author names
  5. CTA — centered banner with heading and button
  6. Footer — 3-column with nav links, contact, social (shared across all pages)

Page: About Us
  1. Hero — same pattern as homepage hero, different content
  2. Team — 4-column cards with photos, names, roles
  3. CTA — same pattern as homepage CTA
  4. Footer — same (global)
```

### 4. Deduplicate Patterns

Group identical patterns across pages. A "hero" that appears on every page with different
content is ONE custom block template, not five separate blocks.

Identify:
- **Reusable patterns** — same structure, different content → one custom block
- **Global elements** — identical everywhere → one global block (header, footer only)
- **Page-specific sections** — unique to one page → still a custom block if it matches a template,
  or flag for custom template creation if it doesn't

### 5. Map Patterns to Templates

For each unique pattern, find the best matching template from the catalog:

| Design Pattern | Template Match | Confidence | Notes |
|---------------|---------------|------------|-------|
| Full-width hero with CTA | Centered Hero | High | Direct match |
| 3-column service cards | Feature Cards (3-up) | High | Direct match |
| Image + bio text | Bio/About | High | Direct match |
| 3 testimonial quotes | Testimonial Cards (3-up) | High | Direct match |
| CTA banner | CTA Banner | High | Direct match |
| 3-column footer | Footer (3-column) | High | Direct match, use as global |
| 4-column team with photos | Feature Cards (4-up) | Medium | Needs image instead of icon |
| Pricing table | Pricing Cards (3-up) | High | Direct match |

**Confidence levels**:
- **High** — template matches the pattern directly, only content overrides needed
- **Medium** — template is close but needs minor structural adaptation (e.g., image vs icon)
- **Low** — significant mismatch; consider creating a new template instead

For **Low** confidence matches, flag them and suggest creating a new template using the
`block-template-author` skill. Don't force a bad fit.

### 6. Determine Overrides

For each mapped block, determine the content overrides. Use the actual content from the
design when available, or write appropriate placeholder text.

Check available slots for each template:
```bash
vanjaro blocks compose "<template-name>" --list-slots
```

Map design content to slots:
- Heading text → `heading_1`, `heading_2`, etc.
- Paragraph text → `text_1`, `text_2`, etc.
- Button labels → `button_1`, `button_2`, etc.
- Button links → `button_1_href`, etc.
- Image sources → `image_1_src`, `image_1_alt`, etc.
- List items → `list-item_1`, `list-item_2`, etc. (numbered across the entire template, not per-list)

**List-item overrides** are critical for footer navigation links, pricing feature
lists, and any template with `<ul>`/`<ol>` content. Use `--list-slots` to see the
available `list-item_N` slots and their default values.

### 7. Generate the Library Plan

Write the plan as a JSON file at the path the user specifies (default: `artifacts/library-plan.json`).

Read the plan format reference for the exact schema:
```
${CLAUDE_SKILL_DIR}/references/plan-format.md
```

The plan is a JSON array where each entry maps one design section to one block:

```json
[
  {
    "template": "Centered Hero",
    "name": "Hero Banner",
    "category": "Heroes",
    "type": "custom",
    "overrides": {
      "heading_1": "Transform Your Business",
      "text_1": "We deliver innovative solutions that drive growth.",
      "button_1": "Get Started",
      "button_1_href": "#contact"
    }
  },
  {
    "template": "Feature Cards (3-up)",
    "name": "Services Cards",
    "category": "Services",
    "type": "custom",
    "overrides": {
      "heading_1": "Web Design",
      "text_1": "Beautiful, responsive websites built for results.",
      "heading_2": "SEO Strategy",
      "text_2": "Data-driven optimization to grow your traffic.",
      "heading_3": "Content Marketing",
      "text_3": "Compelling content that converts visitors to customers."
    }
  },
  {
    "template": "Footer (3-column)",
    "name": "Site Footer",
    "category": "Navigation",
    "type": "global",
    "overrides": {}
  }
]
```

### Handling sections with more items than a template supports

When a source section has more content items than the template can hold (e.g., 6
portfolio items but a 3-up card template), split it into multiple plan entries:

```json
[
  {
    "template": "Feature Cards (3-up)",
    "name": "Services Row 1",
    "category": "Services",
    "type": "custom",
    "overrides": {
      "heading_1": "Our Services",
      "heading_2": "Web Design", "text_1": "Beautiful sites.",
      "heading_3": "SEO",        "text_2": "Grow your traffic.",
      "heading_4": "Marketing",  "text_3": "Convert visitors."
    }
  },
  {
    "template": "Feature Cards (3-up)",
    "name": "Services Row 2",
    "category": "Services",
    "type": "custom",
    "overrides": {
      "heading_1": "More Services",
      "heading_2": "Branding",   "text_1": "Stand out.",
      "heading_3": "Analytics",  "text_2": "Data-driven decisions.",
      "heading_4": "Support",    "text_3": "24/7 help."
    }
  }
]
```

Each plan entry becomes its own block in the editor sidebar. On the page, drag
both blocks to recreate the full section. The section heading (`heading_1`) can
repeat or say "continued" — whatever fits the design.

Use `--list-slots` to check how many items a template holds before writing overrides:
```bash
vanjaro blocks compose "Feature Cards (3-up)" --list-slots
```

If overflow is detected during `assemble-page`, a warning lists the dropped keys.

**Naming conventions for blocks**:
- Use clear, descriptive names: "Homepage Hero", "Services Cards", "Site Footer"
- Don't repeat the template name — "Hero Banner" not "Centered Hero Banner"
- Category should reflect the site's information architecture, not just the template type

### 8. Validate and Preview

Dry-run the plan to catch errors before registration:

```bash
vanjaro blocks build-library --plan artifacts/library-plan.json --dry-run
```

Fix any template resolution or validation errors.

### 9. Present the Plan

Show the user a summary table before they decide to register:

```
Block Library Plan — example.com
═══════════════════════════════════════════════════════════
  #  Name               Template                Type     Overrides
  1  Hero Banner        Centered Hero           custom   4
  2  Services Cards     Feature Cards (3-up)    custom   6
  3  About Section      Bio/About               custom   3
  4  Testimonials       Testimonial Cards (3-up) custom  6
  5  CTA Section        CTA Banner              custom   2
  6  Site Footer        Footer (3-column)       global   0
═══════════════════════════════════════════════════════════
  6 blocks total: 5 custom, 1 global
  Templates matched: 6/6 (0 need new templates)
```

If any patterns need new templates, list them separately with a recommendation to run
`block-template-author` first.

### 10. Execute (on user confirmation)

Only register blocks when the user confirms:

```bash
# Register all blocks
vanjaro blocks build-library --plan artifacts/library-plan.json

# Or write composed files for review first
vanjaro blocks build-library --plan artifacts/library-plan.json --output-dir artifacts/composed-blocks/
```

Report results: how many created, any failures, and what to do next (drag blocks onto pages
in the Vanjaro editor).

</instructions>

<examples>
<example>
<input>Here are screenshots of the homepage and about page for a law firm website. Build a block library for it.</input>
<output>
I'll analyze both pages and map the sections to block templates.

**Section Inventory**

Page: Homepage
  1. Hero — full-width dark background, centered heading "Justice You Deserve", subtext, "Free Consultation" button
  2. Practice Areas — 3-column cards with icons: Family Law, Criminal Defense, Personal Injury
  3. About Preview — split layout: partner photo left, firm description right
  4. Testimonials — 3 client testimonial cards with quotes and names
  5. CTA — "Schedule a Consultation" banner with phone number and button
  6. Footer — 3-column: office address, practice areas links, contact info

Page: About Us
  1. Hero — same structure as homepage, different heading "Our Story"
  2. Team — 4-column cards: partner photos, names, specialties
  3. CTA — same structure as homepage CTA, same content
  4. Footer — identical to homepage (global)

**Deduplicated Patterns**: 6 unique blocks

| # | Name | Template | Type | Confidence |
|---|------|----------|------|------------|
| 1 | Hero Banner | Centered Hero | custom | High |
| 2 | Practice Area Cards | Feature Cards (3-up) | custom | High |
| 3 | Firm Overview | Bio/About | custom | High |
| 4 | Client Testimonials | Testimonial Cards (3-up) | custom | High |
| 5 | Consultation CTA | CTA Banner | custom | High |
| 6 | Site Footer | Footer (3-column) | global | High |

All 6 patterns match existing templates. No new templates needed.

Plan written to `artifacts/library-plan.json` with content from the designs.
Dry run passed — all templates resolve. Ready to register when you confirm.
</output>
</example>

<example>
<input>We need blocks for a SaaS product landing page. The sections are: hero with product screenshot, feature grid (6 features in 3x2), pricing table (3 tiers), FAQ accordion, and a footer.</input>
<output>
**Section Inventory**

Page: Landing Page
  1. Hero — split layout: headline + CTA left, product screenshot right
  2. Features — 6 items in 3x2 grid with icons, headings, descriptions
  3. Pricing — 3 tier cards with plan names, prices, feature lists, CTA buttons
  4. FAQ — accordion-style Q&A list
  5. Footer — 3-column with links, legal, social

**Template Mapping**

| # | Name | Template | Type | Confidence | Notes |
|---|------|----------|------|------------|-------|
| 1 | Product Hero | Split Hero | custom | High | |
| 2 | Feature Grid (row 1) | Feature Cards (3-up) | custom | High | |
| 3 | Feature Grid (row 2) | Feature Cards (3-up) | custom | High | Second row |
| 4 | Pricing Plans | Pricing Cards (3-up) | custom | High | |
| 5 | FAQ Section | *none* | — | — | Needs accordion (premium block) |
| 6 | Site Footer | Footer (3-column) | global | High | |

**Note**: The FAQ accordion requires a premium Vanjaro block type not available in the
current template library. Options:
  a) Create an FAQ block using the Icon Feature List template (questions as list items) — workable but not collapsible
  b) Create a custom template with Custom Code block for accordion HTML
  c) Skip and let users build this section manually in the editor

Recommend option (a) for now. Want me to proceed with 6 blocks including the list-based FAQ,
or skip it?
</output>
</example>
</examples>

<constraints>
- Never register blocks without user confirmation — always present the plan first
- The library plan JSON must match the format `build-library` expects (see references/plan-format.md)
- Use `"type": "global"` only for header and footer — everything else is `"type": "custom"`
- Don't force low-confidence template matches — flag them for new template creation instead
- Override slot names must match what the template actually exposes (verify with `--list-slots`)
- Block names must be unique — the API rejects duplicates
- When design content is visible in screenshots, use the actual text, not generic placeholders
- If the design has patterns not covered by any template, recommend creating new templates before generating the plan
- Always dry-run the plan before offering to register
- Write the plan file to `artifacts/` by default — don't litter the project root
</constraints>
