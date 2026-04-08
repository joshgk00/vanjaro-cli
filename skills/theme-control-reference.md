# Theme: Control Reference — vanjaro-cli

Reference for Vanjaro's 838 theme design controls. Use this when mapping design tokens to LESS variable names for `theme set` or `theme set-bulk`.

## Categories Overview

| Category | Controls | What it affects |
|----------|----------|----------------|
| Site | 12 | Global color palette, site font, border radius |
| Styles: Heading | 120 | H1-H10 typography, spacing, visibility |
| Styles: Text | 120 | P1-P10 paragraph typography, spacing, visibility |
| Styles: Button | 130 | B1-B10 button typography, padding, border radius |
| Styles: Menu | 170 | 2 nav style variants with hamburger, links, submenus |
| Link | 21 | Link states (normal, hover, active) typography |
| Styles: Breadcrumb | 20 | 2 breadcrumb style variants |
| Styles: Language | 22 | 2 language switcher variants |
| Styles: Search Input | 22 | 2 search input variants |
| Styles: Sign In & My Account | 66 | 2 account menu variants |
| Sign In Form | 27 | Login form styling |
| Signup Form | 33 | Registration form styling |
| Search Result | 27 | Search results page |
| Cookie Consent | 19 | Cookie consent banner |
| User Profile | 17 | User profile page |
| Image Gallery | 12 | Gallery component |

## Site (Global) Controls

These are the most impactful controls — they define variables referenced by dozens of other controls.

| LESS Variable | Type | Default | Referenced by |
|---------------|------|---------|--------------|
| `$primarycolor` | Color Picker | `#242623` | 24 controls |
| `$secondarycolor` | Color Picker | `#4A5057` | 24 controls |
| `$tertiary` | Color Picker | `#C86E4C` | — |
| `$quaternary` | Color Picker | `#734BA9` | — |
| `$successcolor` | Color Picker | `#28a745` | — |
| `$infocolor` | Color Picker | `#17a2b8` | — |
| `$warningcolor` | Color Picker | `#ffc107` | — |
| `$dangercolor` | Color Picker | `#dc3545` | — |
| `$lightcolor` | Color Picker | `#f8f9fa` | 3 controls |
| `$darkcolor` | Color Picker | `#343a40` | 3 controls |
| `$siteFontFamily` | Fonts | `Poppins, sans-serif` | — |
| `$siteBorderRadius` | Slider (0-100) | `5` | 22 controls |

**Important:** Many controls default to `$primarycolor`, `$secondarycolor`, or `$siteBorderRadius` as variable references. Changing a Site control cascades to everything referencing it.

## Numbered Style Naming Patterns

Headings (H1-H10), Text (P1-P10), and Buttons (B1-B10) each have 10 numbered styles. The LESS variable prefix for each number is **inconsistent** — you must use the exact prefix.

### Prefix Map

| # | Heading | Text | Button |
|---|---------|------|--------|
| 1 | `hsone` | `psone` | `bsone` |
| 2 | `hsTwo` / `hstwo` | `psTwo` | `bsTwo` |
| 3 | `hsThree` | `psThree` | `bsThree` |
| 4 | `hsFour` | `psFour` | `bsFour` |
| 5 | `hsFive` | `psFive` | `bsFive` |
| 6 | `hsSix` | `psSix` | `bsSix` |
| 7 | `hsSev` | `psSev` | `bsSev` |
| 8 | `hsEth` | `psEth` | `bsEt` |
| 9 | `hsNine` | `psNine` | `bsNn` |
| 10 | `hsTen` | `psTen` | `bsTen` |

**Warning — casing traps:**
- Heading 2 mixes lowercase (`$hstwoFontWeight`) with camelCase (`$hsTwoFontStyle`) in the same style
- Font-weight variables for headings use uppercase `$HS` prefix: `$HSoneFontWeight`, `$HSThreeFontWeight`, etc.
- Button 8 visibility = `$bsEthVisiblity` but properties = `$bsEtFontWeight` (different prefix)
- Button 9 visibility = `$bsNineVisiblity` but properties = `$bsNnFontWeight`

**Best practice:** Always discover variable names via `vanjaro theme get --category "Button" --json` rather than guessing. The naming is not predictable enough to construct programmatically.

### Controls Per Numbered Style

**Heading / Text (12 controls each):**

| Property | Variable suffix | Type |
|----------|----------------|------|
| Visibility | `Visiblity` | Dropdown |
| Font Weight | `FontWeight` | Dropdown |
| Font Family | `FontFamily` | Fonts |
| Font Style | `FontStyle` | Dropdown |
| Letter Spacing | `LetterSpacing` | Slider (0-25px) |
| Word Spacing | `WordSpacing` | Slider (0-25px) |
| Text Transform | `TextTransform` | Dropdown |
| Text Decoration | `TextDecoration` | Dropdown |
| Margin Top | `MTop` | Slider (0-100px) |
| Margin Bottom | `MBottom` | Slider (0-100px) |
| Margin Left | `MLeft` | Slider (0-100px) |
| Margin Right | `MRight` | Slider (0-100px) |

**Button (13 controls each):**

Same as above but replaces margins with:

| Property | Variable suffix | Type |
|----------|----------------|------|
| Border Radius | `BorderRadius` | Slider (0-100px) |
| Padding Top | `paddingt` | Slider (0-100px) |
| Padding Bottom | `paddingb` | Slider (0-100px) |
| Padding Left | `paddingL` | Slider (0-100px) |
| Padding Right | `paddingR` | Slider (0-100px) |

