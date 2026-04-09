# Reusable Block Composition System

## Goal

Enable an agent to analyze a site's design, identify recurring UI patterns, and compose reusable **custom blocks** from Vanjaro's built-in primitives + Bootstrap 5 classes. Users can then drag-and-drop these blocks into their site and they'll match the site's look and feel. Each dropped block is an independent copy that can be edited per-page.

## Block Types in Vanjaro

There are three distinct block concepts. The plan focuses on **custom blocks**.

| Type | What It Is | Edit Behavior | Use Case |
|------|-----------|---------------|----------|
| **Primitive blocks** | Built-in GrapesJS blocks (section, grid, heading, text, button, etc.) | Always independent | The atomic building pieces |
| **Custom blocks** | Saved compositions of primitives that appear in the editor sidebar | Each drop creates an **independent copy** — edit freely per-page | Reusable section templates: hero, cards, CTA, testimonials, etc. |
| **Global blocks** | Shared block instances referenced across pages | Edit once, changes **everywhere** | Header, footer, site-wide CTA banner — things that must stay in sync |

**Custom blocks are the primary deliverable.** They're the components a user drags onto a page to build it out. Each instance is independent, so the user can swap images, change text, and adjust layout without affecting other pages.

**Global blocks are a narrow secondary use case** — only for the few elements (header, footer) that should be identical across every page.

## Current State

### Available Primitives (GrapesJS Blocks)

| Block | What It Does | Key Classes |
|-------|-------------|-------------|
| Section | Top-level container | `vj-section`, `bg-*` |
| Grid | Bootstrap container/row/col | `container`, `row`, `col-xl-*`, `col-md-*`, `col-sm-*`, `col-12` |
| Heading | H1-H6 with 10 style presets | `vj-heading`, `head-style-1` through `head-style-10` |
| Text | Paragraphs with 10 style presets | `vj-text`, `paragraph-style-1` through `paragraph-style-10` |
| Button | CTA buttons with 10 style presets | `btn`, `btn-primary` through `btn-dark`, `btn-outline-*`, `button-style-1` through `button-style-10` |
| Icon | SVG icons with borders/backgrounds | `icon-box`, `vj-icon`, `text-primary`, `border-primary` |
| Link | Wrapper container (can hold other blocks) | `vj-link` |
| List | Ordered/unordered lists | `list-box`, `list`, `list-item`, `list-text` |
| Image | Responsive images | `image-box`, `vj-image`, `img-fluid` |
| Image Gallery | Multi-image display | `vj-image-gallery`, `img-thumbnail` |
| Carousel | Bootstrap 5 slideshow | `carousel`, `carousel-inner`, `carousel-item`, `data-bs-*` |
| Video | HTML5 or YouTube | `video-box`, `embed-container` |
| Spacer | Vertical space (10-600px) | `spacer` |
| Divider | Horizontal rule | `vj-divider`, `border-*` |
| Custom Code | Raw HTML | (user-defined) |

### Vannaro Style Presets

Each heading, text, and button block has 10 style presets that map to the site's theme:
- `head-style-1` through `head-style-10` — controlled by theme H1-H10 settings (font, weight, size)
- `paragraph-style-1` through `paragraph-style-10` — controlled by theme P1-P10 settings
- `button-style-1` through `button-style-10` — controlled by theme B1-B10 settings (font, weight, radius, padding)

This means blocks automatically inherit the site's typography and button styling when using these preset classes.

### Bootstrap 5.1.0 Classes Available

All standard Bootstrap 5 utilities work in Vanjaro:
- **Grid**: `container`, `container-fluid`, `row`, `col-{breakpoint}-{1-12}`
- **Spacing**: `m-{0-5}`, `p-{0-5}`, `mx-auto`, `py-5`, `gap-{1-5}`
- **Flex**: `d-flex`, `flex-column`, `align-items-center`, `justify-content-*`
- **Text**: `text-center`, `text-start`, `text-end`, `text-uppercase`, `fw-bold`, `fs-{1-6}`
- **Colors**: `text-{color}`, `bg-{color}`, `border-{color}`
- **Display**: `d-none`, `d-{breakpoint}-block`, `d-{breakpoint}-flex`
- **Borders**: `border`, `rounded`, `rounded-circle`, `shadow`, `shadow-sm`
- **Sizing**: `w-100`, `h-100`, `mw-100`

