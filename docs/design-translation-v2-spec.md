# Design Translation v2 — Implementation Specification

**Status:** Proposed  
**Project:** `vanjaro-cli`  
**Primary outcome:** Convert live websites and Figma designs into accurate, maintainable Vanjaro sites while preferring native Vanjaro components and reusable agency-standard blocks over site-specific code.

## 1. Purpose

This specification defines the next generation of the Vanjaro design-translation pipeline. It covers the work required to:

1. Analyze either a live website or a Figma frame.
2. Preserve design structure, content relationships, responsive behavior, and visual styling in a common intermediate representation.
3. Select the best existing Vanjaro block templates using explicit capabilities and measurable confidence.
4. Produce deterministic block-library and page-composition plans.
5. Translate design differences through theme controls, Vanjaro/Bootstrap utilities, reusable modifiers, and scoped CSS in that order.
6. Measure content, structural, maintainability, responsive, and visual accuracy against a repeatable benchmark corpus.

The specification is intentionally divided into stable contracts and bounded work packages so implementation can be assigned to multiple agents without overlapping ownership.

## 2. Problem Statement

The existing pipeline reliably handles many operational migration concerns:

- Page discovery and hierarchy
- Content and asset extraction
- Asset upload and URL rewriting
- Page creation and content publication
- Global header/footer wrapping
- Theme palette mapping
- Content verification, structural audit, and screenshot capture

The remaining accuracy problem sits between source extraction and Vanjaro composition.

Today, source content is largely flattened into positional arrays such as `headings`, `paragraphs`, `images`, and `buttons`. Relationships that matter to design fidelity—such as which image belongs to which card, whether media is left or right, how items repeat, which elements overlap, and how a section changes on mobile—must be reconstructed later through heuristics. Figma support currently extracts tokens and assets but does not produce a complete page or block plan.

This causes four recurring costs:

1. New source-site builders require additional special cases in the extractor.
2. Template selection is a hard-coded classification rather than an explainable comparison of alternatives.
3. Responsive and decorative design details are discovered late during visual QA.
4. Successful manual fixes are not consistently promoted into reusable agency standards.

## 3. Goals

### 3.1 Functional goals

- Use one versioned design representation for live HTML and Figma sources.
- Preserve semantic grouping and layout relationships from extraction through composition.
- Make template selection deterministic, explainable, confidence-scored, and biased toward standard Vanjaro maintenance.
- Generate valid migration artifacts without requiring hand-authored positional overrides for supported patterns.
- Capture and translate meaningful responsive differences at desktop, tablet, and mobile breakpoints.
- Produce an actionable plan when a design cannot be represented accurately by existing blocks.
- Turn visual QA into a repeatable, section-level quality gate.
- Preserve all current migration capabilities and artifact resumability.

### 3.2 Agency consistency goals

- A content editor should encounter similar block structure across client sites.
- Blocks should have predictable names, categories, edit points, and component composition.
- Repeated visual treatments should become versioned agency modifiers or generic templates, not client-specific one-offs.
- Every generated custom rule should identify why a theme control or standard utility could not represent it.
- A completed site should include a machine-readable maintainability report.

### 3.3 Engineering goals

- Split the current extraction and composition responsibilities into focused modules.
- Keep pure analysis logic independent of network and portal access.
- Make source adapters independently testable using committed fixtures.
- Keep dependencies minimal; use Pydantic, BeautifulSoup, Requests, and optional Playwright already present in the project.
- Maintain deterministic JSON outputs suitable for diffs and regression testing.

## 4. Non-Goals

The following are outside this specification:

- Pixel-perfect reproduction through arbitrary raw HTML/CSS copying.
- Migrating analytics, tracking code, or third-party widget scripts.
- Automatically wiring source forms to a Vanjaro/DNN form provider.
- Recreating dynamic CMS data sources such as blogs, stores, or directories as working modules.
- Reproducing every animation or interaction when no maintainable Vanjaro primitive exists.
- Replacing the current crawl, asset, page, content, or publishing commands.
- Introducing machine-learning model training inside the CLI.
- Automatically publishing to a target portal without the existing confirmation and snapshot safeguards.

## 5. Design Principles

1. **Preserve relationships before choosing templates.** Extraction must describe the design without prematurely forcing it into a block.
2. **Prefer standard maintenance over superficial similarity.** A slightly simplified native block is preferable to fragile copied markup when the visual difference is acceptable.
3. **Make every lossy decision visible.** Dropped, merged, approximated, or manually required traits must be reported.
4. **Use confidence, not certainty theater.** Ambiguous matches must expose alternatives and evidence.
5. **Keep source adapters separate from shared reasoning.** HTML and Figma have different evidence but must converge on the same contract.
6. **Treat responsive behavior as part of the design.** Mobile is not an afterthought or a simple stacked default.
7. **Promote reusable fixes.** A treatment used successfully across multiple sites should graduate into the agency library.
8. **Benchmark end-to-end outcomes.** Unit tests alone cannot establish design fidelity.

## 6. Current Compatibility Baseline

At the time this specification was written:

- `vanjaro migrate --help` starts successfully.
- The local target reports DNN `9.10.2` and Vanjaro `1.6.0.0`.
- The Figma REST integration can inspect the existing Keys to Success frame.
- `pytest -m "not integration" -q` passes 1,096 tests with 16 integration tests deselected.
- Current section JSON, library-plan JSON, block templates, and migration directories must remain readable.

