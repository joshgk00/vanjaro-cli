# vanjaro-cli

CLI tool for managing Vanjaro/DNN websites. Built with Click + Pydantic + Requests.

## Project Structure

```
vanjaro_cli/
  cli.py           — Click entry point, --profile global option, registers command groups
  config.py        — Profile-aware config (multi-site), API key storage, env var overrides
  auth.py          — DNN cookie-based auth (login via Vanjaro AJAX endpoint, logout)
  client.py        — HTTP wrapper with cookie auth, anti-forgery tokens, X-Api-Key header
  commands/        — Click command groups (auth, pages, content, blocks, assets, theme,
                     global-blocks, custom-blocks, templates, branding, site, migrate, ...)
  migration/       — Site-migration pipeline (crawler, sections, tokens, assets,
                     url_rewrite, verify, global_blocks, content_walk, overrides)
  models/          — Pydantic models (Page, PageContent, ContentBlock, blocks, assets, site)
  utils/           — GrapesJS tree helpers, block template composition
tests/
  conftest.py      — Shared fixtures: CliRunner, mock config, mocked HTTP responses
  test_*.py        — Unit tests per module
artifacts/
  block-templates/ — Tracked GrapesJS block template library (heroes, cards, CTAs, ...)
tools/             — Local site maintenance scripts (baseline reset, theme compare)
```

## Commands

```bash
pip install -e ".[dev]"     # Install with dev deps
pytest                      # Run all tests
pytest -m "not integration" # Skip tests requiring a live Vanjaro instance
```

## Config Format

Config lives at `~/.vanjaro-cli/config.json` using named profiles. Profiles are
auto-created from the URL hostname on login. The `--profile` flag overrides the
active profile for a single command.

## Content Endpoints

Content commands use VanjaroAI endpoints (`/API/VanjaroAI/AIPage/*`) provided by
the Vanjaro.AI DNN module (source: `C:\Code\vanjaro-ai`). These bypass the
`[DnnPageEditor]` restriction that blocks headless access to standard Vanjaro
content endpoints. Authentication requires admin cookies + an API key
(generated via `vanjaro api-key generate` as SuperUser).

## Migration Pipeline

`vanjaro migrate` chains: crawl → build-global → create-pages → build-id-map →
assemble-page → rewrite-urls → verify. Crawl output (inventory, sections,
assets, design tokens) lands in a working directory consumed by later phases.

## Dependencies

- Keep dependencies minimal. Current stack: `click`, `requests`, `pydantic`, `python-dotenv`.
- Don't add a dependency for something the stdlib handles.
- New dependencies require a reason stated before adding.