### What Exists in the CLI

- `blocks scaffold` — generates page-level layouts from 11 templates
- `global-blocks list/get/update/publish/delete` — manages existing global blocks
- `content update` — pushes full component tree to a page
- Theme controls + custom CSS — site-wide styling

### What's Missing

1. **Custom block creation API** — no CLI command or known API endpoint to save a new custom block to the editor sidebar. The `AIBlock` endpoints read page blocks; they don't create sidebar entries. Need to discover the "Save as Block" endpoint.
2. **`global-blocks create`** — same gap for global blocks (header/footer use case)
3. **Block template library** — scaffold templates are page-level layouts, not reusable drag-and-drop components
4. **Design analysis skill** — nothing that maps a design to block compositions
5. **Parameterized templates** — can't customize block templates with site-specific tokens

---

## Architecture

### How Custom Blocks Work in Vanjaro

When a user right-clicks a section in the Vanjaro editor and selects "Save as Block":
1. The section's GrapesJS component tree + styles are captured
2. The block is saved with a name and category
3. It appears in the editor's block sidebar under its category
4. Dragging it onto a page creates an **independent copy** of that component tree
5. The user edits the copy freely — changes don't affect the saved block or other pages

This is the UX we want to enable programmatically.

### Concept: Block Templates

A **block template** is a reusable GrapesJS component tree that represents a common UI pattern. It uses:
- Vanjaro primitive blocks (section, grid, heading, text, button, etc.)
- Bootstrap 5 utility classes for layout and spacing
- Vanjaro style presets (`head-style-1`, `button-style-1`) for theme inheritance
- Placeholder content that users swap out after dropping the block

Templates are JSON files stored in `artifacts/block-templates/`. They serve two purposes:
1. **Agent-side**: The agent uses them to compose page content via `content update` (current workflow)
2. **Editor-side**: Once registered as custom blocks, users can drag-and-drop them in the Vanjaro editor

### Example: "Feature Cards (3-up)" Template

```json
{
  "name": "Feature Cards (3-up)",
  "category": "Content",
  "description": "Three equal-width cards with icon, heading, text, and CTA button",
  "template": {
    "type": "section",
    "classes": [{"name": "vj-section", "active": false}],
    "components": [{
      "type": "grid",
      "classes": [{"name": "container", "active": false}],
      "components": [{
        "type": "row",
        "classes": [
          {"name": "row", "active": false},
          {"name": "g-4", "active": false},
          {"name": "text-center", "active": false}
        ],
        "components": [
          {
            "type": "column",
            "classes": [
              {"name": "col-xl-4", "active": false},
              {"name": "col-md-4", "active": false},
              {"name": "col-sm-6", "active": false},
              {"name": "col-12", "active": false}
            ],
            "components": [
              {
                "type": "icon",
                "classes": [{"name": "icon-box", "active": false}, {"name": "vj-icon", "active": false}, {"name": "text-primary", "active": false}]
              },
              {
                "type": "heading",
                "tagName": "h3",
                "content": "Feature Title",
                "classes": [{"name": "vj-heading", "active": false}, {"name": "head-style-3", "active": false}, {"name": "mt-3", "active": false}]
              },
              {
                "type": "text",
                "content": "Brief description of this feature and why it matters to your audience.",
                "classes": [{"name": "vj-text", "active": false}, {"name": "paragraph-style-1", "active": false}]
              },
              {
                "type": "button",
                "content": "Learn More",
                "classes": [{"name": "btn", "active": false}, {"name": "btn-outline-primary", "active": false}, {"name": "button-style-1", "active": false}, {"name": "mt-2", "active": false}]
              }
            ]
          }
        ]
      }]
    }]
  },
  "styles": []
}
```

The second and third cards are duplicates of the first column. The template includes one; the composition step duplicates it with unique IDs.

### Template Categories

