# Theme -- vanjaro-cli

Theme design controls (colors, fonts, spacing) via the VanjaroAI AIDesign API. A typical Vanjaro site exposes 838 controls across 16 categories. Changes trigger SCSS recompilation on the server.

## Commands

### `vanjaro theme get [OPTIONS]`

Show all theme design controls and their current values.

**Options:**
- `--category, -c TEXT` -- Filter controls by category (case-insensitive)
- `--modified` -- Show only controls with non-default values
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro theme get --json
vanjaro theme get --category "Colors" --json
vanjaro theme get --modified --json
vanjaro theme get --category "Typography" --modified --json
```

**JSON output:**
```json
{
  "theme_name": "starter-theme",
  "controls": [
    {
      "guid": "a1b2c3d4-...",
      "category": "Colors",
      "title": "Primary Color",
      "type": "Color Picker",
      "lessVariable": "@primary-color",
      "currentValue": "#3498db",
      "defaultValue": "#2c3e50"
    }
  ],
  "available_fonts": ["Open Sans", "Roboto", "Lato"],
  "total": 838
}
```

**Human output:**
```
Theme: starter-theme (838 controls)

category   title            type           current    default
Colors     Primary Color    Color Picker   #3498db    #2c3e50
Colors     Secondary Color  Color Picker   #e74c3c    #e74c3c
Typography Heading Font     Fonts          Roboto     Open Sans
```

Control types include: Color Picker, Slider, Dropdown, Fonts.

---

### `vanjaro theme set [OPTIONS]`

Update a single theme control value. Identify the control by GUID or LESS variable name.

**Options:**
- `--guid, -g TEXT` -- Control GUID to update
- `--variable, -v TEXT` -- LESS variable name to update
- `--value, -V TEXT` -- New value for the control (required)
- `--json` -- Output as JSON

One of `--guid` or `--variable` is required.

**Example:**
```bash
vanjaro theme set --guid a1b2c3d4-... --value "#ff5733" --json
vanjaro theme set --variable "@primary-color" --value "#ff5733" --json
```

**JSON output:**
```json
{
  "status": "updated",
  "control": "a1b2c3d4-...",
  "value": "#ff5733"
}
```

---

### `vanjaro theme set-bulk FILE [OPTIONS]`

Update multiple theme controls from a JSON file.

**Arguments:**
- `FILE` -- Path to a JSON file containing control updates (required)

**Options:**
- `--json` -- Output as JSON

The file accepts two formats:

**Raw array:**
```json
[
  {"guid": "a1b2c3d4-...", "value": "#ff5733"},
  {"lessVariable": "@heading-font", "value": "Roboto"}
]
```

**Wrapped object:**
```json
{
  "controls": [
    {"guid": "a1b2c3d4-...", "value": "#ff5733"},
    {"lessVariable": "@heading-font", "value": "Roboto"}
  ]
}
```

Each control object must include `value` and either `guid` or `lessVariable`.

**Example:**
```bash
vanjaro theme set-bulk theme-updates.json --json
```

**JSON output:**
```json
{
  "status": "updated",
  "count": 2
}
```

---

### `vanjaro theme register-font [OPTIONS]`

Register a custom font for use in theme settings. Supports Google Fonts via an import URL or raw CSS for self-hosted fonts.

**Options:**
- `--name, -n TEXT` -- Font display name, e.g., "Raleway" (required)
- `--family, -f TEXT` -- CSS font-family value, e.g., "Raleway, sans-serif" (required)
- `--import-url TEXT` -- Google Fonts import URL
- `--css TEXT` -- Raw CSS for loading the font (takes precedence over `--import-url`)
- `--json` -- Output as JSON

**Example:**
```bash
# Google Fonts
vanjaro theme register-font \
  --name "Raleway" \
  --family "Raleway, sans-serif" \
  --import-url "https://fonts.googleapis.com/css2?family=Raleway:wght@400;700" \
  --json

# Self-hosted font with raw CSS
vanjaro theme register-font \
  --name "CustomFont" \
  --family "CustomFont, sans-serif" \
  --css "@font-face { font-family: 'CustomFont'; src: url('/fonts/custom.woff2'); }" \
  --json
```

**JSON output (new font):**
```json
{
  "name": "Raleway",
  "family": "Raleway, sans-serif"
}
```

**Human output (already registered):**
```
Font 'Raleway' is already registered.
```

---

### `vanjaro theme reset [OPTIONS]`

Reset all theme settings to defaults. This is destructive and cannot be undone.

**Options:**
- `--force` -- Skip confirmation prompt
- `--json` -- Output as JSON

Without `--force`, prompts for confirmation before proceeding.

**Example:**
```bash
vanjaro theme reset --force --json
```

**JSON output:**
```json
{
  "status": "reset"
}
```

---

## Workflows

### Preflight Before Any Theme Change

```bash
# Theme changes only affect pages that are actually on the Vanjaro shell
vanjaro pages shell --json | jq '.[] | select(.shell != "vanjaro") | {id, name, shell, skin_src}'

