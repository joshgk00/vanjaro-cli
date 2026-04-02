# Click CLI Conventions

- Every command supports `--json` flag for structured output (required for scripting and Claude Code).
- JSON output uses `{"status": "ok|error|created|updated|deleted", ...}` shape.
- Human output goes to stdout; errors go to stderr via `click.echo(..., err=True)`.
- Shared helpers (`get_client`, `exit_error`, `output_result`) live in `helpers.py` and are imported — not copied per command module.
- Use `@group.command("name")` decorator syntax for commands — don't define with a different name and re-register later.
- Function names should match their CLI counterparts. Don't name a function `login_cmd` if the CLI command is `login`.
- Group related commands under Click groups (`auth`, `pages`, `content`).
- Validate inputs early. Page IDs should be positive integers — reject bad input before making API calls.
- Use `click.ClickException` for user errors, `click.Abort` for cancellations. Avoid raw `raise SystemExit(1)`.
