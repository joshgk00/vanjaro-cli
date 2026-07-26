# vanjaro-cli

CLI and resumable agency workflow for building and managing Vanjaro/DNN sites
from live HTML, Figma designs, and reference images.

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
vanjaro auth status  [--offline]
```

`auth status` verifies the stored session against the server by default.
Expired cookies are reported as `session_expired` instead of `authenticated`.
Use `--offline` to skip server verification and only check local cookies.

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

### Agency projects

```bash
# Initialize a project from a live site, Figma file, or reference images.
vanjaro project init artifacts/projects/example \
  --name "Example Client" \
  --target-profile example-client \
  --source live_html=https://example.com/

# Inspect, analyze, plan, and preview the resumable workflow.
vanjaro project status artifacts/projects/example
vanjaro project analyze artifacts/projects/example
vanjaro project plan artifacts/projects/example
vanjaro project build artifacts/projects/example --through verify --dry-run
```

Image projects declare page, breakpoint, and viewport ownership. Automatic
evidence generation is explicit and supports a credential-free dry run:

```bash
vanjaro project evidence generate artifacts/projects/image-example --dry-run
vanjaro project evidence generate artifacts/projects/image-example --by "Agency Operator"
```

Generated sidecars are bound to the exact raster SHA-256 and are reviewed by
the normal `project analyze` and planning gates. Existing sidecars are retained
unless `--overwrite` is supplied; overwrites are snapshotted under
`history/evidence`.

Shared agency libraries are immutable named/versioned packs. Review an upgrade
without changing the project or portal:

```bash
vanjaro project pack upgrade artifacts/projects/example \
  --to-version 1.1.0 --dry-run --json
```

Pack manifests independently lock template and modifier payload versions and
hashes. Compatibility reports fail closed when project usage, migration rules,
or used contract ownership cannot be proven.

Apply only the exact report that was reviewed:

```bash
vanjaro project pack upgrade artifacts/projects/example \
  --to-version 1.1.0 --apply \
  --accept-fingerprint <dry-run-fingerprint> --by <reviewer> --json
```

This transaction is offline: it snapshots the project, replans against the
attested target catalog, invalidates stale approvals, and never calls a portal.

## Configuration

Config is stored in `~/.vanjaro-cli/config.json`. Environment variables override file values:

| Variable | Description |
|----------|-------------|
| `VANJARO_BASE_URL` | Site base URL (required) |
| `VANJARO_USERNAME` | DNN username |
| `VANJARO_PASSWORD` | DNN password |
| `VANJARO_TOKEN` | Override stored JWT |
| `VANJARO_PORTAL_ID` | Portal ID for multi-site (default: 0) |
| `FIGMA_ACCESS_TOKEN` | Figma REST token for Figma source acquisition |
| `OPENAI_API_KEY` | OpenAI key used only for explicit image evidence generation |
| `VANJARO_IMAGE_EVIDENCE_MODEL` | Optional vision model override (default: `gpt-5.4`) |
| `VANJARO_AGENCY_PACKS_DIR` | Optional versioned agency-pack registry override |

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
