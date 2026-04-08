# Design — vanjaro-cli

How to translate page designs into Vanjaro page structures using CLI commands.

## Prerequisites

Before building pages, ensure:
1. You are logged in: `vanjaro auth login --url http://your-site.com`
2. API key is generated: `vanjaro api-key generate`
3. Verify connectivity: `vanjaro site health`
4. Verify target pages use the Vanjaro shell: `vanjaro pages shell`

Sessions expire after inactivity. If any command fails with "Session expired":
```bash
vanjaro auth login
vanjaro api-key generate
```

## Site Setup Order

When building a site from a design, follow this order:

1. **Branding** — site name, footer text
2. **Page shell audit** — normalize any non-Vanjaro pages via `pages shell PAGE_ID --fix`
3. **Fonts** — register custom fonts via `theme register-font`
4. **Theme colors** — update design controls via `theme set`
5. **Global blocks** — header and footer (shared across all pages)
6. **Pages** — create and populate each page
7. **Publish** — publish each page when ready

## GrapesJS Component Model

Vanjaro stores page content as a GrapesJS component tree. Every page is a list of top-level components, each containing nested children.

### Component Types

| Type | Purpose | Nesting |
|------|---------|---------|
| `section` | Full-width page section | Contains grid or direct content |
| `grid` | Container (Bootstrap `.container`) | Contains rows |
| `row` | Bootstrap row | Contains columns |
| `column` | Bootstrap column | Contains content components |
| `text` | Paragraph or rich text | Leaf node |
| `heading` | H1-H6 heading | Leaf node |
| `image` | Image element | Leaf node |
| `image-box` | Image with frame wrapper | Contains image-frame > picture-box > image |
| `button` | Button/link | Leaf node |
| `link` | Anchor link | Leaf node |
| `globalblockwrapper` | Reference to a global block (header/footer) | Managed separately |

### Component Structure

```json
{
  "type": "section",
  "classes": [{"name": "vj-section", "active": false}],
  "attributes": {"id": "auto-generated"},
  "components": [
    {
      "type": "grid",
      "classes": [{"name": "container", "active": false}],
      "components": [
        {
          "type": "row",
          "classes": [{"name": "row", "active": false}],
          "components": [
            {
              "type": "column",
              "classes": [
                {"name": "col-lg-6", "active": false},
                {"name": "col-12", "active": false}
              ],
              "components": [
                {"type": "heading", "content": "Page Title"},
                {"type": "text", "content": "Body text here"}
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

## Page Building Workflow

### Step 1: Create the page
```bash
vanjaro build --title "About Us" --template Default
# Or without template:
vanjaro pages create --title "About Us"
```

### Step 2: Scaffold the layout
```bash
vanjaro blocks scaffold --sections hero,content,cards-3,testimonials,cta --output layout.json
```

### Step 3: Push content to the page
```bash
vanjaro content update PAGE_ID --file layout.json
```

### Step 4: Customize individual blocks
```bash
# View the tree
vanjaro blocks tree PAGE_ID