# Normalize a page if needed before applying theme settings
vanjaro pages shell 42 --fix --json
```

### Browse and Modify a Color

```bash
# List all color controls
vanjaro theme get --category "Colors" --json

# Pick a control and update it by GUID
vanjaro theme set --guid a1b2c3d4-... --value "#e74c3c" --json

# Or update by LESS variable name
vanjaro theme set --variable "@primary-color" --value "#e74c3c" --json

# Verify the change
vanjaro theme get --modified --json
```

### Change Fonts

```bash
# See available fonts and current font controls
vanjaro theme get --category "Typography" --json

# The JSON output includes available_fonts — pick from that list
# Update a font control
vanjaro theme set --variable "@heading-font" --value "Roboto" --json
```

### Bulk Theme Update from File

```bash
# Export modified controls as a starting point
vanjaro theme get --modified --json | jq '.controls | [.[] | {guid: .guid, value: .currentValue}]' > theme-snapshot.json

# Edit the file with desired values, then apply
vanjaro theme set-bulk theme-snapshot.json --json
```

### Register a Google Font

```bash
# Register the font
vanjaro theme register-font \
  --name "Poppins" \
  --family "Poppins, sans-serif" \
  --import-url "https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700" \
  --json

# Now assign it to a font control
vanjaro theme set --variable "@heading-font" --value "Poppins" --json
```

### Reset to Defaults

```bash
# Review what has been customized
vanjaro theme get --modified --json

# Save a backup before resetting
vanjaro theme get --modified --json | jq '.controls | [.[] | {guid: .guid, value: .currentValue}]' > theme-backup.json

# Reset everything
vanjaro theme reset --force --json

# If needed later, restore from backup
vanjaro theme set-bulk theme-backup.json --json
```

---

### `vanjaro theme css get [OPTIONS]`

Show the current site-wide custom CSS (portal.css). This is the global stylesheet — classes defined here apply to every page on the site.

**Options:**
- `--output, -o FILE` -- Write CSS to a file instead of stdout
- `--json` -- Output as JSON

**Example:**
```bash
# View current custom CSS
vanjaro theme css get

# Export to file
vanjaro theme css get --output portal.css

# JSON output with content and length
vanjaro theme css get --json
```

**JSON output:**
```json
{
  "status": "ok",
  "css": ".card-hover-lift { transition: transform 0.3s; }\n",
  "length": 50
}
```

---

### `vanjaro theme css update --file FILE [OPTIONS]`

Replace the entire site-wide custom CSS with the contents of a file. This overwrites `portal.css` and clears the client resource cache.

**Options:**
- `--file, -f FILE` -- CSS file to upload (required)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro theme css update --file custom-styles.css --json
```

---

### `vanjaro theme css append --file FILE [OPTIONS]`

Append CSS from a file to the existing site-wide custom CSS without replacing what's already there.

**Options:**
- `--file, -f FILE` -- CSS file to append (required)
- `--json` -- Output as JSON

**Example:**
```bash
# Add card hover classes to existing CSS
vanjaro theme css append --file card-classes.css --json
```

---

### Custom CSS Workflow

The global stylesheet (`portal.css`) is the right place for:
- Reusable component classes (card hovers, button variants, section backgrounds)
- Bootstrap 5 extensions (utility classes that compose with BS5)
- Design-specific overrides (gradients, animations, transitions)

**Best practice:** Define classes in `portal.css`, then reference them on components via the `--classes` option in `blocks add` or in content JSON.

```bash
# 1. Define reusable classes
vanjaro theme css update --file site-classes.css --json

# 2. Add a component that uses those classes
vanjaro blocks add 42 --type section --classes "card-hover-lift,accent-gradient-top" --json
```

Classes in `portal.css` are available site-wide — no need to duplicate per page.

---

## Error Handling

- "Provide --guid or --variable to identify the control": The `set` command requires at least one identifier. Use `theme get --json` to find the GUID or LESS variable name.
- "Each control must have a 'value' key": Every entry in the bulk file needs a `value` field.
- "Each control must have a 'guid' or 'lessVariable' key": Every entry in the bulk file needs an identifier. Use `theme get --json` to find valid GUIDs or variable names.
- "No controls found in file": The JSON file is empty or malformed. Must be either a JSON array or an object with a `controls` array.
- "Cannot read FILE": The file path does not exist or contains invalid JSON.
- Confirmation prompt on `reset`: Use `--force` to skip in scripts. Reset cannot be undone -- back up modified controls first.
- 404 on any theme endpoint: The VanjaroAI module is not installed. These endpoints require Vanjaro.AI.dll.
- 401/403 errors: Re-authenticate with `vanjaro auth login`.
