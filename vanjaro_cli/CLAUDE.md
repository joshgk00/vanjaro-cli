# Python Standards

## Simplicity first

- Flat is better than nested. Avoid deep class hierarchies — a function is fine.
- No abstract base classes unless there are 2+ concrete implementations today.
- No metaclasses, descriptors, or `__init_subclass__` unless solving a real problem.
- Prefer plain functions over classes when there's no state to manage.
- Avoid premature generalization — write the specific thing first.
- One file per concern. If a module does two unrelated things, split it.

## No duplicated code

- Shared helpers belong in a single location, not copy-pasted across modules.
- If two command modules need the same function, extract it to a shared module and import it.
- Repeated patterns (like JSON output formatting) should be a helper function, not inlined 16 times.

## Type hints

- Add type hints to all function signatures (params and return types).
- Use `X | None` instead of `Optional[X]` (Python 3.10+).
- Use `from __future__ import annotations` at the top of every module.
- Use real types — never `object` or `Any` as a placeholder when the actual type is known. If a function returns `Config`, annotate it as `Config`.
- Don't over-annotate local variables — let the types flow from function signatures.

## Module exports

- Every module with public API surface should define `__all__` listing its public names.
- This makes it clear what's public vs. internal and helps IDE autocompletion.

## Naming

- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private helpers: prefix with `_` (e.g., `_get_client`, `_exit_error`)
- Boolean variables/params: use `is_`, `has_`, `should_` prefixes
- Avoid abbreviations — `configuration` not `cfg`, `response` not `resp` (except well-known ones like `url`, `id`)

## Error handling

- Define domain-specific exceptions (`AuthError`, `ConfigError`, `ApiError`) — don't raise generic `Exception`.
- Catch the narrowest exception possible. Never bare `except:` or `except Exception:`. Catch `json.JSONDecodeError`, `ValueError`, `UnicodeDecodeError`, etc. specifically.
- Error messages should tell the user what to do next (e.g., "Run `vanjaro auth login` to re-authenticate").
- Let unexpected exceptions propagate — don't swallow errors silently.
- Functions that always raise should be documented as `NoReturn` or have names that make it obvious (e.g., `exit_error` is fine because the name says "exit").
