# Content -- vanjaro-cli

Read, write, and publish Vanjaro page content (GrapesJS JSON). These commands require the VanjaroAI module (Vanjaro.AI.dll) installed on the DNN site.

## Commands

### `vanjaro content get PAGE_ID [OPTIONS]`

Fetch the GrapesJS content for a page.

**Options:**
- `--locale, -l TEXT` -- Locale code (default: `en-US`)
- `--draft / --published` -- Include draft content (default: `--draft`)
- `--output, -o PATH` -- Write content JSON to a file instead of stdout
- `--json` -- Output as JSON (default behavior for piped usage)

**Example:**
```bash
vanjaro content get 42 --output page.json
vanjaro content get 42 --published --json
vanjaro content get 42 --locale es-ES --output page-es.json
```

**JSON output:**
```json
{
  "page_id": 42,
  "locale": "en-US",
  "version": 3,
  "is_published": false,
  "components": [
    {
      "type": "wrapper",
      "components": [
        {
          "type": "text",
          "content": "Hello world",
          "attributes": { "id": "abc123" }
        }
      ],
      "attributes": { "id": "root-1" }
    }
  ],
  "styles": [
    { "selectors": ["#abc123"], "style": { "color": "red" } }
  ]
}
```

### `vanjaro content update PAGE_ID [OPTIONS]`

Replace the GrapesJS content for a page. Creates a new draft version -- use `content publish` to make it live.

Reads from `--file` if provided, otherwise reads JSON from stdin.

**Options:**
- `--file, -f PATH` -- JSON file containing components and styles
- `--locale, -l TEXT` -- Locale code (default: `en-US`)
- `--version, -v INT` -- Expected version for optimistic conflict detection
- `--json` -- Output as JSON

**Example:**
```bash
# From file
vanjaro content update 42 --file page.json --json

# From stdin
cat page.json | vanjaro content update 42

# With version check
vanjaro content update 42 --file page.json --version 3
```

**JSON output:**
```json
{
  "status": "updated",
  "page_id": 42,
  "version": 4
}
```

**Input format:**
The update command accepts the same JSON shape returned by `content get`:
```json
{
  "components": [ ... ],
  "styles": [ ... ]
}
```

### `vanjaro content publish PAGE_ID [OPTIONS]`

Publish the latest draft version of a page.

**Options:**
- `--locale, -l TEXT` -- Locale code (default: `en-US`)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro content publish 42 --json
```

**JSON output:**
```json
{
  "status": "published",
  "page_id": 42
}
```

### `vanjaro content diff PAGE_ID [OPTIONS]`

Compare draft vs published content for a page. Shows component additions/removals and style changes.

**Options:**
- `--locale, -l TEXT` -- Locale code (default: `en-US`)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro content diff 42 --json
```

**JSON output:**
```json
{
  "page_id": 42,
  "published_version": 2,
  "draft_version": 3,
  "has_changes": true,
  "components": {
    "published_count": 5,
    "draft_count": 6,
    "added": ["comp-abc123"],
    "removed": []
  },
  "styles": {
    "published_count": 3,
    "draft_count": 4,
    "changed": true
  }
}
```

## Workflows

### Export, Edit, and Publish

```bash
# 1. Export current draft
vanjaro content get 42 --output page.json

# 2. Edit page.json in your editor or programmatically

# 3. Push changes (creates draft)
vanjaro content update 42 --file page.json --json

# 4. Review what changed
vanjaro content diff 42

# 5. Publish the draft
vanjaro content publish 42 --json
```

### Safe Update With Version Check

```bash
# Get current version
VERSION=$(vanjaro content get 42 --json | jq '.version')

# Edit and update with conflict detection
vanjaro content update 42 --file page.json --version "$VERSION" --json
```

If another user modified the page between the get and update, the server returns a 409 conflict error.

### Multilingual Content

```bash
# Export English and Spanish versions
vanjaro content get 42 --locale en-US --output page-en.json
vanjaro content get 42 --locale es-ES --output page-es.json

# Update Spanish content
vanjaro content update 42 --locale es-ES --file page-es.json

# Publish both
vanjaro content publish 42 --locale en-US
vanjaro content publish 42 --locale es-ES
```

### Pipe Content Between Pages

```bash
# Copy content from page 42 to page 99
vanjaro content get 42 --json | vanjaro content update 99
```

### Check for Unpublished Changes

```bash
# Quick check
HAS_CHANGES=$(vanjaro content diff 42 --json | jq '.has_changes')
if [ "$HAS_CHANGES" = "true" ]; then
  echo "Page 42 has unpublished changes"
fi
```

## Error Handling

- "No content returned for page": The page ID does not exist, or the VanjaroAI module cannot access it.
- "Invalid JSON": The file passed to `--file` is not valid JSON. Check for syntax errors.
- "Provide --file or pipe JSON via stdin": The update command needs input -- pass `--file` or pipe JSON.
- Version conflict (409): The page was modified since you last read it. Re-fetch with `content get` and retry.
- 404 or connection errors: Verify the VanjaroAI module is installed and the API key is configured (`vanjaro api-key status`).

## Content Structure

Vanjaro uses GrapesJS for page layout. The content JSON is a tree of components:

- **components**: Array of GrapesJS component objects. Each has a `type` (e.g., `text`, `image`, `wrapper`), optional `content` string, nested `components` array, and `attributes` with an `id`.
- **styles**: Array of CSS rule objects with `selectors` and `style` properties.

The `content get` output wraps these in metadata (page_id, locale, version, is_published). The `content update` command accepts either the full wrapped format or just `{"components": [...], "styles": [...]}`.