No phase is accepted if it regresses this baseline without an explicitly approved migration plan.

## 7. Target Architecture

```text
Live URL                                  Figma URL / frame
   |                                             |
   v                                             v
Existing crawler + rendered observations    Figma REST node tree
   |                                             |
   +--------------- Source adapters -------------+
                         |
                         v
              Design Document v1 (shared IR)
                         |
             +-----------+------------+
             |                        |
             v                        v
      Template capability       Theme/style translator
          matcher                    |
             |                        |
             +-----------+------------+
                         v
                 Composition Plan v2
                         |
              Existing block composition,
             assets, pages, global blocks,
                 assembly, and publish
                         |
                         v
          Content + structure + responsive +
                 visual quality gates
                         |
                         v
             Gap report and reusable-fix
                    recommendations
```

### 7.1 Proposed package layout

```text
vanjaro_cli/
  design/
    __init__.py
    models.py              # Pydantic Design Document v1 models
    serialization.py       # Stable JSON read/write and migrations
    html_adapter.py        # HTML/rendered-DOM -> Design Document
    figma_adapter.py       # Figma node tree -> Design Document
    grouping.py            # Source-neutral repeat/layout grouping helpers
    template_catalog.py    # Capability manifest loader/validator
    matcher.py             # Candidate scoring and explanations
    style_translation.py   # Theme/utilities/modifiers/CSS decisions
    planner.py             # Design Document -> Composition Plan v2
    metrics.py             # Extraction, matching, and maintainability metrics
  commands/
    migrate_analyze_cmd.py
    figma_analyze_cmd.py
    block_plan_cmd.py
schemas/
  design-document-v1.schema.json
  template-capabilities-v1.schema.json
  composition-plan-v2.schema.json
tests/
  fixtures/design-benchmarks/
```

Existing modules remain in place during migration. New adapters may call existing pure helpers initially, but new shared logic must not be added back into the monolithic section extractor.

## 8. Shared Design Document v1

### 8.1 Required artifact

Both live-site and Figma analysis must write:

```text
artifacts/<project>/design-document.json
```

The artifact must validate against `schemas/design-document-v1.schema.json` and include `schema_version: "1.0"`.

### 8.2 Top-level model

```json
{
  "schema_version": "1.0",
  "source": {
    "kind": "live_html",
    "identifier": "https://example.com/",
    "captured_at": "2026-07-16T00:00:00Z",
    "adapter_version": "1.0"
  },
  "tokens": {},
  "assets": [],
  "pages": [],
  "warnings": [],
  "analysis": {
    "section_confidence_mean": 0.91,
    "unsupported_traits": []
  }
}
```

### 8.3 Page model

Each page must include:

- Stable `id`
- Source URL or Figma node ID
- Title and slug
- Optional parent-page reference
- Ordered section list
- Page-level breakpoints observed
- Page-level navigation visibility
- SEO metadata when available
- Provenance references back to source nodes or DOM selectors

### 8.4 Section model

Each section must include:

```json
{
  "id": "home.services",
  "order": 3,
  "semantic_role": "feature_cards",
  "role_confidence": 0.92,
  "candidate_roles": [
    {"role": "feature_cards", "score": 0.92},
    {"role": "gallery", "score": 0.41}
  ],
  "layout": {
    "kind": "grid",
    "contained": true,
    "columns": 3,
    "media_position": "top",
    "alignment": "left",
    "full_bleed": false
  },
  "content": [],
  "groups": [],
  "style": {},
  "responsive": [],
  "decorative_layers": [],
  "interactions": [],
  "provenance": []
}
```

### 8.5 Content element model

Every visitor-facing content item must be represented as an element rather than placed directly into an unrelated positional array.

Required fields:

- `id`: stable within the document
- `kind`: `heading`, `text`, `image`, `button`, `link`, `list`, `list_item`, `quote`, `stat`, `video`, `form_placeholder`, or `other`
- `role`: semantic purpose such as `section_title`, `card_title`, `card_media`, `primary_action`, `price`, or `author`
- `value`: text or URL value when applicable
- `attributes`: alt text, href, heading level, media metadata, and accessibility information
- `group_id`: owning repeat group or layout region
- `order`: order within its owner
- `provenance`: source DOM selector, source URL, or Figma node ID
- `confidence`: extraction confidence from 0 to 1

### 8.6 Repeat groups

Cards, testimonials, stats, pricing plans, team members, FAQ items, gallery items, and navigation lists must be represented as repeat groups.

```json
{
  "id": "home.services.cards",
  "kind": "card",
  "items": [
    {
      "id": "home.services.card.1",
      "fields": {
        "media": "element-21",
        "title": "element-22",
        "body": "element-23",
        "action": "element-24"
      }
    }
  ]
}
```

The system must not depend on the first image, first heading, and first paragraph coincidentally referring to the same card.

### 8.7 Style observations

Style observations must distinguish extracted evidence from translation decisions.

Required supported properties:

- Background color and image
- Text color
- Font family, size, weight, line height, and letter spacing
- Width, height, min-height, and max-width
- Margin, padding, row gap, and column gap
- Text and item alignment
- Border, radius, and shadow
- Object fit and object position
- Positioning and overlap
- Transform and rotation
- Opacity and overlay color
- Display and visibility
- Grid/flex direction, wrapping, ordering, and column count

Unsupported CSS properties may be preserved as raw observations but must not be silently applied.

### 8.8 Responsive observations

The canonical breakpoint names are:

| Breakpoint | Default viewport | Purpose |
|---|---:|---|
| `desktop` | 1440×900 | Primary visual match |
| `tablet` | 768×1024 | Intermediate layout behavior |
| `mobile` | 390×844 | Small-screen behavior |

Each responsive observation must describe differences from the section's base layout, not duplicate the whole section.

Examples:

- `columns: 4 -> 2 -> 1`
- `media_position: right -> top`
- `navigation: expanded -> collapsed`
- `background_position: 50% 40% -> 65% 50%`
- `hidden: false -> true`

### 8.9 Provenance

Every inferred section, content item, style, and match must be traceable.

Live HTML provenance may contain:

- Page URL
- CSS selector or generated DOM path
- Source attribute
- Static or rendered observation
- Viewport

Figma provenance may contain:

- File key
- Page node ID
- Frame node ID
- Element node ID
- Component or instance ID

## 9. Requirement Set A — Design Document Foundation

### REQ-IR-001: Versioned models

Implement Pydantic models for every Design Document v1 structure.

**Acceptance criteria**

- A valid fixture round-trips JSON -> model -> JSON without data loss.
- Unknown future fields are either explicitly rejected or preserved according to one documented policy.
- Invalid references such as a group field pointing to a missing element fail validation with a useful path.
- Model validation never performs network or filesystem I/O.
- Public functions and models have type hints and `__all__` exports.

### REQ-IR-002: Deterministic serialization

Create stable UTF-8 JSON serialization.

**Acceptance criteria**

- Two runs against the same committed fixture produce byte-identical output after excluding documented volatile fields such as `captured_at`.
- Arrays retain meaningful source order.
- Generated IDs are stable and derived from source identity or structural position, not random UUIDs.
- Serialization uses two-space indentation and a trailing newline.

### REQ-IR-003: Schema files

Commit JSON Schema documents for all public artifacts.

**Acceptance criteria**

- The schemas validate every committed benchmark artifact.
- The schemas reject missing `schema_version`, duplicate IDs, invalid confidence ranges, and unknown enum values.
- Schema versioning and backward-compatibility rules are documented.

### REQ-IR-004: Legacy section conversion

Provide a compatibility converter from current crawler section JSON to Design Document v1.

**Acceptance criteria**

- Existing migration artifacts can be analyzed without recrawling.
- The converter records `confidence` and warnings when relationships cannot be recovered.
- Existing section files are not modified in place.

## 10. Requirement Set B — Live Website Analysis

### REQ-HTML-001: Preserve current crawl behavior

`vanjaro migrate crawl` remains responsible for discovery, fetching, assets, globals, tokens, and current artifacts.

**Acceptance criteria**

- All existing crawl tests remain green.
- Existing artifact names and schemas remain available during the compatibility period.
- A new crawl additionally writes `design-document.json` unless `--legacy-only` is passed.
- Crawl warnings include Design Document generation failures without deleting legacy output.

### REQ-HTML-002: Rendered observations at three breakpoints

When `--rendered` is enabled, collect DOM and computed-layout observations at desktop, tablet, and mobile viewports.

**Acceptance criteria**

- Each requested viewport appears in the Design Document.
- Lazy-loaded content is triggered before extraction.
- Fonts are awaited and animations/transitions are disabled for measurements.
- Hidden duplicates are distinguished from unique content hidden behind tabs or carousels.
- A per-viewport failure produces a warning and does not discard successful viewports.

### REQ-HTML-003: Section boundary detection

Detect visual sections using semantic markup, geometry, background changes, whitespace separation, layout containment, and heading hierarchy.

**Acceptance criteria**

- On the benchmark corpus, section-boundary precision is at least 0.90 and recall is at least 0.90.
- Header, footer, off-canvas navigation, cookie dialogs, and modal chrome are excluded from page-body sections.
- Repeated card children are not incorrectly split into separate page sections.
- Multiple stacked content modules inside one CMS pane can be separated.
- Every boundary includes evidence and confidence.

### REQ-HTML-004: Relationship-aware extraction

Extract repeat groups and bind their content fields.

**Acceptance criteria**

- Card titles, images, body copy, and actions remain associated with the correct card.
- Pricing features remain associated with the correct plan.
- Testimonials retain quote, author, role, and optional avatar association.
- FAQ questions remain associated with their answers.
- Blog cards retain title, image, excerpt, metadata, category, and link association.
- Group-field accuracy is at least 0.95 on annotated benchmark elements.

### REQ-HTML-005: Interaction inventory

Detect interactions without copying third-party scripts.

**Acceptance criteria**

- Accordions, tabs, carousels, video embeds, menus, forms, and modal triggers are identified.
- Each interaction records whether a native Vanjaro representation is known.
- Unsupported interactions appear as explicit gaps rather than being silently flattened.
- Forms retain field inventory but never generate functional raw form markup.

