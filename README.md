# vanjaro-cli

CLI tool for managing Vanjaro/DNN websites from Claude Code (or any terminal).

## Install

```bash
pip install -e .
```

## Quick Start

```bash
# Authenticate
vanjaro auth login --url https://your-site.com

# List pages
vanjaro pages list

# Read page content
vanjaro content get 42 --output page42.json

# Update page content
vanjaro content update 42 --file page42.json

# Publish
vanjaro content publish 42
```

## Commands

### Auth

```
vanjaro auth login   --url URL -u USER -p PASS
vanjaro auth logout
vanjaro auth status
```

### Pages

```
vanjaro pages list     [--keyword KEYWORD]
vanjaro pages get      PAGE_ID
vanjaro pages create   --title TITLE [--parent ID] [--hidden]
vanjaro pages copy     PAGE_ID [--title TITLE]
vanjaro pages delete   PAGE_ID [--force]
vanjaro pages shell    [PAGE_ID] [--fix]
vanjaro pages settings PAGE_ID [--title TITLE] [--hidden|--visible]
```

### Content

```
vanjaro content get    PAGE_ID [--output FILE] [--locale LOCALE]
vanjaro content update PAGE_ID [--file FILE]   [--locale LOCALE]
vanjaro content publish PAGE_ID
```

Every command supports `--json` for structured output — ideal for scripting and Claude Code.

## Configuration

Config is stored in `~/.vanjaro-cli/config.json`. Environment variables override file values:

| Variable | Description |
|----------|-------------|
| `VANJARO_BASE_URL` | Site base URL (required) |
| `VANJARO_USERNAME` | DNN username |
| `VANJARO_PASSWORD` | DNN password |
| `VANJARO_TOKEN` | Override stored JWT |
| `VANJARO_PORTAL_ID` | Portal ID for multi-site (default: 0) |

Copy `.env.example` to `.env` for local development.

## Development

```bash
pip install -e ".[dev]"
# or:
pip install -r requirements-dev.txt

pytest
```

## Skills

See the [skills/](skills/) directory for Claude Code skill documentation.
