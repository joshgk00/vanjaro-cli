# Testing Standards

## Structure

- One test file per source module: `test_auth.py` tests `auth.py`, etc.
- Shared fixtures live in `conftest.py` — not duplicated across test files.
- Helper functions (like `make_page()`, `make_client()`) go at the top of the file that uses them, or in `conftest.py` if shared.

## What to test

- Every public function gets at least: happy path, error/edge case, and boundary input.
- Test CLI commands through `CliRunner` — this tests the full Click integration.
- Test HTTP interactions with the `responses` library (mock at the HTTP boundary, not on internal functions).
- Don't test Pydantic validation that Pydantic already handles.
- Don't test private helpers directly — test them through the public API.

## How to test

- Use `@responses.activate` decorator for any test that makes HTTP calls.
- Assert on behavior, not implementation. Check the output/response, not which internal method was called.
- Assert on request parameters too — use `responses.calls[n].request` to verify the right params/body were sent to the API.
- Use `pytest.raises` for expected exceptions — assert on both the exception type and the message content.
- Keep tests independent — no test should depend on another test's side effects.
- Use `tmp_path` fixture for any test that touches the filesystem.
- Let `save_config` actually write to `tmp_path` instead of mocking it away — verify the file was written correctly.
- Keep test names descriptive: `test_login_bad_credentials`, not `test_login_2`.

## Assertions

- For JSON output: parse the JSON and assert on specific fields, not substring presence.
- For text output: use precise assertions. `assert "Created page" in result.output` is okay. `assert "New Page" in result.output or "99" in result.output` is not — pick one correct expectation.
- For error cases: assert both the exit code and the error message content.

## What NOT to do

- Don't mock functions you own (like `save_config`) — let them run against `tmp_path`.
- Don't mock Pydantic models — use real instances with test data.
- Don't test logging output or print statements unless they're the feature.
- Don't write integration tests that hit a live Vanjaro instance without the `@pytest.mark.integration` marker.
- Don't use `time.sleep` in tests.
- Don't write tests that patch module-level constants in multiple places — if the test needs 3+ patches to work, the code's coupling is the problem.
