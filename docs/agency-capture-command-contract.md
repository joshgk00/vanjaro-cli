# Agency capture command contract

Status: implementation requirements, not an implemented command or live validation.

## Purpose

Expose repeatable, page-specific design-to-build comparison to an agency operator
for live HTML, supplied images, and Figma designs. Reuse the existing project
workspace and evidence reader. Collection must not publish or alter a portal.

## Review disposition

The source-reference review is recorded in
`artifacts/ringer-agency-capture-command-review/source-reference-contract/report.md`.
Its Ringer run ended FAIL after two attempts; its recommendations are not a
verified implementation. Root inspection confirms that `CaptureImage` requires
browser stability flags and `ViewportCapturePair` currently describes canonical
viewports. Static references need an explicit alternative, not invented flags.

Do not adopt the review's suggestion that a desktop-only source can satisfy
workspace responsive coverage by reducing the required breakpoint set. A valid
desktop comparison and complete responsive evidence are separate facts.

## Required behavior

1. Provide an explicit `project capture` command with page selection, JSON output,
   and a local-only dry run. Dry run must not load credentials, contact a portal,
   launch a browser, acquire Figma exports, or write files. Show source kind,
   exact page identity, source references, output target, viewport dimensions,
   proposed workspace paths, and missing-reference diagnostics.
2. Resolve pages from the authoritative design document and managed page
   manifests. Refuse unknown or ambiguous page mappings. Never infer identity by
   splitting opaque section IDs. Explicit reference overrides must bind to a
   specific page and breakpoint, not silently replace another page's reference.
3. Before capture, reuse `verify_project_portal` to check configured and live
   target identity. Resolve the output route for the managed portal page and
   validate its origin and child-portal path. Do not silently accept redirects
   outside that target. Do not log cookies, passwords, API keys, or signed URLs.
4. Do not publish, change visibility, update content, or create portals. A draft
   rendering an empty shell is a diagnostic failure requiring separate operator
   action, never permission to publish automatically.
5. Live references render at the existing desktop, tablet, and mobile viewports.
   Both live source and built output require actual stability evidence.
6. Static references retain their bytes, hash, declared dimensions, page, and
   breakpoint ownership. Use a distinct static evidence type without browser
   stability flags. Render the built output at the reference's declared viewport;
   never resize a desktop reference into tablet/mobile evidence. Distinguish
   image canvas dimensions from viewport dimensions for full-page screenshots;
   require explicit interpretation if they differ instead of guessing.
7. Figma references must bind to the selected frame, source design identity,
   breakpoint, and actual exported bytes. Reuse existing acquisition facilities;
   do not introduce a parallel Figma client. An inferred responsive layout is
   not an exported reference. Missing frame variants remain missing evidence.
8. Report valid comparisons separately from responsive completeness. A real
   1280-pixel desktop reference may support a valid desktop comparison at 1280
   pixels, but does not prove a canonical 1440-pixel capture. Preserve the
   existing strict quality metric until an explicit versioned metric policy
   supports declared-viewport evidence; never loosen its reader incidentally.
9. Distinguish `reference_not_declared`, `reference_invalid`, `capture_failed`,
   `target_mismatch`, and `output_not_measurable` in structured results. Do not
   fabricate expected geometry from a raster; use only available, provenance-
   bound design observations and report unscored dimensions.
10. Preserve design/build/target fingerprints, file hashes, containment checks,
    and page isolation. Use safe opaque filenames, not raw page IDs. A failed or
    partial recapture must not leave old evidence presented as the new successful
    attempt. Quality and fidelity consumers must agree about validity.

## Implementation tasks and acceptance

### A. Typed reference and planning layer

Keep source resolution pure and separate from CLI/browser dependencies. Define
live and static reference types, explicit viewport interpretation, ownership,
and per-breakpoint diagnostics. Integrate image/Figma metadata without network
access. Publicly expose a single reusable image-identity helper if necessary.

Acceptance: offline tests cover all three source kinds, missing mobile/tablet,
arbitrary valid viewport sizes, invalid dimensions, duplicate ownership, unknown
pages, changed bytes, and traversal/symlink escapes. No test may earn missing
breakpoint credit. Planning tests assert zero writes and zero network calls.

