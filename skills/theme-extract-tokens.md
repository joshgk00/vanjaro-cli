# Theme: Extract Design Tokens — vanjaro-cli

How to analyze a design (mockup, Figma export, CSS file, or live site) and produce a standardized design tokens document that maps to Vanjaro theme controls.

## When to Use

Use this skill when starting theme work on a new site. The output is a `design-tokens.json` file that feeds into the `theme-apply` workflow.

## What to Extract

Scan the design for these categories, in order:

### 1. Colors

Identify the site's color palette. Map each color to its role:

| Role | Maps to LESS Variable | Notes |
|------|----------------------|-------|
| Primary brand color | `$primarycolor` | Main accent, headers, links |
| Secondary brand color | `$secondarycolor` | Supporting accent |
| Tertiary / highlight | `$tertiary` | Decorative elements |
| Light background | `$lightcolor` | Section backgrounds, cards |
| Dark / text color | `$darkcolor` | Body text, dark sections |

Vanjaro also has `$quaternary`, `$successcolor`, `$infocolor`, `$warningcolor`, `$dangercolor` — set these only if the design explicitly uses them. Otherwise leave as defaults.

### 2. Fonts

Identify distinct font families used in the design:

| Element | What to look for |
|---------|-----------------|
| Body text | The font used for paragraphs, form labels, general content |
| Headings | The font used for h1-h6 elements — often a different family |
| Buttons | Usually matches body font, but check |
| Navigation | Usually matches body font |
| Decorative | Script fonts, display fonts used for accents — these need custom CSS, not theme controls |

**For each font, note:**
- Font family name (e.g., "Lora")
- CSS font-family value (e.g., "Lora, serif")
- Weight range needed (e.g., 400, 600, 700)
- Google Fonts URL or source

### 3. Font Weights

Map each element type to a weight:

| Element | Common values | Maps to |
|---------|--------------|---------|
| Body text | 400 (normal) | Paragraph font-weight controls (P1-P10) |
| Headings | 700 (bold) | Heading font-weight controls (H1-H10) |
| Buttons | 700 (bold) | Button font-weight controls (B1-B10) |
| Nav links | 700 (bold) or 400 | Menu font-weight controls |

**Available font-weight values in Vanjaro:** 100 (Thin), 300 (Light), 400 (Normal), 500 (Medium), 700 (Bold), 900 (Ultra Bold). If the design specifies 600, use 700. If it specifies 200, use 300.

### 4. Spacing & Border Radius

| Property | What to measure | Maps to |
|----------|----------------|---------|
| Site border radius | Default rounded corners on cards, inputs | `$siteBorderRadius` (0-100px) |
| Button border radius | Button rounding — 0 = square, 30+ = pill | Button `BorderRadius` controls (B1-B10) |
| Button padding | Top/bottom and left/right padding | Button `paddingt/b/L/R` controls |

### 5. Menu Styling

| Property | What to look for | Maps to |
|----------|-----------------|---------|
| Nav font size | Usually 14-16px | `$fontsize` (Menu Style 1) |
| Nav font weight | Bold vs normal | `$fontweight` |
| Nav link color | Text color of nav items | `$color` |
| Nav hover color | Color on hover | `$hovercolor` |
| Nav active color | Color when active/current | `$activecolor` |

## Output Format

Produce a `design-tokens.json` file:

```json
{
  "site_name": "Example Site",
  "extracted_from": "figma export / mockup / live site URL",

  "fonts": {
    "register": [
      {
        "name": "Lora",
        "family": "Lora, serif",
        "import_url": "https://fonts.googleapis.com/css2?family=Lora:wght@400;700&display=swap"
      }
    ],
    "assignments": {
      "site": "Lato, sans-serif",
      "headings": "Lora, serif",
      "paragraphs": "Lato, sans-serif",
      "buttons": "Lato, sans-serif",
      "menu": "Lato, sans-serif",
      "links": "Lato, sans-serif"
    }
  },

  "colors": {
    "$primarycolor": "#C75B8E",
    "$secondarycolor": "#7EBEC5",
    "$tertiary": "#EC72A7",
    "$lightcolor": "#FDF2F6",
    "$darkcolor": "#3D3D3D"
  },

  "typography": {
    "heading_weight": "700",
    "paragraph_weight": "400",
    "button_weight": "700",
    "menu_weight": "700"
  },

  "spacing": {
    "site_border_radius": "12",
    "button_border_radius": "30",
    "button_padding_top": "12",
    "button_padding_bottom": "12",
    "button_padding_left": "28",
    "button_padding_right": "28"
  },

  "menu": {
    "font_size": "14",
    "link_color": "$darkcolor",
    "hover_color": "$primarycolor",
    "active_color": "$primarycolor"
  },

  "custom_css_needed": [
    "Decorative/script font (cannot be set via theme controls, needs @font-face + class-based CSS)",
    "Hero gradients",
    "Card hover effects",
    "Any component-specific styling beyond global theme controls"
  ]
}
```

## Font Registration

Before applying theme controls, register any fonts not already available:

```bash
# Check what's available
vanjaro theme get --json | jq '.available_fonts'

# Register missing fonts
vanjaro theme register-font \
  --name "Lora" \
  --family "Lora, serif" \
  --import-url "https://fonts.googleapis.com/css2?family=Lora:wght@400;700&display=swap" \
  --json
```

Register fonts **before** setting font family controls — the value must match a registered font name.

## What Theme Controls Cannot Do

These require custom CSS injected separately:

- Decorative/script fonts applied to specific elements (theme controls set fonts globally per heading/paragraph/button level)
- Gradient backgrounds
- Hover animations and transitions
- Navbar transparency or blur effects
- Footer-specific dark theme styling
- Component-specific overrides (e.g., one section with different colors)
- Sticky elements
- Custom shadows beyond border-radius

Note these in the `custom_css_needed` array so they're tracked separately.

## Next Step

Once you have `design-tokens.json`, use the **theme-apply** workflow to convert it into bulk update files and apply to the site.