# Modify a specific block
vanjaro blocks add PAGE_ID --type text --content "New paragraph" --parent SECTION_ID
vanjaro blocks remove PAGE_ID COMPONENT_ID --force
```

### Step 5: Publish
```bash
vanjaro content publish PAGE_ID
```

## Section Patterns

These are the reusable layout patterns available in the scaffold command. Mix and match to build pages.

### `hero` — Two-column hero with CTA buttons
```
| Script heading + Title      | Image/Video    |
| Body text                   | Placeholder    |
| [Primary CTA] [Secondary]  |                |
```
Layout: 2 columns (6/6), gradient background
Use for: Landing pages, home pages

### `hero-simple` — Centered heading banner
```
|           Page Title           |
|           Subtitle             |
```
Layout: Full-width centered, gradient background
Use for: Interior page headers (About, Services, Contact)

### `content` — Centered text block
```
|              Heading              |
|   Body text paragraph 1          |
|   Body text paragraph 2          |
|          [CTA Button]            |
```
Layout: Single column (8/12 centered)
Use for: About sections, mission statements, long-form content

### `cards-3` — Three-column card grid
```
| Card 1      | Card 2      | Card 3      |
| Heading     | Heading     | Heading     |
| Description | Description | Description |
| Link ->     | Link ->     | Link ->     |
```
Layout: 3 columns (4/4/4)
Use for: Services overview, feature highlights

### `testimonials` — Quote cards
```
| "Quote 1..."  | "Quote 2..."  | "Quote 3..."  |
| — Author 1    | — Author 2    | — Author 3    |
```
Layout: 3 columns (4/4/4), light background
Use for: Social proof, success stories

### `bio` — Photo + text side-by-side
```
| Photo      | Name & Title          |
| Placeholder| Bio paragraph 1       |
|            | Bio paragraph 2       |
```
Layout: 2 columns (5/7)
Use for: About page bios, team members

### `checklist` — Heading + list items + CTA
```
|         Script Heading          |
|   [ ] Item 1                   |
|   [ ] Item 2                   |
|   [ ] Item 3                   |
|         [CTA Button]           |
```
Layout: Single column (8/12 centered), tinted background
Use for: "Are you ready" sections, feature lists

### `cta` — Call-to-action banner
```
|           Heading              |
|           Body text            |
|        [Primary Button]       |
```
Layout: Full-width centered
Use for: Conversion sections, page closers

### `form` — Contact form with sidebar
```
| Form Title               | Contact Info   |
| [Name field]             | Social links   |
| [Email] [Phone]          | Email address  |
| [Message textarea]       | Schedule link  |
| [Submit button]          |                |
```
Layout: 2 columns (8/4)
Use for: Contact pages, booking pages

### `features-4` — Four-column feature grid
```
| Feature 1  | Feature 2  | Feature 3  | Feature 4  |
| Heading    | Heading    | Heading    | Heading    |
| Text       | Text       | Text       | Text       |
```
Layout: 4 columns (3/3/3/3), dark background
Use for: Value propositions, "you belong" sections

### `program` — Program/service detail card
```
| Program Label                              |
| Program Title (script)                     |
| Description text                           |
| Week 1: Title — Description               |
| Week 2: Title — Description               |
| Week 3: Title — Description               |
| Summary text                              |
```
Layout: Single column (6/12 centered), card style
Use for: Service details, course outlines

## Common Page Recipes

### Home Page
```bash
vanjaro blocks scaffold \
  --sections hero,content,cards-3,features-4,testimonials,cta \
  --output home.json
```

### About Page
```bash
vanjaro blocks scaffold \
  --sections hero-simple,content,bio,checklist,cta \
  --output about.json
```

### Services Page
```bash
vanjaro blocks scaffold \
  --sections hero-simple,content,program,program,program,cta \
  --output services.json
```

### Contact Page
```bash
vanjaro blocks scaffold \
  --sections hero-simple,form,cta \
  --output contact.json
```

### Coaching Page
```bash
vanjaro blocks scaffold \
  --sections hero-simple,content,checklist,bio,bio,testimonials,form \
  --output coaching.json
```

## Theming Workflow

After scaffolding pages, apply the site's visual design through theme controls. This is a three-phase process documented in dedicated skills:

### Phase 1: Extract design tokens
Use the **theme-extract-tokens** skill to analyze the design (mockup, Figma, live site) and produce a `design-tokens.json` file with colors, fonts, weights, spacing, and border radius values.

### Phase 2: Map tokens to controls
Use the **theme-control-reference** skill to find the exact LESS variable names for each token. Vanjaro has 838 controls across 16 categories — the reference documents naming patterns, valid values, and known quirks.

### Phase 3: Apply to site
Use the **theme-apply** skill to convert tokens into bulk update JSON files and apply them in the correct order: colors → site globals → fonts → headings → paragraphs → buttons → menu → links.

### Quick example

```bash
# Register a custom font
vanjaro theme register-font --name "Lora" --family "Lora, serif" \
  --import-url "https://fonts.googleapis.com/css2?family=Lora:wght@400;700&display=swap" --json

# Set theme colors
vanjaro theme set-bulk colors.json --json

# Set heading typography
vanjaro theme set-bulk heading-typography.json --json

# Verify
vanjaro theme get --modified --json | jq '.total'
```

## Tips for AI Agents

1. **Always scaffold first, then customize.** Don't try to build component trees by hand.
2. **Use `blocks tree` to inspect.** After pushing content, verify the structure.
3. **Use `content diff` before publishing.** Check what changed.
4. **Use `content snapshot` before major changes.** Easy rollback if something goes wrong.
5. **Global blocks (header/footer) are shared.** Edit them via `global-blocks update`, not per-page.
6. **Styles are separate from components.** The `styles` array in the JSON controls CSS rules.
7. **IDs are auto-generated.** The scaffold command creates unique IDs for each component.
