# Blocks -- vanjaro-cli

Page components (blocks), global reusable blocks, and templates. All commands in this file require the VanjaroAI module (Vanjaro.AI.dll) installed on the DNN site.

## Page Block Commands

### `vanjaro blocks list PAGE_ID [OPTIONS]`

List top-level blocks on a page.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro blocks list 42 --json
```

**JSON output:**
```json
{
  "page_id": 42,
  "version": 3,
  "total": 2,
  "blocks": [
    {
      "component_id": "abc123",
      "guid": "",
      "block_type_guid": "",
      "type": "section",
      "name": "Hero Section",
      "child_count": 3
    }
  ]
}
```

### `vanjaro blocks get PAGE_ID COMPONENT_ID [OPTIONS]`

Get details for a specific block/component.

**Options:**
- `--output, -o PATH` -- Write block JSON to file
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro blocks get 42 abc123 --json
vanjaro blocks get 42 abc123 --output block.json
```

**JSON output:**
```json
{
  "page_id": 42,
  "version": 3,
  "component_id": "abc123",
  "guid": "",
  "block_type_guid": "",
  "type": "section",
  "name": "Hero Section",
  "content_json": {},
  "style_json": []
}
```

### `vanjaro blocks tree PAGE_ID [OPTIONS]`

Show the full component tree for a page. Displays the hierarchy of all components with their types, IDs, and nesting depth.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro blocks tree 42 --json
```

**JSON output:**
```json
[
  {
    "id": "root-1",
    "type": "wrapper",
    "name": "",
    "content_preview": "",
    "depth": 0
  },
  {
    "id": "abc123",
    "type": "text",
    "name": "",
    "content_preview": "Hello world",
    "depth": 1
  }
]
```

**Human output:**
```
wrapper [root-1]
  text [abc123] -- Hello world
  image [img-1]
```

### `vanjaro blocks add PAGE_ID [OPTIONS]`

Add a component to a page. Fetches current content, inserts the component, and saves as draft.

**Options:**
- `--type, -t TEXT` -- Component type (required: section, text, heading, image, etc.)
- `--content, -c TEXT` -- Text content for the component
- `--parent, -p TEXT` -- Parent component ID (default: root level)
- `--position INT` -- Insert position (-1 = append, default)
- `--classes TEXT` -- Comma-separated CSS class names
- `--locale, -l TEXT` -- Locale code (default: `en-US`)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro blocks add 42 --type heading --content "Welcome" --json
vanjaro blocks add 42 --type text --content "Body text" --parent abc123 --position 0 --json
vanjaro blocks add 42 --type section --classes "container,py-5" --json
```

**JSON output:**
```json
{
  "status": "added",
  "page_id": 42,
  "component_id": "new-comp-id",
  "version": 4
}
```

### `vanjaro blocks remove PAGE_ID COMPONENT_ID [OPTIONS]`

Remove a component from a page. Saves as draft.

**Options:**
- `--force` -- Skip confirmation prompt
- `--locale, -l TEXT` -- Locale code (default: `en-US`)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro blocks remove 42 abc123 --force --json
```

**JSON output:**
```json
{
  "status": "removed",
  "page_id": 42,
  "component_id": "abc123",
  "version": 4
}
```

---

## Global Block Commands

Global blocks are reusable components shared across pages (e.g., Header, Footer). They are identified by GUID.

### `vanjaro global-blocks list [OPTIONS]`

List all global blocks.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro global-blocks list --json
```

**JSON output:**
```json
[
  {
    "id": 1,
    "guid": "a1b2c3d4-...",
    "name": "Header",
    "category": "Layout",
    "is_published": true,
    "version": 2,
    "updated_on": "2024-01-15T10:30:00"
  }
]
```

### `vanjaro global-blocks get GUID [OPTIONS]`

Fetch a global block by GUID.