Note: Buttons have 13 controls (extra padding vs margin split). The suffix casing is inconsistent — padding uses lowercase `t`/`b` but uppercase `L`/`R`.

### Building a Variable Name

Combine prefix + suffix. Examples for Button 1:
- Font weight: `$bsoneFontWeight`
- Border radius: `$bsoneBorderRadius`
- Padding left: `$bsonepaddingL`

For Heading 3:
- Font weight: `$HSThreeFontWeight` (note: uppercase `HS` for weight)
- Font family: `$hsThreeFontFamily` (note: lowercase `hs` for family)

**When in doubt, query:** `vanjaro theme get --category "Heading" --json | jq '.controls[] | select(.title == "Font Weight") | .lessVariable'`

## Dropdown Values

### Font Weight
```
100 = Thin
300 = Light
400 = Normal (default for most)
500 = Medium
700 = Bold
900 = Ultra Bold
```

### Visibility
```
inline-flex = Visible (default for styles 1-7)
none        = Hidden (default for styles 8-10)
```

Styles 8-10 are hidden by default. Only set styles 1-7 unless the design needs more than 7 distinct heading/paragraph/button styles.

### Font Style
```
normal
italic
```

### Text Transform
```
none
uppercase
lowercase
capitalize
```

### Text Decoration
```
none
underline
overline
line-through
```

## Menu Controls

Menu has 2 style variants. Style 1 is active by default, Style 2 is hidden.

### Style 1 (Primary Nav) — Key Controls

| Property | LESS Variable | Type | Default |
|----------|--------------|------|---------|
| Nav link color | `$color` | Color Picker | `$darkcolor` |
| Nav hover color | `$hovercolor` | Color Picker | `$primarycolor` |
| Nav active color | `$activecolor` | Color Picker | `$primarycolor` |
| Nav background | `$bgcolor` | Color Picker | transparent |
| Font size | `$fontsize` | Slider (1-100px) | `14` |
| Font weight | `$fontweight` | Dropdown | `400` |
| Font family | `$menufontfamily` | Fonts | `Poppins, sans-serif` |
| Font style | `$menufontstyle` | Dropdown | `normal` |
| Text transform | `$menutexttransform` | Dropdown | `none` |
| Letter spacing | `$menuletterspacing` | Slider (0-25px) | `0` |
| Submenu font family | `$submenufontfamily` | Fonts | `Poppins, sans-serif` |
| Submenu font size | `$submenufontsize` | Slider (1-100px) | `14` |
| Submenu font weight | `$submenufontweight` | Dropdown | `400` |
| Submenu link color | `$submenucolor` | Color Picker | `$darkcolor` |
| Submenu hover color | `$submenuhovercolor` | Color Picker | `$primarycolor` |
| Submenu background | `$submenubackground` | Color Picker | `$lightcolor` |

### Style 2 — Same controls with `$msb` prefix
Example: `$msbcolor`, `$msbfontsize`, `$msbmenufontfamily`

## Link Controls

3 states, 7 controls each:

| Property | Normal | Hover | Active |
|----------|--------|-------|--------|
| Font Family | `$linkNormalFontFamily` | `$linkHoverFontFamily` | `$linkActiveFontFamily` |
| Font Weight | `$linkNormalFontWeight` | `$linkHoverFontWeight` | `$linkActiveFontWeight` |
| Font Style | `$linkNormalFontStyle` | `$linkHoverFontStyle` | `$linkActiveFontStyle` |
| Text Transform | `$linkNormalTextTransform` | `$linkHoverTextTransform` | `$linkActiveTextTransform` |
| Text Decoration | `$linkNormalTextDecoration` | `$linkHoverTextDecoration` | `$linkActiveTextDecoration` |
| Letter Spacing | `$linkNormalLetterSpacing` | `$linkHoverLetterSpacing` | `$linkActiveLetterSpacing` |
| Word Spacing | `$linkNormalWordSpacing` | `$linkHoverWordSpacing` | `$linkActiveWordSpacing` |

## Known Bugs in Control Data

These exist in the Vanjaro theme builder and affect variable resolution:

| Bug | Impact | Workaround |
|-----|--------|------------|
| Button 5 border radius uses `$bsFourBorderRadius` (same as Button 4) | Setting B5 radius actually changes B4 | Use GUID instead of variable name for B5 |
| `$submenubackground` appears twice in Menu Style 1 | Ambiguous resolution | Use GUID for the specific control |
| Heading 2 has typos: `$hstwoLtterSpacing`, `$hsTwotestTransform` | Must use exact typo in variable name | Copy from `theme get` output |
| Heading 2, 3, 5 text decoration options have trailing spaces | May need trailing space in value | Use `theme get` to read current options |
| `Visiblity` is misspelled consistently across all controls | Not a bug to fix — use the misspelling | `$bsoneVisiblity`, not `$bsoneVisibility` |

## Discovery Workflow

When you need to find the right variable for a property:

```bash
# List all controls in a category
vanjaro theme get --category "Button" --json | jq '.controls[] | {title, lessVariable, type, currentValue}'

# Find a specific property across all styles
vanjaro theme get --category "Heading" --json | jq '.controls[] | select(.title == "Font Weight") | {lessVariable, currentValue}'

# See what's been modified from defaults
vanjaro theme get --modified --json
```