### B. Source-aware capture and evidence serialization

Depends on A. Extend capture and storage through an explicit schema variant;
preserve existing live records and strict metric semantics. Capture static
references without pretending to render them. Record built-output stability and
source provenance independently. Feed only validated observations into scoring.

Acceptance: mixed live/image/Figma fixtures; noncanonical static viewport retained;
source bytes unchanged; invalid exports rejected; partial recapture invalidates
old completeness; page B preserves page A; stale bindings reject; malformed
variant payloads return diagnostics rather than exceptions. Legacy tests remain
green, including independent missing-binding and malformed-breakpoint checks.

### C. Operator command and target routing

Depends on A and B. Keep Click argument handling thin; orchestration owns planning,
identity checks, collection, and result aggregation. Register `project capture`
without conflating it with image-analysis `project evidence generate`.

Acceptance: actual CLI invocation with injected browser and portal interfaces
proves dry-run isolation, page selection, target mismatch refusal before capture,
child-portal route containment, redirect refusal, empty-draft diagnostics, no
mutation requests, safe filenames, JSON results, and shared-reader consumption.

### D. End-to-end proof and operator documentation

Depends on C. Run full non-integration regression, then separately authorized
isolated live trials for HTML, image, and Figma. Record exact input, portal/page
identity, before/after captures, missing variants, fidelity results, and manual
adjustments. Provide a reproducible runbook and actual time measurements; mocks
cannot establish live rendering quality or human-effort reduction.

Acceptance: each input kind has inspected real artifacts and independently read
back results. Report failures as failures. Do not describe the agency goal as
complete based on a functioning capture command alone.

## Delegation boundaries

A precedes B; C consumes both. These are dependent tasks, not parallel lanes.
Declare exact file ownership in each implementation manifest after inspecting
current interfaces. Root retains acceptance checks and reviews worker output.
An independent test/review lane may run alongside implementation only when it
has disjoint write ownership and a stable agreed interface.

## Verified integration constraints from current code

- `portal/pages.py::_record` already persists design `key`, DNN `page_id`,
  server-returned `path`, and publication/visibility flags. The command should
  use those records rather than reconstruct routes from design slugs. Local
  flags alone do not prove the current live page is published.
- `portal_identity.py::verify_project_portal` checks the profile URL and portal
  ID against project pins and then reads the live health endpoint. It does not
  validate a browser's eventual redirect destination; that needs a separate
  capture-time check.
- `figma_adapter.py` puts only observed breakpoints in `Page.breakpoints`.
  Inferred tablet/mobile section observations carry `ObservationMethod.INFERRED`
  and may reuse the desktop frame ID. Frame-ID presence alone therefore cannot
  establish a genuine responsive export.
- `fidelity_capture.py::PageRenderer.render` currently accepts a breakpoint,
  not an arbitrary viewport. Static-reference integration must extend the
  renderer boundary to express actual dimensions; substituting a breakpoint
  label would silently render the wrong width.
- `fidelity_capture.py::_screenshot_path` currently interpolates raw page IDs.
  Safe filenames must be implemented before exposing externally supplied IDs
  through the new command.

## Source-reference implementation verification

The typed reference/planner implementation and its first correction are present.
Root verification after the correction: 2,758 non-integration tests passed,
one Windows symlink test skipped, 16 live integrations deselected. The focused
independent-plus-maintained reference checks passed 81 tests with the same one
skip. The 17 independent cases cover malformed identity/URLs, credential-safe
errors, Figma ownership (including inferred provenance), positive ownership,
and canvas interpretation. `git diff --check` exited zero.

These results do not yet accept the entire reference contract. Review of the
real-adapter positive fixture found a remaining viewport-binding gap: its Figma
frames are 1440x900 and 375x812, but the test supplies 16x16 exports declared as
16x16 viewports and the planner accepts both. File/frame/breakpoint ownership
is checked, but source-frame dimensions are not yet bound to reference viewport
dimensions. A subsequent correction must use actual frame dimensions and reject
or explicitly model export scale rather than treat thumbnail pixels as layout
coordinates. Positive fixtures must exercise realistic declared dimensions.