| Category | Patterns | Use Cases |
|----------|----------|-----------|
| **Heroes** | Full-width hero, split hero (text+image), video hero, centered hero | Landing pages, interior page headers |
| **Content** | Text block, text+image side-by-side, blockquote/pullquote, bio/about | Body content sections |
| **Cards** | 2-up, 3-up, 4-up feature cards, pricing cards, team member cards | Services, features, team, pricing |
| **Testimonials** | Single quote, 3-up quote cards, carousel testimonials | Social proof sections |
| **CTAs** | Centered CTA, split CTA (text+button), banner CTA | Conversion sections |
| **Lists** | Icon list, checklist, numbered steps, FAQ (if accordion available) | Feature lists, processes, FAQs |
| **Media** | Image gallery, video embed, carousel/slideshow | Portfolio, galleries |
| **Navigation** | Footer (multi-column), breadcrumb bar, sidebar nav | Page chrome |

---

## Implementation Phases

### Phase 1: Block Creation API [RESEARCHED]

**Findings**: Both endpoints discovered and documented.

#### Global Block Creation (ready to implement)

**Endpoint**: `POST /API/VanjaroAI/AIGlobalBlock/Create`
- **Auth**: Cookies + API key (same as all other VanjaroAI endpoints — already works)
- **Body**: JSON
  ```json
  {
    "name": "Site Header",
    "category": "Navigation",
    "contentJSON": "[{...grapesjs json...}]",
    "styleJSON": "[{...styles...}]",
    "html": "<section>...</section>",
    "css": ".class { ... }"
  }
  ```
- **Response**: HTTP 201 `{ guid, name, version, isPublished }`
- **Conflicts**: Returns 409 if name already exists
- **Storage**: `VJ_Core_GlobalBlock` table (versioned, publishable, shared across pages)

**Task**: Add `global-blocks create` CLI command. Straightforward — same auth pattern as existing commands.

#### Custom Block Creation (needs DNN header support)

**Endpoint**: `POST /API/Vanjaro/Block/AddCustomBlock`
- **Auth**: Cookies + anti-forgery token (already handled by `client.py`) + DNN headers (`TabId`, `ModuleId`)
- **Body**: Form-encoded (NOT JSON)
  ```
  Name=Feature+Cards&Category=Content&IsGlobal=false&ContentJSON=[...]&StyleJSON=[...]&Html=&Css=
  ```
- **Response**: `{ Status: "Success", Guid: null }` (custom) or `{ Status: "Success", Guid: "..." }` (global)
- **Conflicts**: Returns `{ Status: "Exist" }` if name taken
- **Storage**: `VJ_Core_CustomBlock` table (no versioning, no publish — drag creates independent copy)

**Challenges**:
1. Requires `TabId` and `ModuleId` DNN Services Framework headers — need to discover the UXManager module ID
2. Requires form-encoded body — client currently always sends `Content-Type: application/json`
3. The `[AuthorizeAccessRoles(AccessRoles = "admin")]` attribute may need page editor context

**Resolution**: Approach A works. No `TabId`/`ModuleId` headers needed — just cookies + anti-forgery token + form-encoded body. The `post_form()` method was added to `VanjaroClient` to handle form-encoded requests.

CLI commands implemented and tested:
- `custom-blocks list` — lists all custom blocks
- `custom-blocks create --name NAME --category CAT --file FILE` — creates a custom block
- `custom-blocks delete GUID --force` — deletes a custom block

#### All Discovered Block Endpoints

**Core Vanjaro Block Controller** (`/API/Vanjaro/Block/`):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `GetAll` | List built-in design blocks (Logo, Menu, Login, etc.) |
| GET | `GetAllCustomBlock` | List all custom blocks (independent-copy type) |
| GET | `GetAllGlobalBlock` | List all global blocks (shared type) |
| POST | `AddCustomBlock` | Create custom or global block (via `IsGlobal` flag) |
| POST | `EditCustomBlock` | Update custom block name/category |
| POST | `EditGlobalBlock` | Update global block name/category |
| POST | `DeleteCustomBlock?CustomBlockGuid=...` | Delete custom block |
| POST | `DeleteGlobalBlock?CustomBlockGuid=...` | Delete global block |
| GET | `ExportCustomBlock?CustomBlockGuid=...` | Export block as .zip |
| POST | `ImportCustomBlock?TemplateHash=...&TemplatePath=...` | Import block from template |

