# Theme: Apply Design Tokens — vanjaro-cli

How to take a `design-tokens.json` file and apply it to a Vanjaro site via the CLI. This is the execution phase after token extraction.

## Prerequisites

1. Authenticated session: `vanjaro auth status --json`
2. API key set: `vanjaro api-key status --json`
3. Pages on Vanjaro shell: `vanjaro pages shell --json`
4. Design tokens extracted (see **theme-extract-tokens** skill)

## Application Order

Apply theme changes in this order. Each step builds on the previous — colors first because other controls reference them.

### Step 1: Site Colors

```bash
# Build the colors file from your design-tokens.json
cat > colors.json << 'EOF'
[
  {"lessVariable": "$primarycolor", "value": "#C75B8E"},
  {"lessVariable": "$secondarycolor", "value": "#7EBEC5"},
  {"lessVariable": "$tertiary", "value": "#EC72A7"},
  {"lessVariable": "$lightcolor", "value": "#FDF2F6"},
  {"lessVariable": "$darkcolor", "value": "#3D3D3D"}
]
EOF

vanjaro theme set-bulk colors.json --json
```

**Why first:** Many controls default to `$primarycolor`, `$secondarycolor`, etc. Setting these first ensures correct cascade.

### Step 2: Site Font & Border Radius

```bash
cat > site-globals.json << 'EOF'
[
  {"lessVariable": "$siteFontFamily", "value": "Lato, sans-serif"},
  {"lessVariable": "$siteBorderRadius", "value": "12"}
]
EOF

vanjaro theme set-bulk site-globals.json --json
```

### Step 3: Register Custom Fonts

Register any fonts not in Vanjaro's default list **before** setting font family controls.

```bash
# Check available fonts
vanjaro theme get --json | jq '.available_fonts'

# Register if missing
vanjaro theme register-font \
  --name "Lora" \
  --family "Lora, serif" \
  --import-url "https://fonts.googleapis.com/css2?family=Lora:wght@400;700&display=swap" \
  --json
```

### Step 4: Heading Typography (H1-H10)

Set font family and weight for all 10 heading styles. Discover exact variable names first:

```bash
# Get current heading controls
vanjaro theme get --category "Heading" --json | \
  jq '.controls[] | select(.title == "Font Family" or .title == "Font Weight") | {lessVariable, currentValue}'
```

Build the bulk file. Example for Lora serif, bold:

```json
[
  {"lessVariable": "$hsoneFontFamily", "value": "Lora, serif"},
  {"lessVariable": "$HSoneFontWeight", "value": "700"},
  {"lessVariable": "$hstwoFontFamily", "value": "Lora, serif"},
  {"lessVariable": "$hstwoFontWeight", "value": "700"},
  {"lessVariable": "$hsThreeFontFamily", "value": "Lora, serif"},
  {"lessVariable": "$HSThreeFontWeight", "value": "700"}
]
```

**Important:** Heading font-weight variables use uppercase `$HS` prefix while font-family uses lowercase `$hs`. Always verify with `theme get`.

See **theme-control-reference** for the full prefix map (H1-H10).

### Step 5: Paragraph Typography (P1-P10)

Same pattern as headings. Usually matches the site font:

```bash
vanjaro theme get --category "Text" --json | \
  jq '.controls[] | select(.title == "Font Family" or .title == "Font Weight") | {lessVariable, currentValue}'
```

### Step 6: Button Styling (B1-B10)

Buttons have font, weight, border-radius, and padding:

```json
[
  {"lessVariable": "$bsoneFontFamily", "value": "Lato, sans-serif"},
  {"lessVariable": "$bsoneFontWeight", "value": "700"},
  {"lessVariable": "$bsoneBorderRadius", "value": "30"},
  {"lessVariable": "$bsonepaddingt", "value": "12"},
  {"lessVariable": "$bsonepaddingb", "value": "12"},
  {"lessVariable": "$bsonepaddingL", "value": "28"},
  {"lessVariable": "$bsonepaddingR", "value": "28"}
]
```

Repeat for B2-B10. See **theme-control-reference** for prefix map and the B5/B4 border-radius bug.

### Step 7: Menu Styling

```bash
# Discover menu controls
vanjaro theme get --category "Menu" --json | \
  jq '.controls[] | select(.title | test("font|color|size"; "i")) | {title, lessVariable, currentValue}'
```