**Options:**
- `--output, -o PATH` -- Write block JSON to file
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro global-blocks get a1b2c3d4-... --json
vanjaro global-blocks get a1b2c3d4-... --output header.json
```

**JSON output:**
```json
{
  "id": 1,
  "guid": "a1b2c3d4-...",
  "name": "Header",
  "category": "Layout",
  "version": 2,
  "is_published": true,
  "content_json": [],
  "style_json": []
}
```

### `vanjaro global-blocks update GUID [OPTIONS]`

Update a global block from a JSON file.

**Options:**
- `--file, -f PATH` -- JSON file containing contentJSON and styleJSON (required)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro global-blocks update a1b2c3d4-... --file header.json --json
```

**Input format:**
```json
{
  "content_json": [],
  "style_json": []
}
```

Also accepts `contentJSON` / `styleJSON` keys.

**JSON output:**
```json
{
  "status": "updated",
  "guid": "a1b2c3d4-..."
}
```

### `vanjaro global-blocks publish GUID [OPTIONS]`

Publish the latest draft of a global block.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro global-blocks publish a1b2c3d4-... --json
```

### `vanjaro global-blocks delete GUID [OPTIONS]`

Delete a global block.

**Options:**
- `--force` -- Skip confirmation prompt
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro global-blocks delete a1b2c3d4-... --force --json
```

---

## Template Commands

### `vanjaro templates list [OPTIONS]`

List available templates.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro templates list --json
```

**JSON output:**
```json
[
  {
    "name": "Blank",
    "type": "page",
    "is_system": true,
    "has_svg": true
  }
]
```

### `vanjaro templates get NAME [OPTIONS]`

Fetch a template by name.

**Options:**
- `--output, -o PATH` -- Write full template JSON to file
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro templates get "Blank" --json
vanjaro templates get "Landing Page" --output template.json
```

**JSON output:**
```json
{
  "name": "Blank",
  "type": "page",
  "is_system": true,
  "svg": "<svg>...</svg>",
  "content_json": [],
  "style_json": []
}
```

### `vanjaro templates apply PAGE_ID [OPTIONS]`

Apply a template to a page. This replaces existing page content.

**Options:**
- `--template, -t TEXT` -- Template name to apply (required)
- `--force` -- Skip confirmation prompt
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro templates apply 42 --template "Landing Page" --force --json
```

**JSON output:**
```json
{
  "status": "applied",
  "page_id": 42,
  "template_name": "Landing Page"
}
```

## Workflows

### Inspect Page Structure Before Editing

```bash
# See the full component tree
vanjaro blocks tree 42

# Get details on a specific component
vanjaro blocks get 42 abc123 --json
```

### Add Content to a Page

```bash
# Add a heading
vanjaro blocks add 42 --type heading --content "Our Services" --json

# Add body text below it
vanjaro blocks add 42 --type text --content "We offer..." --json

# Publish changes
vanjaro content publish 42
```

### Edit a Global Block

```bash
# Export the header
vanjaro global-blocks get a1b2c3d4-... --output header.json

# Edit header.json

# Push changes
vanjaro global-blocks update a1b2c3d4-... --file header.json

# Publish
vanjaro global-blocks publish a1b2c3d4-...
```

### Apply a Template to a New Page

```bash
# Create the page
vanjaro pages create --title "Landing" --json

# List available templates
vanjaro templates list --json

# Apply template (use the page ID from the create output)
vanjaro templates apply 50 --template "Landing Page" --force --json

# Publish
vanjaro content publish 50
```

### Find Components by Type

```bash
# Get tree as JSON and filter with jq
vanjaro blocks tree 42 --json | jq '[.[] | select(.type == "image")]'
```

## Error Handling

- Version conflict (409) on `blocks add` or `blocks remove`: The page was modified since it was read. Re-run the command to retry with the latest content.
- "Parent component not found" on `blocks add`: The `--parent` ID does not exist in the page. Use `blocks tree` to see valid IDs.
- "Component not found" on `blocks remove`: The component ID does not exist. Use `blocks tree` to see valid IDs.
- Confirmation prompt on `global-blocks delete`, `blocks remove`, `templates apply`: Use `--force` to skip in scripts.
- "Apply template replaces existing content": This is destructive. Export content first with `content get` if you need a backup.