**VanjaroAI Global Block Controller** (`/API/VanjaroAI/AIGlobalBlock/`):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `List` | List all global blocks |
| GET | `Get?guid=...` | Get global block detail |
| POST | `Create` | **Create** global block (NEW — not yet in CLI) |
| POST | `Update` | Update global block content |
| POST | `Publish` | Publish global block |
| POST | `Delete` | Delete global block |

**No VanjaroAI equivalent exists for custom blocks.** Only the core controller handles them.

**Status: COMPLETE.** Both create commands work end-to-end:
- `global-blocks create` → block visible in editor sidebar as shared block
- `custom-blocks create` → block visible in editor sidebar, creates independent copy when dragged

### Phase 2: Block Template Library

**Goal**: Build a library of composable block templates as JSON files.

**Tasks**:
1. Define the template file format (name, category, description, template JSON, styles, metadata)
2. Create templates for the most common patterns:
   - Hero (full-width with CTA)
   - Hero split (text left, image right)
   - Feature cards (3-up)
   - Feature cards (4-up)
   - Testimonial cards (3-up)
   - CTA banner (centered)
   - CTA split (text + button)
   - Bio/about (image + text)
   - Pricing cards (3-up)
   - Contact section (form + info)
   - Footer (3-column)
   - Icon feature list
3. Each template uses only Vanjaro primitives + Bootstrap 5 classes
4. Each template uses style presets (`head-style-*`, `button-style-*`) so they inherit theme settings
5. Validate every template by pushing to a test page and verifying it renders correctly

**Acceptance**: 12+ block templates stored in `artifacts/block-templates/`, each verified on a live Vanjaro site.

### Skills (created alongside Phase 2-3)

Three skills support the block template workflow:

| Skill | Status | Phase | Purpose |
|-------|--------|-------|---------|
| `block-template-author` | CREATED | 2 | Validates and creates block template JSON files. Enforces nesting rules, required classes, style presets, and category conventions. Includes a `validate_template.py` script for deterministic checks. |
| `block-register` | PLANNED | 3 | Batch-registers templates as custom blocks on a live site. Takes a directory or list of template files, registers each via `custom-blocks create`, reports success/failure per template. |
| `block-compose` | PLANNED | 3 | Customizes a template with content overrides (heading text, button labels, image URLs, column count) and outputs ready JSON for registration or `content update`. |

### Phase 3: Block Composition CLI Commands

**Goal**: CLI commands to compose and register blocks from templates.

**New commands**:
```bash
# List available block templates
vanjaro blocks templates

# Preview a template (show its structure)
vanjaro blocks template-preview <template-name>

# Compose a block from a template with customization
vanjaro blocks compose <template-name> \
  --heading "Our Services" \
  --text "What we offer" \
  --button-label "Get Started" \
  --columns 4 \
  --output block.json

# Register as a custom block (independent copies when dragged)
vanjaro custom-blocks create \
  --name "Services Cards" \
  --category "Content Blocks" \
  --file block.json

# Register as a global block (shared instance — header/footer only)
vanjaro global-blocks create \
  --name "Site Header" \
  --category "Navigation" \
  --file header.json

# Batch: compose + register multiple custom blocks from a plan
vanjaro blocks build-library --plan library-plan.json
```

**Tasks**:
1. Add `blocks templates` command — lists templates from `artifacts/block-templates/`
2. Add `blocks compose` command — takes a template + overrides, outputs customized JSON
3. Add `custom-blocks create` command (from Phase 1 research) — registers as editor sidebar entry
4. Add `global-blocks create` command (from Phase 1 research) — for header/footer
5. Add `blocks build-library` command — reads a plan file and batch-creates custom blocks

**Acceptance**: Can go from template selection to registered custom block in 2-3 CLI commands. Block appears in editor sidebar and creates an independent copy when dragged onto a page.

### Phase 4: Design Analysis Skill

**Goal**: A skill that teaches an agent to analyze a design and produce a block library plan.

**Skill: `skills/block-composer.md`**

The skill instructs the agent to:

1. **Analyze the design** — Look at mockups, screenshots, or a live site and identify:
   - Recurring UI patterns (what sections appear on multiple pages?)
   - Layout structures (how many columns? what breakpoints?)
   - Content types within each pattern (heading, text, image, button, icon, list?)
   - Spacing and alignment patterns