```json
[
  {"lessVariable": "$color", "value": "$darkcolor"},
  {"lessVariable": "$hovercolor", "value": "$primarycolor"},
  {"lessVariable": "$activecolor", "value": "$primarycolor"},
  {"lessVariable": "$fontsize", "value": "14"},
  {"lessVariable": "$fontweight", "value": "700"},
  {"lessVariable": "$menufontfamily", "value": "Lato, sans-serif"},
  {"lessVariable": "$submenufontfamily", "value": "Lato, sans-serif"}
]
```

**Note:** Menu color values can reference site variables (e.g., `$darkcolor`) — Vanjaro resolves them at compile time.

### Step 8: Link Styling

```json
[
  {"lessVariable": "$linkNormalFontFamily", "value": "Lato, sans-serif"},
  {"lessVariable": "$linkHoverFontFamily", "value": "Lato, sans-serif"},
  {"lessVariable": "$linkActiveFontFamily", "value": "Lato, sans-serif"}
]
```

## Generating Bulk Files Programmatically

For styles with 10 numbered variants (H1-H10, P1-P10, B1-B10), use the control reference prefix map and build the JSON programmatically rather than by hand:

```python
import json

# From theme-control-reference prefix map
HEADING_PREFIXES = {
    1: "hsone", 2: "hsTwo", 3: "hsThree", 4: "hsFour", 5: "hsFive",
    6: "hsSix", 7: "hsSev", 8: "hsEth", 9: "hsNine", 10: "hsTen"
}
# Font weight uses different casing
HEADING_WEIGHT_PREFIXES = {
    1: "HSone", 2: "hsTwo", 3: "HSThree", 4: "HSFour", 5: "HSFive",
    6: "HSSix", 7: "HsSev", 8: "HSEth", 9: "HSNine", 10: "HSTen"
}

controls = []
for n in range(1, 11):
    controls.append({"lessVariable": f"${HEADING_PREFIXES[n]}FontFamily", "value": "Lora, serif"})
    controls.append({"lessVariable": f"${HEADING_WEIGHT_PREFIXES[n]}FontWeight", "value": "700"})

with open("heading-typography.json", "w") as f:
    json.dump(controls, f, indent=2)
```

**Always verify generated variable names** against `theme get` output before applying. The naming is irregular enough that typos are easy to introduce.

## Verification

After applying all steps:

```bash
# Count modified controls
vanjaro theme get --modified --json | jq '.total'

# Review all changes
vanjaro theme get --modified --json | jq '.controls[] | {category, title, lessVariable, currentValue}'

# Spot-check specific categories
vanjaro theme get --category "Button" --modified --json
```

**Expected control counts by category for a typical theme application:**

| Category | Controls set | What's covered |
|----------|-------------|----------------|
| Site | 5-7 | Colors + font + border radius |
| Heading | 20 | Font family + weight for H1-H10 |
| Text | 10-20 | Font family (+ weight if non-default) for P1-P10 |
| Button | 50-70 | Font + weight + border radius + padding for B1-B10 |
| Menu | 5-15 | Nav colors + font + size + weight |
| Link | 3-6 | Font family per state |
| **Total** | **~100-130** | Core design applied |

## Troubleshooting

### CSS compilation breaks after set-bulk

If the site CSS breaks after applying controls:

1. Check if the site still loads — a broken compile usually means white/unstyled page
2. Apply controls one category at a time to isolate the problem
3. Common cause: invalid value for a control type (e.g., text where a number is expected)
4. Reset and reapply: `vanjaro theme reset --force --json` then re-run bulk files

### Font not available after registration

1. Verify registration: `vanjaro theme get --json | jq '.available_fonts'`
2. The `--name` flag must match what you use in font family controls
3. Font family value must include fallback (e.g., "Lora, serif" not just "Lora")

### Control not found errors

1. Variable names are case-sensitive and full of inconsistencies
2. Always copy variable names from `theme get --json` output
3. See **theme-control-reference** for known naming quirks and bugs

## What's Left After Theme Controls

Theme controls cover global typography, colors, and spacing. Everything else needs custom CSS:

- Section-specific background colors/gradients
- Component hover animations
- Navbar transparency/blur
- Dark-themed footer
- Decorative font application to specific elements
- Card shadows and hover effects
- Sticky/floating elements
- Responsive breakpoint overrides