### REQ-HTML-006: Page-specific CSS evidence

Do not assume the homepage stylesheet set completely represents every page.

**Acceptance criteria**

- Linked stylesheets are cached by normalized URL and reused across pages.
- New page-specific stylesheets are fetched once and analyzed.
- Rendered computed styles take precedence over regex-derived static approximations.
- Stylesheet failures identify the affected page and URL.

## 11. Requirement Set C — Figma Analysis

### REQ-FIG-001: New command

Add:

```bash
vanjaro figma analyze FIGMA_URL \
  --node FRAME_ID \
  --output-dir artifacts/<project>/figma \
  --json
```

**Acceptance criteria**

- The command writes `design-document.json`, `design-tokens.json`, `theme-palette.json`, and an asset manifest.
- `--node` is required when a file contains multiple page-like frames unless `--all-page-frames` is passed.
- Dry-run mode performs analysis but does not download assets.
- Existing `figma inspect`, `tokens`, and `export` commands remain compatible.

### REQ-FIG-002: Frame-to-section segmentation

Segment a page frame into ordered visual sections using node containment, bounding boxes, background bands, repeated structures, and whitespace.

**Acceptance criteria**

- Section order matches vertical visual order.
- Overlapping decorative nodes do not create false sections.
- Full-width background shapes are associated with their section.
- A section nested inside a named component or frame preserves that identity as evidence.
- Precision and recall each reach at least 0.90 on annotated Figma benchmark frames.

### REQ-FIG-003: Layout and grouping

Interpret both auto-layout and manually positioned files.

**Acceptance criteria**

- Auto-layout direction, spacing, padding, alignment, and sizing modes are used when present.
- Non-auto-layout files infer rows, columns, repeat groups, alignment, and overlap from geometry.
- Repeated component instances become repeat-group items.
- Component overrides are resolved to the visible instance values.
- Hidden nodes are excluded unless they represent unique interactive states.

### REQ-FIG-004: Typography roles

Do not reduce the entire file to one heading font and one body font.

**Acceptance criteria**

- Text styles are clustered by semantic use, size, weight, position, and repetition.
- The system can represent display, heading, body, label, button, menu, and decorative typography separately.
- Mixed fonts in one design are preserved in the Design Document.
- Unresolvable font sources produce actionable registration notes.

### REQ-FIG-005: Asset association

Associate exported image fills and rendered vector/decorative assets with owning sections and roles.

**Acceptance criteria**

- Every visible image fill has an asset record or an explicit missing reason.
- Duplicate image references are downloaded once but may be referenced by multiple elements.
- Original image fills are preferred over frame screenshots.
- Vector groups needed for fidelity may be exported as SVG or PNG with provenance.
- Decorative assets are tagged separately from editorial content assets.

### REQ-FIG-006: Responsive evidence policy

Figma files often contain one desktop frame or separate desktop/mobile frames.

**Acceptance criteria**

- When paired frames are supplied, sections are matched across breakpoints by name, component identity, content, and order.
- When only desktop exists, inferred mobile behavior is marked `inferred`, not `observed`.
- The plan reports every major responsive decision that was inferred.

## 12. Requirement Set D — Template Capabilities and Matching

### 12.1 Capability manifest

Every template must gain a `capabilities` object, either embedded in the template JSON or stored in one generated catalog. Embedded metadata is preferred so templates remain portable.

```json
{
  "name": "Feature Cards (3-up)",
  "category": "Cards",
  "description": "...",
  "capabilities": {
    "schema_version": "1.0",
    "roles": ["feature_cards", "service_cards"],
    "layout": {
      "kind": "grid",
      "columns": [3],
      "media_positions": ["top", "none"],
      "alignment": ["left", "center"]
    },
    "repeat_group": {
      "kind": "card",
      "minimum": 2,
      "default": 3,
      "expandable": true
    },
    "fields": {
      "section_title": "optional",
      "item.title": "required",
      "item.body": "optional",
      "item.media": "optional",
      "item.action": "optional"
    },
    "responsive": {
      "desktop_columns": 3,
      "tablet_columns": 2,
      "mobile_columns": 1
    },
    "native_component_ratio": 1.0,
    "supported_modifiers": ["band-color", "card-radius", "media-aspect"]
  }
}
```

### REQ-TPL-001: Manifest coverage

**Acceptance criteria**

- All tracked templates validate against `template-capabilities-v1.schema.json`.
- The template catalog documentation is generated from actual templates and cannot silently drift.
- Duplicate template names fail validation.
- Every template declares fields, responsive behavior, and native-component ratio.

### REQ-TPL-002: Candidate scoring

The matcher must score all plausible templates rather than returning the first classified type.

The default weighted score is:

| Signal | Weight |
|---|---:|
| Semantic role compatibility | 25% |
| Required content field coverage | 20% |
| Repeat-group compatibility | 15% |
| Layout/geometry similarity | 15% |
| Responsive compatibility | 10% |
| Style/modifier compatibility | 5% |
| Interaction compatibility | 5% |
| Maintainability/native-component preference | 5% |

Weights must be configurable in one documented location.

**Acceptance criteria**

