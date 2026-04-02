# Build Page from Design — vanjaro-cli

Step-by-step workflow for translating a design mockup into a live Vanjaro page.

## When to Use

Use this workflow when you have:
- An HTML mockup file
- A screenshot or design description
- A list of sections and content to put on a page

## Before You Start

Ensure your session is active:
```bash
vanjaro auth status
# If not authenticated:
vanjaro auth login
vanjaro api-key generate
```

If building a brand new site, set up the foundation first (see `design.md` for the full setup order):
```bash
# 1. Branding
vanjaro branding update --site-name "Site Name" --footer-text "Copyright 2026..."

# 2. Register fonts (if the design uses custom fonts)
vanjaro theme register-font --name "Lora" --family "Lora, serif" \
  --import-url "https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&display=swap"

# 3. Theme colors (find control GUIDs first)
vanjaro theme get --category "Site" --json | jq '.controls[] | {guid, title}'
vanjaro theme set --guid "GUID-HERE" --value "#336699"
```

## Workflow

### Phase 1: Analyze the design

Before writing any commands, break the design into sections. Identify:

1. **Page type** — home, about, services, contact, etc.
2. **Sections** — list each section top to bottom
3. **Section pattern** for each — match to a scaffold type (hero, cards-3, bio, content, cta, etc.)
4. **Content** — extract headings, paragraphs, button labels, image references
5. **Layout** — column counts, widths, alignment

### Phase 2: Create the page

```bash
# Create the page
vanjaro pages create --title "Page Name" --json

# Note the page ID from the response
```

### Phase 3: Scaffold the layout

```bash
# Generate the base layout
vanjaro blocks scaffold --sections hero,content,cards-3,testimonials,cta --output layout.json
```

### Phase 4: Customize the content

Edit `layout.json` to replace placeholder text with real content from the design. The file structure is:

```json
{
  "components": [
    {
      "type": "section",
      "components": [
        {
          "type": "grid",
          "components": [
            {
              "type": "row",
              "components": [
                {
                  "type": "column",
                  "components": [
                    {"type": "heading", "content": "REPLACE WITH REAL HEADING"},
                    {"type": "text", "content": "REPLACE WITH REAL TEXT"}
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "styles": []
}
```

Key fields to customize:
- `"content"` — the visible text/HTML of each component
- `"classes"` — CSS classes for styling
- Component structure — add/remove components to match the design

### Phase 5: Push and verify

```bash
# Push the customized content
vanjaro content update PAGE_ID --file layout.json

# Verify the structure
vanjaro blocks tree PAGE_ID

# Check what it looks like
vanjaro content get PAGE_ID --json | jq '.components | length'

# Publish when satisfied
vanjaro content publish PAGE_ID
```

### Phase 6: Iterate

```bash
# Snapshot before making changes
vanjaro content snapshot PAGE_ID

# Add a missing block
vanjaro blocks add PAGE_ID --type text --content "New paragraph" --parent SECTION_ID

# Remove an unwanted block
vanjaro blocks remove PAGE_ID COMPONENT_ID --force

# Check diff before publishing
vanjaro content diff PAGE_ID

# Publish
vanjaro content publish PAGE_ID
```

## Section Pattern Reference

| Pattern | Use For | Columns |
|---------|---------|---------|
| `hero` | Landing page hero with CTA | 2 (6/6) |
| `hero-simple` | Interior page header | 1 centered |
| `content` | Body text, mission statement | 1 (8/12 centered) |
| `cards-3` | Services, features | 3 (4/4/4) |
| `testimonials` | Quotes, reviews | 3 (4/4/4) |
| `bio` | About, team member | 2 (5/7) |
| `checklist` | Feature list with CTA | 1 (8/12 centered) |
| `cta` | Call to action | 1 centered |
| `form` | Contact, booking | 2 (8/4) |
| `features-4` | Value props | 4 (3/3/3/3) |
| `program` | Course/service detail | 1 (8/12 centered) |

## Example: Building a Home Page

Given this design:
- Hero with welcome message + video placeholder
- Mission statement strip
- "Who is this for" section with checklist
- 3 service cards
- 3 testimonials
- CTA to book a call

```bash
# 1. Create the page
vanjaro pages create --title "Home" --json
# Returns: {"status": "created", "page": {"id": 99}}

# 2. Scaffold
vanjaro blocks scaffold \
  --sections hero,content,checklist,cards-3,testimonials,cta \
  --output home.json

# 3. Edit home.json with real content (use your editor or script)

# 4. Push
vanjaro content update 99 --file home.json

# 5. Verify
vanjaro blocks tree 99

# 6. Publish
vanjaro content publish 99
```

## Example: Building from HTML Mockup

When given an HTML file, follow this process:

1. Read the HTML file
2. Identify each `<section>` tag — each becomes a section in the scaffold
3. For each section, determine the column layout from Bootstrap grid classes
4. Extract the text content from headings, paragraphs, buttons
5. Map to the closest scaffold pattern
6. Generate the layout JSON with real content
7. Push to the page

## Tips

- **Start with scaffold, then customize.** Don't build JSON from scratch.
- **Use `blocks tree` often.** It shows the component hierarchy with IDs you need for add/remove.
- **Snapshot before big changes.** Easy rollback if something goes wrong.
- **One page at a time.** Build, verify, publish, then move to the next page.
- **Global blocks (header/footer) are shared.** Edit via `global-blocks update`, not per-page.
- **Content update creates a draft.** Nothing goes live until you `content publish`.
