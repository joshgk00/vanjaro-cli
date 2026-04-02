# Site -- vanjaro-cli

Site information, health checks, and branding management. All commands in this file require the VanjaroAI module (Vanjaro.AI.dll) installed on the DNN site.

## Commands

### `vanjaro site info [OPTIONS]`

Show comprehensive site analysis including pages, global blocks, assets, design, and branding summary.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro site info --json
```

**JSON output:**
```json
{
  "site": {
    "name": "My Site",
    "description": "A Vanjaro-powered website",
    "theme": "starter-theme",
    "url": "http://my-site.com"
  },
  "pages": [
    { "tabId": 42, "name": "Home", "isPublished": true },
    { "tabId": 43, "name": "About", "isPublished": false }
  ],
  "global_blocks": [
    { "name": "Header", "guid": "..." },
    { "name": "Footer", "guid": "..." }
  ],
  "design_summary": {
    "themeName": "starter-theme",
    "totalControls": 50,
    "customizedControls": 12
  },
  "assets": {
    "totalFiles": 25,
    "totalFolders": 4,
    "totalSizeMB": 15.3
  },
  "branding": {
    "hasLogo": true,
    "hasFavicon": true
  }
}
```

### `vanjaro site health [OPTIONS]`

Check site health status. Returns DNN and Vanjaro versions, current user, and portal info.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro site health --json
```

**JSON output:**
```json
{
  "status": "healthy",
  "dnn_version": "9.10.2",
  "vanjaro_version": "1.6.0",
  "user_id": 1,
  "user_name": "host",
  "portal_id": 0,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

---

### `vanjaro branding get [OPTIONS]`

Show current site branding (name, description, footer, logo).

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro branding get --json
```

**JSON output:**
```json
{
  "site_name": "My Site",
  "description": "A Vanjaro-powered website",
  "keywords": "vanjaro, dnn",
  "footer_text": "Copyright 2024",
  "logo": {
    "fileName": "logo.png",
    "width": 200,
    "height": 80,
    "folderPath": "Images/"
  }
}
```

### `vanjaro branding update [OPTIONS]`

Update site branding. Without any flags, shows current values (same as `branding get`).

**Options:**
- `--site-name TEXT` -- Update site name
- `--description TEXT` -- Update site description
- `--footer-text TEXT` -- Update footer text
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro branding update --site-name "New Site Name" --footer-text "Copyright 2025" --json
```

**JSON output:**
```json
{
  "status": "updated",
  "siteName": "New Site Name",
  "footerText": "Copyright 2025"
}
```

## Workflows

### Initial Site Assessment

```bash
# Check connectivity and versions
vanjaro site health --json

# Get full site overview
vanjaro site info --json

# Review branding
vanjaro branding get --json
```

### Health Check in CI/CD

```bash
# Quick health check after deployment
STATUS=$(vanjaro site health --json | jq -r '.status')
if [ "$STATUS" != "healthy" ]; then
  echo "Site health check failed: $STATUS"
  exit 1
fi
```

### Update Branding

```bash
# View current branding
vanjaro branding get

# Update specific fields
vanjaro branding update --site-name "My New Site" --json
vanjaro branding update --description "Updated description" --footer-text "Copyright 2025" --json
```

### Site Inventory Report

```bash
# Get full analysis and extract summary
vanjaro site info --json | jq '{
  site_name: .site.name,
  theme: .site.theme,
  total_pages: (.pages | length),
  published_pages: ([.pages[] | select(.isPublished)] | length),
  global_blocks: ([.global_blocks[].name]),
  total_assets: .assets.totalFiles,
  asset_size_mb: .assets.totalSizeMB
}'
```

## Error Handling

- 404 on `site info` or `site health`: The VanjaroAI module is not installed. These endpoints require Vanjaro.AI.dll.
- Connection refused: The site URL may be wrong. Check `vanjaro auth status` for the configured URL.
- 401/403 errors: Re-authenticate with `vanjaro auth login`.
- `branding update` with no flags: Shows current values instead of updating. Pass at least one flag to make changes.