- Matching is deterministic.
- The result includes the top three candidates, subscores, total score, missing requirements, and required modifiers.
- The benchmark top-1 template accuracy is at least 0.85.
- The benchmark top-3 accuracy is at least 0.95.
- A candidate missing a required interaction or required field cannot receive `high` confidence.

### REQ-TPL-003: Confidence policy

| Confidence | Score | Required behavior |
|---|---:|---|
| High | `>= 0.85` | May be selected automatically |
| Medium | `0.65–0.849` | Select with visible delta report |
| Low | `< 0.65` | Do not silently force; require new template, simplification, or user decision |

**Acceptance criteria**

- Every selected template has a confidence label and numeric score.
- Low-confidence sections appear as blocking plan issues unless an explicit policy allows simplification.
- Users can override the selected template without editing source code.
- Manual overrides are recorded in the plan with author, reason, and prior candidates.

### REQ-TPL-004: Maintainability scoring

The matcher must calculate a maintainability impact.

Factors include:

- Native Vanjaro component ratio
- Number of custom modifiers
- Bytes and selector count of generated CSS
- Use of Custom Code
- Editable content coverage
- Global-block reuse
- Template reuse across pages

**Acceptance criteria**

- A visually similar native template outranks a raw-code solution by default.
- The final plan reports native component coverage and editable content coverage.
- Custom Code is never selected automatically when a medium-or-better native template exists.

## 13. Requirement Set E — Composition Plan v2

### 13.1 Required artifact

The planner writes:

```text
artifacts/<project>/composition-plan.json
```

The current `library-plan.json` remains supported. Composition Plan v2 may emit a compatible library plan as a derived artifact.

### 13.2 Plan entry

```json
{
  "id": "home.services.plan",
  "source_section_id": "home.services",
  "template": "Feature Cards (3-up)",
  "match": {
    "score": 0.91,
    "confidence": "high",
    "alternatives": []
  },
  "block": {
    "name": "Services Cards",
    "category": "Services",
    "type": "custom"
  },
  "bindings": {},
  "modifiers": [],
  "style_decisions": [],
  "warnings": []
}
```

### REQ-PLAN-001: Semantic bindings

Bindings must map semantic fields to actual template slots.

**Acceptance criteria**

- The planner never assumes that `image_3`, `heading_3`, and `text_3` belong together unless the template capability map declares that relationship.
- Repeating groups bind item-by-item.
- Missing optional fields blank or prune template placeholders.
- Missing required fields produce a validation error.
- No placeholder content or `placehold.co` URL reaches crawler-generated output.

### REQ-PLAN-002: Deterministic names and categories

**Acceptance criteria**

- Block names are unique within the target library.
- Naming follows documented agency conventions.
- Repeated structure with different content maps to one reusable custom-block pattern where appropriate.
- Identical content across pages remains eligible for existing global-section deduplication.

### REQ-PLAN-003: Explicit simplifications

**Acceptance criteria**

- Every unsupported decorative, responsive, or interactive trait is classified as `omit`, `approximate`, `modifier`, `new_template`, or `manual_module`.
- Omissions require a reason and severity.
- High-severity omissions block automatic approval.
- The gap report can consume these decisions without reparsing prose.

### REQ-PLAN-004: Backward-compatible output

**Acceptance criteria**

- The planner can emit a current-format `library-plan.json` for `blocks build-library`.
- Current `assemble-page` section files remain accepted.
- A migration may mix legacy section files and v2 planned sections during rollout.

## 14. Requirement Set F — Style and Responsive Translation

### 14.1 Translation precedence

Every visual property must be resolved through this order:

1. Existing Vanjaro theme control
2. Existing Vanjaro or Bootstrap utility class
3. Existing generic template modifier
4. Existing agency utility
5. New generic template modifier
6. Scoped site CSS
7. Explicit simplification or manual work

Raw copied source CSS is not an allowed automatic strategy.

### REQ-STY-001: Theme-token mapping

**Acceptance criteria**

- Colors within configured tolerance map to theme palette classes.
- Typography maps to the closest configured Vanjaro heading, paragraph, button, menu, or link style.
- Spacing and radius values map to known utilities or theme controls where possible.
- The decision report records exact source value, chosen target, distance, and confidence.

### REQ-STY-002: Responsive layout translation

**Acceptance criteria**

- Grid column changes produce appropriate breakpoint classes.
- Media/text order changes are preserved.
- Navigation collapse requirements are represented and cannot silently ship as a fully expanded mobile menu.
- Image crop differences support breakpoint-specific object position or alternate asset decisions.
- Every inferred responsive behavior is marked as inferred.

### REQ-STY-003: Decorative layers

**Acceptance criteria**

- Decorative assets and shapes remain separate from editable content.
- Common treatments such as overlays, pills, image rings, blobs, dividers, play buttons, and simple rotated bands can use generic modifiers.
- Decorative layers never obscure keyboard focus or meaningful content.
- Decorative images use empty alt text unless they convey content.

### REQ-STY-004: CSS contract and budget

Generated CSS must be scoped, explainable, and measured.

**Acceptance criteria**

- Every generated selector is scoped to a project or reusable agency namespace.
- No `!important` is generated unless an allowlisted platform override requires it and the reason is recorded.
- The plan reports selector count, rule count, and byte size.
- A section requiring more than 12 new scoped rules is flagged for a new template or design simplification review.
- Identical rules across two projects are recommended for promotion to an agency utility.