The subsequent frame-dimension correction resolves that specific gap. The
adapter now retains frame-level provenance for every observed variant, and the
planner rejects missing/conflicting bounds and mismatched viewport/canvas sizes.
Positive real-adapter fixtures use 1440x900 desktop and 375x812 mobile exports;
unmatched-section variants retain frame provenance. The Ringer authoritative
check passed 2,782 tests (including 18 independent tests), with one symlink skip
and 16 live integrations deselected. The first attempt passed. Root reviewed
the implementation, reran focused acceptance, and checked whitespace errors.
Static Figma references currently require 1x exports; scaled export metadata
and acquisition remain future integration work, not inferred capabilities.

The operator command, rendering integration, static-evidence serialization,
real symlink validation, and live three-source trials remain outstanding.

### Capture-layer integration checklist

Current renderer and measurer independently open browser sessions and each
chooses canonical dimensions from the breakpoint label. Task B must pass an
explicit viewport through both paths, preserving the legacy canonical wrapper.
Screenshots and measured observations must describe the same layout state;
prefer one settled session per output viewport for both operations instead of
two unrelated page loads.

The current per-page writer serializes stability flags from the source image
only, even though each pair also carries output stability. The new schema must
validate and store each live side independently. A static source needs verified
artifact identity, not fabricated browser flags; the built side always needs
its own actual stability evidence. Negative acceptance tests must reject an
unstable output even when its source is valid and stable.

Capture-time destination checks must happen after navigation and before taking
the screenshot or reading the DOM. Browser redirects are not checked by the
portal health preflight. Unexpected destination changes must become a failed
page result with no credit, and URL diagnostics must redact credentials and
query secrets.

### Evidence schema integration decision

Introduce a versioned source-aware record rather than retrofit static artifacts
into the v1 browser-only flags. Keep reading existing v1 records under their
current strict canonical policy. New records must contain, per breakpoint:

- Actual viewport width/height and explicit viewport/full-page interpretation.
- A source union: live screenshot with its own stability evidence, or static
  artifact with image/Figma identity, hash and declared dimensions. Static
  records have no browser-settlement flags.
- Built screenshot hash, separately recorded stability evidence and measured
  observations from the same capture session.
- Expected observations with their design provenance; unknown measurements
  remain unavailable, never derived from an image merely because pixels exist.
- A structured attempt result, including missing reference or capture failure.

Both versions retain the current page/design/build/target binding and workspace
containment checks. The reader must revalidate static ownership against the
current design through the source planner, not trust a serialized `valid` flag.
Do not preserve old successful captures alongside a new failed attempt as if
they belonged to that attempt.

Keep two facts explicit in results: a valid source-paired comparison at its
declared viewport, and completion of the existing three-canonical-viewport
policy. A 375px source/output pair is a valid mobile comparison, but is not a
390px capture. Partial/static comparisons must be inspectable and scoreable
where measured data exists while missing required release evidence continues
to block release. Any future policy allowing declared-viewport completeness
must be versioned and reported, not silently substituted for the existing
canonical quality count.

Acceptance must invoke the actual reader and fidelity consumer on records
produced through collection, including a 375px Figma frame, a 1280px image,
three canonical live captures, a missing mobile reference, unstable output,
changed source bytes, and partial recapture. Merely constructing new record
types or adding tests around an unused serializer does not finish integration.

### Shared capture primitive verified

`design/capture_session.py` now provides `PlaywrightCaptureSession.capture` with
explicit viewport, destination, allowed target base URL, full-page selection,
and an output-section requirement. It obtains screenshot and measured DOM in
one settled session, validates redirects before evidence collection and before
artifact replacement, hashes actual screenshot bytes, and preserves an old
destination when a new capture fails. Genuine timeout retries are separately
injectable; arbitrary navigation failures are not retried. External exception
chains are suppressed from safe capture errors. Temporary screenshot paths
retain an image extension so browser format inference works.

Root-owned capture checks exposed and verified corrections for retry scope,
redirects during settle, traceback disclosure, and screenshot format. All 11
capture checks and 18 source-reference checks pass. Root's full offline run:
2,842 passed, one Windows symlink test skipped, 16 live integrations deselected
in 44.18 seconds; `git diff --check` exited zero. The correction Ringer run
passed on its second attempt after the first attempt reached its time limit.

