# vanjaro-cli Skills

CLI tool for managing Vanjaro/DNN websites. Load specific skills for detailed command reference.

## Available Skills

| Skill | Commands | Use When |
|-------|----------|----------|
| auth | login, logout, status, profile list/use/delete, api-key generate/revoke/status/set | Connecting to a site, managing profiles, API key setup |
| pages | list, get, create, copy, delete, settings | Managing page structure |
| content | get, update, publish, diff | Reading/writing page content (GrapesJS JSON) |
| blocks | blocks list/get/tree/add/remove, global-blocks list/get/update/publish/delete, templates list/get/apply | Working with page components, shared blocks, and templates |
| assets | folders, list, upload, delete | Managing files and images |
| site | site info, site health, branding get/update | Site configuration, monitoring, and branding |

## Prerequisites

- Content, blocks, global-blocks, and templates commands require the VanjaroAI module (Vanjaro.AI.dll) installed on the DNN site.
- Standard page commands use DNN PersonaBar APIs and work without VanjaroAI.

## Global Options

- `--profile NAME` on `auth login` saves credentials to a named profile
- `vanjaro profile use NAME` switches the active profile for all subsequent commands
- `--json` is available on every command for structured output

## Quick Start

```bash
# 1. Authenticate
vanjaro auth login --url http://your-site.com

# 2. Check site health
vanjaro site health --json

# 3. List pages
vanjaro pages list --json

# 4. Export page content
vanjaro content get 42 --output page.json

# 5. Edit page.json locally

# 6. Push changes (creates draft)
vanjaro content update 42 --file page.json

# 7. Publish
vanjaro content publish 42
```

## Multi-Site Workflow

```bash
# Set up profiles
vanjaro auth login --url http://dev.example.com --profile dev
vanjaro auth login --url http://staging.example.com --profile staging

# Switch between sites
vanjaro profile use dev
vanjaro pages list --json

vanjaro profile use staging
vanjaro pages list --json
```
