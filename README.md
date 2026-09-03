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

For a new client, start with the
[isolated migration portal runbook](docs/isolated-migration-portal-runbook.md).
It previews and fingerprints a blank child portal before any mutation, verifies
the saved profile and portal identity, and then connects that target to the
guarded HTML, Figma, or image project workflow.

```bash
# Initialize a project from a live site, Figma file, or reference images.
vanjaro project init artifacts/projects/example \
  --name "Example Client" \
  --target-profile example-client \
  --source live_html=https://example.com/

# Inspect, analyze, plan, and preview exactly the next build stage.
vanjaro project status artifacts/projects/example
vanjaro project analyze artifacts/projects/example
vanjaro project plan artifacts/projects/example
vanjaro project build artifacts/projects/example --through verify \
  --dry-run --by "Agency Operator" --json
```

Save the returned `receipt` object as strict UTF-8 JSON. Apply that one stage
only with the same modes and ceiling plus `--review-receipt`,
`--confirm-build <receipt fingerprint>`, and the same `--by` identity. Then
preview again for the next stage. See the runbook for a PowerShell example that
saves the detached receipt safely.

Project schema migrations are explicit and review-first. A v1.0 workspace is
never silently enriched while loading:

```bash
vanjaro project migrate-contract artifacts/projects/example
vanjaro project migrate-contract artifacts/projects/example --apply
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

### Release readiness

The aggregate audit consumes hash-bound local evidence and never contacts or
mutates a portal:

```bash
vanjaro release verify release/agency-release-contract.json \
  --repository-root . \
  --output artifacts/releases/agency-release-audit.json \
  --json
```

It exits nonzero for failed, missing, stale, unsupported, or incomplete gates.
By default it validates declared test evidence without executing repository
code, so test and dependent control gates remain incomplete. Add
`--execute-tests` only after reviewing the repository to explicitly authorize
the governed pytest rerun. That option executes repository-controlled Python
with the caller's local filesystem and process authority. Its sanitized
subprocess environment excludes application credentials and configuration,
but it is not a network sandbox.

Locally authored live receipts also remain incomplete unless the embedding
caller supplies a trusted live verifier. The production CLI does not yet
supply one, so it cannot independently close live gates.

Preview the governed test capture before authorizing repository code:

```bash
vanjaro release capture-tests release/test-policy.json \
  --repository-root . \
  --output artifacts/releases/test-evidence.json

vanjaro release capture-tests release/test-policy.json \
  --repository-root . \
  --output artifacts/releases/test-evidence.json \
  --execute-tests --json
```

The preview validates the strict policy, hashes the complete governed source
inventory, and prints the exact command, destination, and contract-ready
fragment without running pytest or writing files. `--execute-tests` is explicit
local-process authority: it runs only `python -m pytest -m not integration -q`
in a minimal environment, requires a clean result and the policy's exact
deselection count, then atomically writes the canonical receipt. Neither mode
edits the release contract or contacts a portal; the operator must review and
copy the printed hash-bound fragment.

Create operator worksheets for one representative project with a write-free
preview first:

```bash
vanjaro release scaffold-project-evidence \
  --candidate-id rc-2026.08 \
  --project-id representative-image \
  --source-kind image \
  --workspace artifacts/projects/representative-image \
  --output-dir artifacts/releases/representative-image

vanjaro release scaffold-project-evidence \
  --candidate-id rc-2026.08 \
  --project-id representative-image \
  --source-kind image \
  --workspace artifacts/projects/representative-image \
  --output-dir artifacts/releases/representative-image \
  --write --json
```

The `.template.json` files deliberately contain null or empty observations and
cannot validate as strict evidence. They do not invent operator identities,
versions, results, timings, dates, captures, or digests. Existing worksheets
are refused unless `--overwrite` accompanies `--write`. All five files are
staged and committed as one rollback-protected set; an ordinary write, backup,
or replacement failure restores the prior set. If temporary recovery cleanup
fails after a successful commit, the result contains an explicit warning and
the residual repository-local directory so it can be reviewed and removed.
The command never contacts a portal and never updates the release contract.
See `docs/agency-release-checklist.md` and
`docs/agency-development-architecture.md` for the evidence and contribution
contracts.

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