### REQ-STY-005: Reusable-fix promotion

**Acceptance criteria**

- A machine-readable registry tracks generic modifiers and the templates that support them.
- A modifier used successfully in at least two projects may be proposed for promotion.
- Promotion requires a generic name, documentation, responsive behavior, accessibility review, and tests.
- Client-prefixed rules are never promoted without being generalized.

## 15. Requirement Set G — Quality Measurement and Closed-Loop QA

### 15.1 Benchmark corpus

Commit a benchmark manifest describing at least:

- Three live HTML sites using meaningfully different builders or markup styles
- Two Figma designs, including one without auto-layout
- At least 25 annotated sections total
- At least 40 annotated repeating items total
- Desktop and mobile references for every benchmark page where available

Copyrighted source material that cannot be committed must be represented by synthetic fixtures with equivalent structure or by hashes and local setup instructions.

### REQ-QA-001: Extraction metrics

Measure:

- Section-boundary precision and recall
- Semantic-role accuracy
- Visitor-facing content retention
- Group-field association accuracy
- Asset association accuracy
- Responsive observation coverage

**Acceptance criteria**

- Metrics are reproducible from committed fixtures.
- A regression beyond 0.02 in any accepted metric fails CI unless baseline change is explicitly approved.
- Per-section failures identify source and expected annotations.

### REQ-QA-002: Match metrics

Measure top-1 and top-3 template accuracy, confidence calibration, required-field coverage, and maintainability score.

**Acceptance criteria**

- High-confidence predictions are correct at least 0.90 of the time on the benchmark.
- Low-confidence cases are not counted as successful merely because a fallback template rendered.
- Expected acceptable alternatives can be annotated when multiple templates are equally maintainable.

### REQ-QA-003: End-to-end portal benchmark

Run selected benchmarks through a disposable local portal.

**Acceptance criteria**

- The harness creates isolated pages or a portal, publishes, captures, and cleans up or restores from snapshot.
- Anonymous pages return HTTP 200 and exceed the blank-render threshold.
- Zero source-site asset URLs remain.
- Zero template placeholder strings or placeholder image domains remain.
- Global header/footer wrappers resolve correctly.
- The benchmark never modifies an unrelated portal or page.

### REQ-QA-004: Visual quality gate

Capture source/reference and migrated output at desktop, tablet, and mobile.

**Acceptance criteria**

- Lazy content is triggered before every capture.
- Fonts are settled and animation is disabled.
- Reports score sections individually and the page overall.
- Initial automatically generated drafts target at least 75/100 overall with no section below 60.
- A migration is shippable at 85/100 overall, no section below 75, and no high-severity systemic finding.
- Desktop success cannot mask a mobile score below 75.

### REQ-QA-005: Actionable remediation

**Acceptance criteria**

- Visual findings map to a source section, selected template, style decision, and responsible pipeline stage where possible.
- Recommendations distinguish content, asset, template, theme, modifier, CSS, and responsive issues.
- Re-running after a fix produces a score delta report.
- The system records which fixes are candidates for reusable promotion.

### REQ-QA-006: Maintainability gate

The final report must include:

- Native component coverage
- Editable content coverage
- Number of custom and global blocks
- New template count
- Custom Code usage
- Scoped CSS selector and byte counts
- Reusable modifier count
- Manual module requirements

**Acceptance criteria**

- Native component coverage is at least 90% for supported static sections.
- Editable content coverage is at least 95% for visitor-facing text and editorial images.
- Custom Code usage is zero unless an approved gap explicitly requires it.
- Any threshold exception is listed in the final gap report.

## 16. CLI Contracts

### 16.1 Live analysis

Existing command, extended behavior:

```bash
vanjaro migrate crawl URL \
  --output-dir artifacts/migration/example \
  --rendered \
  --viewport desktop \
  --viewport tablet \
  --viewport mobile \
  --json
```

New optional follow-up command for legacy artifacts or re-analysis without recrawling:

```bash
vanjaro migrate analyze artifacts/migration/example \
  --output artifacts/migration/example/design-document.json \
  --json
```

### 16.2 Figma analysis

```bash
vanjaro figma analyze FIGMA_URL \
  --node 156-890 \
  --output-dir artifacts/example/figma \
  --export-assets \
  --json
```

### 16.3 Template planning

```bash
vanjaro blocks plan \
  --design artifacts/example/design-document.json \
  --output artifacts/example/composition-plan.json \
  --library-plan artifacts/example/library-plan.json \
  --json
```

Options:

- `--minimum-confidence FLOAT`
- `--allow-simplification`
- `--template-override SECTION_ID=TEMPLATE`
- `--explain SECTION_ID`
- `--dry-run`

### 16.4 Validation

```bash
vanjaro blocks plan-validate artifacts/example/composition-plan.json --json
```

Validation must check schemas, references, template availability, bindings, placeholder leakage, CSS budget, confidence policy, and unresolved high-severity gaps.

### 16.5 Benchmarking

```bash
vanjaro migrate benchmark \
  --manifest tests/fixtures/design-benchmarks/manifest.json \
  --output artifacts/benchmarks/latest \
  --json
```

The default benchmark command is offline and fixture-based. Live portal and network-backed cases require explicit flags.

