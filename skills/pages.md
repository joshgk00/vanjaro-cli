# Pages -- vanjaro-cli

CRUD operations for DNN/Vanjaro pages (tabs).

## Commands

### `vanjaro pages list [OPTIONS]`

List all pages in the site.

**Options:**
- `--keyword, -k TEXT` -- Filter pages by keyword (matches name, title, or text)
- `--portal-id INT` -- Portal ID (default: from config)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro pages list --json
vanjaro pages list --keyword "About" --json
```

**JSON output:**
```json
[
  {
    "id": 42,
    "name": "Home",
    "title": "Home",
    "url": "/",
    "parent_id": null,
    "is_deleted": false,
    "include_in_menu": true,
    "status": "",
    "level": 0,
    "has_children": false,
    "portal_id": 0
  }
]
```

### `vanjaro pages get PAGE_ID [OPTIONS]`

Get details for a single page.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro pages get 42 --json
```

**JSON output:**
```json
{
  "id": 42,
  "name": "About Us",
  "title": "About Us",
  "url": "/about-us",
  "parent_id": null,
  "is_deleted": false,
  "include_in_menu": true,
  "status": "Visible",
  "level": 0,
  "has_children": true,
  "portal_id": 0
}
```

### `vanjaro pages create [OPTIONS]`

Create a new page.

**Options:**
- `--title, -t TEXT` -- Page title (required; also used as name if `--name` omitted)
- `--name, -n TEXT` -- Page name/slug (defaults to title)
- `--parent, -P INT` -- Parent page ID for nesting
- `--hidden` -- Exclude from navigation menu
- `--portal-id INT` -- Portal ID (default: from config)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro pages create --title "Contact" --json
vanjaro pages create --title "FAQ" --parent 42 --hidden --json
```

**JSON output:**
```json
{
  "status": "created",
  "page_id": 99,
  "name": "Contact",
  "path": "/Contact"
}
```

### `vanjaro pages copy PAGE_ID [OPTIONS]`

Copy an existing page.

**Options:**
- `--title, -t TEXT` -- Title for the copied page
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro pages copy 42 --title "About Us (Copy)" --json
```

**JSON output:**
```json
{
  "status": "copied",
  "source_id": 42,
  "new_page": {
    "id": 100,
    "name": "About Us (Copy)",
    "title": "About Us (Copy)"
  }
}
```

### `vanjaro pages delete PAGE_ID [OPTIONS]`

Delete a page by ID.

**Options:**
- `--force` -- Skip confirmation prompt
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro pages delete 99 --force --json
```

**JSON output:**
```json
{
  "status": "deleted",
  "page_id": 99
}
```

### `vanjaro pages settings PAGE_ID [OPTIONS]`

View or update page settings. Without update flags, shows current settings.

**Options:**
- `--title TEXT` -- Update page title
- `--name TEXT` -- Update page name/slug
- `--hidden / --visible` -- Toggle menu visibility
- `--json` -- Output as JSON

**Example (view):**
```bash
vanjaro pages settings 42 --json
```

**Example (update):**
```bash
vanjaro pages settings 42 --title "New Title" --hidden --json
```

**JSON output (update):**
```json
{
  "status": "updated",
  "page_id": 42
}
```

### `vanjaro pages shell [PAGE_ID] [OPTIONS]`

Audit which skin/container shell a page is using, or normalize a page onto the Vanjaro shell.

Without `PAGE_ID`, lists all pages and shows whether each one is using the Vanjaro shell. With `PAGE_ID`, shows shell details for that page. Use `--fix` with `PAGE_ID` to normalize the page to the Vanjaro shell without changing content.

**Options:**
- `--fix` -- Normalize the page to the Vanjaro shell before showing details (requires `PAGE_ID`)
- `--json` -- Output as JSON

**Examples:**
```bash
vanjaro pages shell
vanjaro pages shell 42 --json
vanjaro pages shell 42 --fix --json
```

**JSON output (single page):**
```json
{
  "id": 42,
  "name": "Home",
  "url": "/",
  "has_vanjaro_content": true,
  "is_portal_home": true,
  "shell": "non-vanjaro",
  "skin_src": "[g]skins/Xcillion/Home.ascx",
  "container_src": "[g]containers/Xcillion/NoTitle.ascx"
}
```

## Workflows

### Create a Page Hierarchy

```bash
# Create parent page
vanjaro pages create --title "Services" --json
# Output: {"status": "created", "page": {"id": 50, ...}}

# Create child pages under it
vanjaro pages create --title "Web Development" --parent 50 --json
vanjaro pages create --title "Consulting" --parent 50 --json
```

### Clone and Modify a Page

```bash
# Copy the page
vanjaro pages copy 42 --title "About Us v2" --json

# Update settings on the copy
vanjaro pages settings 100 --hidden --json
```

### Audit All Pages

```bash
# Get all pages as JSON and pipe to jq
vanjaro pages list --json | jq '.[] | select(.include_in_menu == false) | .name'
```

### Audit Theme Readiness

```bash
# Before any automated theme update, verify the published pages actually use Vanjaro
vanjaro pages shell --json | jq '.[] | select(.shell != "vanjaro") | {id, name, shell, skin_src}'

# Normalize a page shell if needed
vanjaro pages shell 42 --fix --json
```

### Bulk Page ID Lookup

```bash
# Find a page by keyword, extract ID
PAGE_ID=$(vanjaro pages list --keyword "Contact" --json | jq '.[0].id')
vanjaro pages get "$PAGE_ID" --json
```

## Error Handling

- "No pages found": The site may have no pages, or the keyword filter matched nothing. Try without `--keyword`.
- 404 on `pages get`: The page ID does not exist. Run `pages list` to see valid IDs.
- 403 on `pages create/delete`: The authenticated user lacks page management permissions.
- Confirmation prompt on `delete`: Use `--force` to skip in scripts.
- `pages shell --fix` requires `PAGE_ID`: use `pages shell` first to audit the site, then normalize specific pages as needed.

## API Notes

- `pages list` uses Vanjaro's `GetPages` endpoint, which returns a flat list with nesting via `-  ` prefix.
- `pages get` and `pages settings` use the DNN PersonaBar `GetPageDetails` endpoint.
- `pages create` uses the VanjaroAI `AIPage/Create` endpoint (requires the Vanjaro.AI module).
- `pages delete` uses the VanjaroAI `AIPage/Delete` endpoint.
- `pages copy` uses the DNN PersonaBar `CopyPage` endpoint.

## Session Notes

- Sessions expire after inactivity. If you get "Session expired", re-login: `vanjaro auth login`
- After re-login, regenerate the API key: `vanjaro api-key generate`
- The API key is required for all VanjaroAI endpoints (content, blocks, templates, assets, etc.)
