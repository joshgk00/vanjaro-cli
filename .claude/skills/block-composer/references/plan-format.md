# Library Plan Format

The plan file is a JSON array consumed by `vanjaro blocks build-library --plan <file>`.

## Schema

```json
[
  {
    "template": "Centered Hero",
    "name": "Homepage Hero",
    "category": "Heroes",
    "type": "custom",
    "overrides": {
      "heading_1": "Welcome to Our Site",
      "text_1": "We help businesses grow with modern solutions.",
      "button_1": "Get Started",
      "button_1_href": "#contact"
    }
  }
]
```

## Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `template` | Yes | string | Template name (case-insensitive match against catalog) |
| `name` | Yes | string | Display name for the registered block in the editor sidebar |
| `category` | No | string | Sidebar category; defaults to the template's category |
| `type` | No | `"custom"` or `"global"` | Block type. Default: `"custom"`. Use `"global"` only for header/footer. |
| `overrides` | No | object | Content overrides keyed by slot name |

## Override Slot Naming

Slots follow the pattern `{type}_{n}` or `{type}_{n}_{attr}`:

- **Content slots**: `heading_1`, `text_1`, `button_1` — replace the text content
- **Attribute slots**: `button_1_href`, `image_1_src`, `image_1_alt` — replace specific attributes

Slot numbering is 1-based, ordered by document position (top-to-bottom, left-to-right).

## Block Type Guidance

| Type | When to use | Behavior |
|------|-------------|----------|
| `custom` | Most blocks — heroes, cards, CTAs, content sections | Each drag creates an independent copy. Users edit freely per page. |
| `global` | Header, footer, site-wide banners | Single shared instance. Editing updates all pages. |

Rule of thumb: if it should look different on different pages, it's `custom`. If it must stay identical everywhere, it's `global`.

## Validation

The CLI validates:
- Each entry has `template` and `name`
- `type` is `"custom"` or `"global"`
- `overrides` is an object (if present)
- Template name resolves to a file in the catalog

## Execution

```bash
# Preview what would be created
vanjaro blocks build-library --plan library-plan.json --dry-run

# Write composed JSON files without registering
vanjaro blocks build-library --plan library-plan.json --output-dir ./composed/

# Register all blocks on the live site
vanjaro blocks build-library --plan library-plan.json
```