## 17. Error Handling and Diagnostics

All new commands follow existing Click conventions and support `--json`.

Required error categories:

- `schema_invalid`
- `source_unavailable`
- `frame_ambiguous`
- `section_low_confidence`
- `template_not_found`
- `template_low_confidence`
- `binding_incomplete`
- `asset_unresolved`
- `responsive_unknown`
- `css_budget_exceeded`
- `quality_gate_failed`

Every error must include:

- Human-readable message
- Machine-readable category
- Artifact or source path
- Section/node identifier where applicable
- Recommended next action

Warnings must never be used for conditions that would cause visitor-facing content loss.

## 18. Security and Privacy Requirements

- Never write `.env` values, Figma tokens, DNN passwords, cookies, or API keys into artifacts or logs.
- Redact signed Figma asset URLs after download; manifests should use stable `figma://` provenance identifiers.
- Respect current crawl limits and robots behavior.
- Do not execute source-site scripts outside the controlled browser context.
- Do not copy analytics, tracking scripts, or third-party credentials.
- Sanitize generated filenames and selectors.
- Keep benchmark fixtures free of customer secrets and personally sensitive content.

## 19. Performance Requirements

Performance is secondary to correctness, but prevent pathological behavior.

**Acceptance criteria**

- Pure analysis of a committed 10-page static fixture completes in under 30 seconds on the standard development machine.
- Figma analysis visits each node at most a constant number of times; no repeated full-tree scans per candidate template.
- Stylesheets and identical assets are fetched once per normalized URL/reference.
- Template matching is bounded by `sections × templates` and completes in under one second for 100 sections and 100 templates using fixtures.
- Browser sessions are reused across page/viewpoint captures when safe and always closed on error.

## 20. Backward Compatibility and Rollout

### Phase 0: Benchmark freeze

- Commit benchmark manifest, annotations, and current scores.
- Preserve Keys to Success as the first end-to-end regression case.
- Record the current legacy pipeline output for comparison.

### Phase 1: Design Document foundation

- Add models, schemas, serialization, and legacy conversion.
- Current pipeline behavior remains unchanged.

### Phase 2: Source adapters

- HTML and Figma emit Design Document v1.
- Commands expose experimental opt-in output.

### Phase 3: Capability matcher and planner

- Add template capabilities.
- Generate Composition Plan v2 and compatible library plans.
- Compare planned results with current template hints.

### Phase 4: Style/responsive translator

- Add translation decisions, modifiers, CSS contracts, and breakpoint output.

### Phase 5: Default-on and cleanup

- Design Document and planner become the default migration path after quality gates pass.
- Legacy artifacts remain readable for at least one minor release.
- Old heuristic code is removed only after equivalent benchmark coverage exists.

## 21. Definition of Done

Design Translation v2 is complete only when all of the following are true:

- Both live HTML and Figma produce valid Design Document v1 artifacts.
- All tracked templates have validated capability metadata.
- Planner top-1 and top-3 accuracy meet specified thresholds.
- Relationship-aware content bindings meet the benchmark threshold.
- Three-breakpoint responsive observations are supported.
- A current-format library plan can be generated and dry-run successfully.
- Existing migration artifacts remain usable.
- All unit tests pass.
- Live integration smoke tests pass against the local target.
- End-to-end benchmark meets content, structure, maintainability, and visual gates.
- No secrets appear in logs or artifacts.
- Documentation describes how to inspect, override, resume, and debug each stage.
- The final implementation report identifies remaining deliberate gaps.

## 22. Subagent Work Packages

The following packages are designed to minimize file overlap. One integration owner should control shared command registration, schema-version decisions, and final merges.

### WP-0 — Benchmark corpus and annotations

**Owns**

- `tests/fixtures/design-benchmarks/**`
- Benchmark manifest and annotation format
- Baseline score report

**Inputs**

- Existing Keys to Success artifacts
- Selected live-site and Figma fixtures

**Outputs**

- Offline fixtures
- Expected sections, roles, groups, bindings, and acceptable templates
- Current legacy baseline

**Dependencies:** None after annotation schema is agreed.  
**Acceptance:** REQ-QA-001 and the corpus-size requirements are satisfied.

### WP-1 — Design Document models and schemas

**Owns**

- `vanjaro_cli/design/models.py`
- `vanjaro_cli/design/serialization.py`
- `schemas/design-document-v1.schema.json`
- Model/schema unit tests

**Inputs**

- Sections 8 and 9 of this specification

**Outputs**

- Stable public artifact contract
- Deterministic serialization
- Legacy conversion interface contract

**Dependencies:** None. This package must merge before adapter integration.  
**Acceptance:** REQ-IR-001 through REQ-IR-003.

### WP-2 — Legacy conversion and HTML adapter

**Owns**

- `vanjaro_cli/design/html_adapter.py`
- HTML-specific fixtures and tests
- Minimal adapter hooks in migration analysis

**Must not own**

- Shared models
- Figma logic
- Matcher logic
- CLI registration

**Dependencies:** WP-1 contract.  
**Acceptance:** REQ-IR-004 and REQ-HTML-001 through REQ-HTML-006.

### WP-3 — Figma adapter

**Owns**

