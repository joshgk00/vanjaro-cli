# vanjaro-cli

CLI tool for managing Vanjaro/DNN websites. Built with Click + Pydantic + Requests.

## Project Structure

```
vanjaro_cli/
  cli.py           — Click entry point, registers command groups
  config.py        — Config loading from ~/.vanjaro-cli/config.json + env vars
  auth.py          — DNN JWT auth (login, token refresh, logout)
  client.py        — HTTP wrapper with auth headers, CSRF, and error handling
  commands/        — Click command groups (auth_cmd, pages_cmd, content_cmd)
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

## Dependencies

- Keep dependencies minimal. Current stack: `click`, `requests`, `pydantic`, `python-dotenv`.
- Don't add a dependency for something the stdlib handles.
- New dependencies require a reason stated before adding.
