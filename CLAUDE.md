# vanjaro-cli

CLI tool for managing Vanjaro/DNN websites. Built with Click + Pydantic + Requests.

## Project Structure

```
vanjaro_cli/
  cli.py           — Click entry point, --profile global option, registers command groups
  config.py        — Profile-aware config (multi-site), API key storage, env var overrides
  auth.py          — DNN cookie-based auth (login via Vanjaro AJAX endpoint, logout)
  client.py        — HTTP wrapper with cookie auth, anti-forgery tokens, X-Api-Key header
  commands/        — Click command groups (auth, pages, content, profile, api-key)
  models/          — Pydantic models (Page, PageSettings, PageContent, ContentBlock)
tests/
  conftest.py      — Shared fixtures: CliRunner, mock config, mocked HTTP responses
  test_*.py        — Unit tests per module
```

## Commands

```bash
pip install -e ".[dev]"     # Install with dev deps
pytest                      # Run all tests
pytest -m "not integration" # Skip tests requiring a live Vanjaro instance
```

## Config Format

Config lives at `~/.vanjaro-cli/config.json` using named profiles:

```json
{
  "active_profile": "vanjarocli-local",
  "profiles": {
    "vanjarocli-local": {
      "base_url": "http://vanjarocli.local",
      "cookies": { ".DOTNETNUKE": "..." },
      "api_key": "base64-key-here",
      "portal_id": 0
    }
  }
}
```

Profiles are auto-created from the URL hostname on login. The `--profile` flag overrides the active profile for a single command.

## Content Endpoints

Content commands use VanjaroAI endpoints (`/API/VanjaroAI/AIPage/*`) which require the Vanjaro.AI DNN module. These bypass the `[DnnPageEditor]` restriction that blocks headless access to standard Vanjaro content endpoints. Authentication requires admin cookies + an API key (generated via `vanjaro api-key generate` as SuperUser).

## Dependencies

- Keep dependencies minimal. Current stack: `click`, `requests`, `pydantic`, `python-dotenv`.
- Don't add a dependency for something the stdlib handles.
- New dependencies require a reason stated before adding.