- `vanjaro_cli/design/figma_adapter.py`
- Figma fixture normalization
- Figma analysis unit tests

**Must not own**

- Existing REST client behavior except narrowly required read-only additions
- Shared models
- Template matcher
- CLI registration

**Dependencies:** WP-1 contract.  
**Acceptance:** REQ-FIG-001 through REQ-FIG-006, excluding final command wiring.

### WP-4 — Template capability catalog

**Owns**

- Capability metadata on all templates
- `schemas/template-capabilities-v1.schema.json`
- `vanjaro_cli/design/template_catalog.py`
- Generated catalog documentation

**Dependencies:** Capability schema agreed with WP-5.  
**Acceptance:** REQ-TPL-001 and zero catalog drift.

### WP-5 — Template matcher

**Owns**

- `vanjaro_cli/design/matcher.py`
- Match scoring configuration
- Explainability and confidence tests

**Must not edit**

- Template JSON files
- Source adapters
- Command modules

**Dependencies:** WP-1 models and WP-4 capability interface.  
**Acceptance:** REQ-TPL-002 through REQ-TPL-004 and benchmark thresholds.

### WP-6 — Style and responsive translator

**Owns**

- `vanjaro_cli/design/style_translation.py`
- Agency modifier registry format
- Style-decision tests

**Dependencies:** WP-1 style models and WP-4 modifier declarations.  
**Acceptance:** REQ-STY-001 through REQ-STY-005.

### WP-7 — Composition planner

**Owns**

- `vanjaro_cli/design/planner.py`
- `schemas/composition-plan-v2.schema.json`
- Library-plan compatibility emitter
- Planner unit tests

**Dependencies:** WP-1, WP-4, WP-5, and WP-6.  
**Acceptance:** REQ-PLAN-001 through REQ-PLAN-004.

### WP-8 — CLI integration and artifact orchestration

**Owns**

- New command modules
- Registration in `commands/__init__.py`, `cli.py`, and migrate groups
- End-user JSON output and diagnostics
- Compatibility flags

**Must not implement**

- Adapter, matcher, or planner internals

**Dependencies:** Stable public functions from WP-2, WP-3, WP-5, and WP-7.  
**Acceptance:** Section 16 command contracts and Section 17 diagnostics.

### WP-9 — End-to-end benchmark and portal harness

**Owns**

- `vanjaro_cli/design/metrics.py`
- Offline benchmark runner
- Isolated live-portal benchmark workflow
- Score and regression reports

**Dependencies:** WP-0 fixtures plus integrated adapters, matcher, and planner.  
**Acceptance:** REQ-QA-001 through REQ-QA-006.

### WP-10 — Documentation and migration guide

**Owns**

- User workflow documentation
- Artifact reference
- Override and debugging guide
- Contributor guide for templates and modifiers

**Dependencies:** Final command and schema names.  
**Acceptance:** A new contributor can run an offline benchmark, analyze one source, explain a match, override it, and validate the plan using only documented commands.

## 23. Recommended Parallel Execution Plan

### Wave 1 — Contract and evidence

Run in parallel:

- WP-0 Benchmark corpus
- WP-1 Design Document models and schemas
- WP-4 capability schema/catalog preparation

Integration checkpoint:

- Freeze Design Document v1 field names.
- Freeze benchmark annotation shape.
- Freeze template capability schema.

### Wave 2 — Independent engines

Run in parallel after the checkpoint:

- WP-2 HTML adapter
- WP-3 Figma adapter
- WP-5 matcher
- WP-6 style translator

Integration checkpoint:

- Both adapters validate against the same Design Document schema.
- Matcher consumes adapter output without source-specific branches.
- Style translator consumes only shared style observations and capability metadata.

### Wave 3 — Planning and commands

Run:

- WP-7 composition planner
- WP-8 CLI integration after public functions stabilize

Integration checkpoint:

- A live fixture and a Figma fixture both produce valid compatible library plans.
- Dry-run block-library validation succeeds.

### Wave 4 — Quality gate and documentation

Run in parallel:

- WP-9 benchmark/portal harness
- WP-10 documentation

Final checkpoint:

- Run the full unit, integration, benchmark, and visual suites.
- Compare all metrics with the frozen legacy baseline.
- Approve any intentional behavior changes explicitly.

## 24. Integration Ownership Rules

To prevent subagent conflicts:

1. Only WP-1 may change shared Design Document model fields during Waves 1–2.
2. Only WP-4 may bulk-edit template capability metadata.
3. Only WP-8 may register commands or edit central CLI imports.
4. Only WP-7 may define Composition Plan v2 output.
5. Source adapters must not import each other.
6. Matcher and planner must not contain source-specific DOM or Figma logic.
7. New shared-field requests require a short contract change note and tests before dependent work continues.
8. Each package must include tests and a handoff note listing public functions, artifacts, and known gaps.

## 25. Review Checklist

Before implementation begins, reviewers should explicitly approve:

- Design Document v1 schema
- Template capability schema
- Composition Plan v2 schema
- Benchmark corpus and target thresholds
- Confidence thresholds and scoring weights
- Native-component and CSS-budget gates
- Responsive viewport policy
- Backward-compatibility period
- Exact CLI command names

These decisions are the primary cross-package contracts. Changing them after parallel work starts will create the largest rework risk.
