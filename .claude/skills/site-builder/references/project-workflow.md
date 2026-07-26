# Project Workspace Reference

Detail for the resumable agency project workflow. The skill body has the stage
order; this file has the contracts, layout, and failure modes.

## Workspace layout

`vanjaro project init` creates:

```
<project>/
  project.json      manifest: identity, target, sources, stages, approvals, audit
  sources/          acquired source evidence (rasters, sidecars, crawl data)
  analysis/         Design Document v1 per source
  plans/            Composition Plan v2, library plan, global block plan, theme plan
  build/            resolved documents and portal manifests
  qa/               captures and verification evidence
  history/          snapshots, pack upgrade transactions, prior attempts
```

Manifest writes are atomic and deterministic. Artifact paths cannot escape the
workspace. Secret-bearing metadata keys, authorization values, and secret URL
query parameters are rejected before a manifest can be written.

## Stage graph

```
intake → analyze → plan → theme → assets → library → pages → globals → verify → publish
```

Each stage stores separate input and output fingerprints. A completed stage is
skipped only when all three hold:

1. Inputs are unchanged.
2. Declared artifacts still exist.
3. Their current hashes match the recorded output fingerprint.

Changed or tampered evidence reruns the stage and invalidates everything
downstream. Interrupted or failed work is retried, never treated as complete.

Portal mutation stages require approval of the current plan output. Publish
requires approval of the current verification output. Upstream changes supersede
stale approvals.

## Source kinds

| Kind | Reference | Notes |
|---|---|---|
| `figma` | File or node URL | Needs `FIGMA_ACCESS_TOKEN`. Original fills preferred over screenshots. |
| `html` | Live URL | Static plus rendered observation at three breakpoints. |
| `image` | Local PNG/JPEG/WebP path | Requires viewport, breakpoint, and evidence sidecar. |
| `legacy` | Existing crawl directory | Converts prior migration output without recrawling. |

Combining sources is supported and expected — a Figma desktop frame plus mobile
screenshots is one project, not two.

### Image source requirements

Every raster needs all three, declared at init:

```bash
--source image=./sources/home-desktop.png \
--image-viewport 1440x900 \
--image-breakpoint home-desktop=desktop \
--image-evidence home-desktop=./sources/home-desktop.evidence.json
```

Pair multiple captures of one page with `--source-page SOURCE_ID=PAGE_REFERENCE`.

Acquisition accepts only valid local rasters, rejects workspace escapes, and
rejects byte/extension mismatches. Evidence is owned by the exact image SHA-256 —
replacing the file invalidates the sidecar.

## Evidence generation

```bash
vanjaro project evidence generate <project> --dry-run --json   # no credential needed
vanjaro project evidence generate <project> --json             # needs OPENAI_API_KEY
```

Providers never choose hashes, page ownership, breakpoints, viewports, or pixel
dimensions — orchestration injects those from verified local bytes. Valid
existing sidecars resume rather than regenerate. Overwrites snapshot first and
roll back if manifest adoption fails.

Optional `VANJARO_IMAGE_EVIDENCE_MODEL` overrides the vision model.

## Theme

`--theme-mode` accepts only `preserve` and `plan`.

- `preserve` — portal theme untouched.
- `plan` — maps design tokens to existing controls and writes review artifacts.

**Neither applies the theme.** Planning is GET-only and deterministic. It records
current and proposed values separately for all ten palette slots, maps status
colors only from explicit semantic token names, and refuses unavailable font
substitutions rather than guessing a near match.

Apply the theme by hand with `theme set-bulk`, `theme register-font`, and
`theme css update` before running the build.

## Agency packs

Template and modifier packs are versioned independently of projects.

```bash
vanjaro project pack upgrade <project> --to-version 1.1.0 --dry-run
vanjaro project pack rollback <project>
```

Dry run is mandatory on upgrade — it never writes a report, updates a project, or
contacts a portal. Outcomes are `compatible`, `remediation-required`, or
`blocked`. Missing composition usage, unknown versions, missing migration rules,
unreviewed changes to used templates, and invalid replacements all fail closed.

`rollback` restores an interrupted local transaction from its verified snapshot.

## Verification

`verify/draft-verification.json` records:

- `source_text_coverage` with matched and total counts
- `missing_action_url_count` and the offending element IDs
- `page_count`, `global_count`, warnings, and blockers
- `valid` — false means publication is correctly refused

Unmapped action URLs are the usual blocker. They are content decisions for the
operator. Fabricating a destination to clear the gate is prohibited.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Stage reruns unexpectedly | Input or artifact hash changed | Expected; evidence drifted |
| Approval rejected as stale | Upstream stage reran | Re-request against the new fingerprint |
| `project build` refuses to start | Target not pinned, or portal mismatch | `project target pin` then `check` |
| Evidence command writes nothing | `OPENAI_API_KEY` unset | Set it, or supply sidecars manually |
| Pack upgrade reports blocked | Project has no recorded template usage | Run `project plan` first |
| Empty CLI output from `python -m` | Known stdout issue | Invoke `vanjaro` directly |
