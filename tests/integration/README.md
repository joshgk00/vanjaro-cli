# Live Integration Smoke Tests

These tests run the CLI against a **real Vanjaro site** to catch what mocked
unit tests structurally can't: endpoint URL drift, renamed response fields,
auth regressions, and form-encoding quirks. The unit-test mocks are built from
the same assumptions the code makes, so when the API changes, both drift
together and stay green.

## Requirements

- A running Vanjaro instance with the Vanjaro.AI module installed
  (default target: `http://vanjarocli.local`)
- An authenticated CLI profile: `vanjaro auth login --url http://vanjarocli.local`
- An API key on the profile: `vanjaro api-key generate` (as SuperUser)

## Running

```bash
pytest -m integration                 # just the live suite
pytest                                # everything (live suite self-skips if site is down)
pytest -m "not integration"           # unit tests only
```

Target a different site by profile:

```bash
VANJARO_TEST_PROFILE=vanjarobaseline-local pytest -m integration
```

## Behavior

- The whole suite **skips** (not fails) when the health check fails — an
  expired session or stopped site never breaks a normal test run.
- Lifecycle tests create resources with unique `it-smoke-*` names and delete
  them in `finally` blocks. If a run is killed mid-test, leftovers are
  greppable by that prefix.
- Theme and branding tests are **read-only** — theme writes trigger SCSS
  recompilation and are deliberately excluded from the smoke suite
  (see docs/theme-update-investigation.md for the history).