2. **Map patterns to templates** — For each identified pattern:
   - Find the closest matching block template from the library
   - Note any customizations needed (different column count, extra elements, etc.)
   - If no template fits, design a new composition from primitives

3. **Generate a library plan** — Output a JSON plan file:
   ```json
   {
     "site": "example.com",
     "blocks": [
       {
         "name": "Hero Banner",
         "template": "hero-split",
         "category": "Heroes",
         "customizations": {
           "heading_style": "head-style-1",
           "button_style": "button-style-1",
           "button_variant": "btn-primary"
         }
       },
       {
         "name": "Service Cards",
         "template": "feature-cards-3",
         "category": "Content",
         "customizations": {
           "heading_style": "head-style-3",
           "columns": 3
         }
       }
     ]
   }
   ```

4. **Build the library** — Run `blocks build-library --plan <file>` to compose and register all custom blocks

**Acceptance**: Agent can look at a design, produce a plan, and build a complete custom block library in one workflow.

### Phase 5: End-to-End Workflow Integration

**Goal**: Tie everything together into a single skill that goes from design to drag-and-drop blocks.

**Complete workflow**:
```
Design/Mockup
  → Theme Extraction (colors, fonts, spacing)
  → Theme Application (112 theme controls + custom CSS)
  → Design Analysis (identify recurring UI patterns)
  → Block Library Plan (map patterns to templates)
  → Block Composition (build GrapesJS JSON for each)
  → Custom Block Registration (save to editor sidebar)
  → Global Block Registration (header/footer only)
  → User drags and drops custom blocks to build pages
```

**Integration with existing skills**:
- `theme-extract-tokens` → extracts colors, fonts, spacing from the design
- `theme-apply` → applies theme controls to match the design
- `theme css update` → injects custom CSS for anything beyond theme controls
- `block-composer` (new) → analyzes design patterns and builds custom blocks
- `build-page` → assembles pages using custom blocks + page-specific content

**User experience after the agent finishes**:
1. Open any page in the Vanjaro editor
2. Open the block sidebar → see custom blocks organized by category (Heroes, Cards, CTAs, etc.)
3. Drag a "Feature Cards (3-up)" block onto the page
4. Get an independent copy with placeholder content already styled to match the site
5. Edit text, swap images, adjust as needed — no effect on other pages or the saved block

---

## Open Questions

### Answered

1. ~~**Custom block creation API**~~ — **FOUND.** `POST /API/Vanjaro/Block/AddCustomBlock` with form-encoded body + DNN headers. Needs `TabId`, `ModuleId`, `RequestVerificationToken`, and `IsGlobal=false`. See Phase 1 for details.

2. ~~**Global block creation API**~~ — **FOUND.** `POST /API/VanjaroAI/AIGlobalBlock/Create` with JSON body + cookies + API key. Ready to implement.

3. ~~**Thumbnails**~~ — **Answered.** Custom blocks have a `ScreenshotPath` field in the `GetAllCustomBlock` response. The editor likely generates a screenshot on save. For CLI-created blocks, we may get a default/empty thumbnail. Need to verify whether blocks without screenshots still appear usable in the sidebar.

### Still Open

4. ~~**DNN header discovery**~~ — **ANSWERED.** `TabId` and `ModuleId` are NOT required. `AddCustomBlock` works with just cookies + anti-forgery token (which the client already provides).

5. **Style isolation** — When a custom block's styleJSON is copied to a page, do the selectors conflict? Does Vanjaro regenerate component IDs when a custom block is dropped onto a page?

6. **Custom block limits** — Is the 50-block limit configurable? A full site library could exceed it with variants.

7. **Premium blocks** — Accordion, Tabs, Counter, Portfolio require premium. Should templates flag these or have fallback compositions?

8. **Custom Code blocks** — For patterns beyond primitives (complex hover effects, animations), should we use raw HTML Custom Code blocks? Tradeoff: full control vs. no inline editing.

9. **Template versioning** — When block templates are improved, should existing custom blocks on the site be updated? Or fire-and-forget since each page copy is independent?