These are injected-browser tests, not a live browser or portal run. The full
suite count above predates the command and evidence integration below.

### Offline integration verified (2026-09-21)

The command and source-aware collector now pass combined offline verification;
live workflow acceptance remains outstanding. Root-owned `artifacts/test_capture_collection_independent.py`
executes the actual collector, writer, shared reader and fidelity consumer,
replacing only browser and portal I/O. Six checks currently pass: canonical live
coverage, separate output stability, failed-recapture invalidation, target
mismatch without writes, and image/Figma comparisons at an actual 375px mobile
width. Static bytes remain unchanged and missing canonical coverage blocks
release. These checks are offline evidence, not live-browser proof.

The seventh check invokes the actual registered CLI and exposed an interface
mismatch: the collector returns `captured`, while the CLI initially recognized
only `ok`. Two separate root-owned reference-file boundary checks exposed an
outside-workspace read attempt. Both defects are fixed and all three checks
pass. Two additional checks in `artifacts/test_capture_summary_independent.py`
exposed a workspace summary that hid partial image/Figma scores as `not_scored`;
the evidence worker corrected that during its retry. Partial scores now remain
visible without inflating fully scored page counts or granting release approval.

Root's combined verification executed the full non-integration suite plus all
six independent capture acceptance files: **2,933 passed, 2 skipped, 16 live
integrations deselected in 45.54 seconds**, exit zero. `git diff --check` for
production code, tests, and this contract also exited zero. The command
correction run passed on its first attempt. The evidence run passed on its second
attempt after its initial handoff was incomplete (authoritative check exit zero).
No separate summary
correction run was launched; its prepared manifest is now superseded by the
verified fix in the evidence run.

A read-only preview against `artifacts/projects/pilot-measure` stopped before
capture because its historical project manifest uses schema 1.0. The explicit
`project migrate-contract` preview reports `review_required`, proposing schema
1.1 plus `stages.launch:added-pending`. No migration was applied, no receipt or
backup was written, and no portal was contacted by those previews. A reviewed
workspace migration is a prerequisite for using this historical project in a
later real capture trial.

The subsequent read-only `--profile pilot site health --json` check exited one
with `Session expired`; it did not establish live portal identity. A refreshed
local-development login and a successful pinned target check are prerequisites
for the pilot capture trial. No automatic authentication recovery or portal
mutation was performed by that health check.

The operator subsequently refreshed the existing `pilot` session using the
local development credentials without exposing them in arguments or output.
Read-back health succeeded for `http://vanjarocli.local/pilot`, portal **8**,
DNN 9.10.2 and Vanjaro 1.6.0.0 (server timestamp 2026-09-22T02:54:28Z).
This resolves the expired-session prerequisite only; it is not a capture,
visual-fidelity result or authorization to publish. The historical workspace
format migration remains unapplied.

### Real browser smoke completed (2026-09-21 local time)

The reviewed pilot workspace migration was subsequently applied through the
existing command. `artifacts/check_pilot_contract_migration.py` verifies the
exact reviewed old/new SHA-256 values, original-byte backup, completed receipt,
unchanged portal-8 target pins and current schema. The migration run passed on
its first attempt. A live pinned target check then succeeded.

The unchanged local Northstar HTML fixture was temporarily served only on
127.0.0.1:8766. Explicit canonical desktop/tablet/mobile references were saved
in `pilot-measure/sources/capture-smoke-references.json`, and the real
`project capture` command captured it against existing pilot page 187. The
browser smoke run passed on its first attempt. Root independently reran
`artifacts/check_pilot_browser_capture.py`: six real PNGs had the expected
widths and sufficient heights, the shared reader accepted current evidence,
and output section measurements were present. Root visually inspected the
desktop source and output screenshots. The temporary server was stopped after
the run; restart it to repeat these references.

**Capture passed; fidelity failed.** Overall fidelity was 56.89 against a draft
minimum of 75, with additional section-level failures. The screenshots show
substantial layout differences. The source fixture is unstyled and references
absent synthetic media; this run is not representative-client design acceptance
and does not demonstrate hands-on time savings. No portal build, publication,
page edit or asset change occurred during this capture trial. Real image/Figma
browser trials and representative complete-source projects remain outstanding.
