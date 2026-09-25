# Vanjaro CLI Agency Tool Goal

**Status:** Active  
**Started:** 2026-07-16  
**Product owner:** Clicks and Mortars  
**Related foundation:** `design-translation-v2-spec.md`

## Goal

Turn Vanjaro CLI into a maintainable agency production system that can convert
Figma designs, screenshots/reference images, and live websites into consistent,
editor-friendly Vanjaro sites with substantially less manual development and
client-specific cleanup.

The tool is successful when an agency operator can start a project from any
supported source, review an explainable build plan, create a site using
standard Vanjaro components and agency-approved patterns, and verify the result
across content, structure, responsive behavior, visual fidelity, and ongoing
maintainability.

## Product requirements

### AG-1 — Unified source workflow

- Support three first-class source kinds: live website, Figma frame/file, and
  screenshot/reference image set.
- Every source adapter emits the same versioned Design Document contract.
- Source-specific evidence remains inside its adapter; matching and planning do
  not contain Figma-, DOM-, or image-specific special cases.
- A project may combine sources, such as Figma desktop plus mobile screenshots
  or a live site plus a redesigned homepage image.

### AG-2 — Agency project workflow

- Provide one resumable project workflow from intake through analyze, plan,
  theme, library, pages, global blocks, QA, approval, and publish.
- Store project artifacts under one predictable workspace with a manifest,
  source inventory, decisions, generated plans, QA evidence, and audit history.
- Dry-run and approval gates are mandatory before portal mutation and publish.
- Failed stages can resume without repeating successful network or portal work.

### AG-3 — Standard component system

- Prefer native Vanjaro primitives, Bootstrap utilities, existing templates,
  and versioned agency modifiers before scoped custom CSS.
- Capability manifests describe semantic fields, cardinality, responsive
  behavior, interactions, and physical slot ownership.
- Repeated client fixes can be promoted into a versioned agency template or
  modifier with benchmark evidence.
- Generated sites use predictable block names, categories, edit points, and
  global header/footer ownership.

### AG-4 — Accurate design translation

- Preserve section boundaries, visitor content, media ownership, repeat groups,
  responsive behavior, and important design tokens.
- Missing or ambiguous evidence produces an explicit blocker or review item;
  the tool never fabricates visitor content to pass a gate.
- Candidate templates include scores, alternatives, source evidence, bindings,
  simplifications, and maintainability impact.
- Visual comparison is section-aware at desktop, tablet, and mobile sizes.

### AG-5 — Maintainable engineering architecture

- Keep source adapters, shared reasoning, portal operations, and CLI
  presentation in separate packages with enforced import boundaries.
- Keep analysis and planning pure wherever possible; network and filesystem I/O
  belong at orchestration edges.
- Replace monolithic modules with cohesive pipeline stages and stable typed
  interfaces. New modules should normally stay below 500 lines.
- Use deterministic artifacts, centralized error models, structured logging,
  and tests at unit, contract, benchmark, and live-integration levels.
- Do not add dependencies when the standard library or current dependencies are
  sufficient.

### AG-6 — Safe multi-client operations

- Project configuration, target portal profile, agency library version, and
  source credentials are explicit and cannot leak between clients.
- Secrets never enter artifacts, reports, fixtures, or logs.
- Portal mutations record before/after evidence and support snapshot-based
  recovery.
- No publish occurs without explicit operator confirmation.

## Success measures

The goal is complete only when all of the following are demonstrated on the
current supported benchmark and live-test environments.

| Measure | Required result |
|---|---:|
| Supported input kinds | Live HTML, Figma, and screenshot/image |
| Section boundary precision and recall | >= 0.90 per source kind |
| Visitor-content retention | >= 0.95 |
| Repeat-field ownership accuracy | >= 0.95 |
| Template top-1 / top-3 accuracy | >= 0.85 / >= 0.95 |
| High-confidence precision | >= 0.90 |
| Eligible-section editable coverage | >= 0.85 |
| Native/agency-standard component ratio | >= 0.90 |
| Body sections composed without generic fallback | >= 0.90 |
| Required desktop/tablet/mobile evidence | 100% for release candidates |
| Non-integration test suite | 100% passing |
| Live smoke suite | 100% passing on the local test portal |
| Secret scan and deterministic artifact checks | 100% passing |

For at least three representative agency projects—one per source kind—the
system must also record baseline manual effort and demonstrate at least a 60%
reduction in hands-on build/tweak time without lowering the quality gates.

## Target architecture

```text
sources/
  base.py                 typed adapter request/result contracts
  registry.py             adapter discovery and source dispatch
  html.py                 live/rendered HTML evidence adapter
  figma.py                Figma REST evidence adapter
  image.py                screenshot/reference-image evidence adapter
        |
        v
Design Document --------> grouping and semantic ownership
        |                 template catalog and matcher
        |                 style/theme translation
        v
Composition Plan --------> project orchestrator and approval gates
        |                  portal/build services
        v
Vanjaro site ------------> structural, responsive, visual, and maintenance QA
```

CLI command modules should translate arguments and render results. They should
not own analysis algorithms or portal business rules.

## Delivery milestones

### M1 — Architecture foundation

- Introduce an explicit typed source-adapter interface and registry.
- Route existing HTML and Figma analysis through adapters without changing
  Design Document output.
- Add import-boundary and adapter contract tests.
- Split Figma/HTML grouping and semantic ownership into focused modules.

**Acceptance:** Existing five-case benchmark and non-integration suite remain
green; adapter outputs are byte-equivalent to the legacy entry points.

### M2 — Agency project workspace and orchestrator

- Define a versioned project manifest and artifact directory contract.
- Add `vanjaro project init/status/analyze/plan/build/verify` orchestration.
- Record stage fingerprints, decisions, approvals, and resumable state.
- Keep existing low-level commands available for expert use.

**Acceptance:** A stopped project resumes at the first incomplete stage and no
dry-run mutates a portal.

### M3 — Screenshot/reference-image adapter

- Accept one or more images with explicit viewport and page metadata.
- Extract or accept evidence for section geometry, text, media, tokens, and
  repeated structures, recording confidence and provenance.
- Support human-assisted corrections as audited overlays rather than hidden
  mutations.
- Add annotated desktop/mobile image fixtures to the benchmark corpus.

**Acceptance:** Image-source precision, retention, ownership, and matching meet
the success thresholds without source-specific planner logic.

### M4 — Agency library governance

- Version template and modifier packs independently from client projects.
- Add capability-to-physical-slot/cardinality validation.
- Add promotion reports for repeated scoped-CSS and manual override patterns.
- Add compatibility/migration rules for library upgrades.

**Acceptance:** Two projects can share an agency pack, upgrade it in dry-run,
and receive deterministic compatibility and remediation reports.

### M5 — End-to-end agency build workflow

- Build global navigation/footer, theme, reusable library, pages, assets, and
  content from the approved project plan.
- Add explicit client/editor naming and maintenance conventions.
- Produce handoff documentation and a machine-readable maintenance scorecard.

**Acceptance:** Three representative projects reach a publish-ready state with
all quality gates and the required reduction in manual effort.

### M6 — Reliability and release hardening

- Add performance budgets, structured logs, secret scanning, recovery tests,
  contract migrations, and supported-version policy.
- Document development architecture and contribution boundaries.
- Establish a repeatable release checklist and benchmark baseline.

**Acceptance:** Completion audit proves every AG requirement and success measure
with current artifacts, tests, benchmark reports, and live-site evidence.

## Initial prioritized backlog

| ID | Priority | Work | Milestone |
|---|---:|---|---|
| AG-101 | P0 | Typed source adapter request/result contract | M1 |
| AG-102 | P0 | Adapter registry and deterministic dispatch | M1 |
| AG-103 | P0 | HTML and Figma compatibility wrappers | M1 |
| AG-104 | P0 | Adapter contract and import-boundary tests | M1 |
| AG-105 | P1 | Extract Figma section segmentation module | M1 |
| AG-106 | P1 | Extract shared semantic field taxonomy | M1 |
| AG-107 | P1 | Extract HTML section grouping and semantic ownership module | M1 |
| AG-201 | P0 | Project manifest schema and models | M2 |
| AG-202 | P0 | Resumable stage engine | M2 |
| AG-203 | P1 | `project` command group and status report | M2 |
| AG-301 | P0 | Image-source request and provenance contract | M3 |
| AG-302 | P0 | Image region/text/media adapter | M3 |
| AG-303 | P0 | Annotated image benchmark fixtures | M3 |
| AG-401 | P1 | Semantic slot/cardinality capability schema | M4 |
| AG-402 | P1 | Reusable-fix promotion report | M4 |
| AG-501 | P0 | Approved-plan site build orchestrator | M5 |
| AG-502 | P0 | Agency editor/handoff report | M5 |

## Progress log

### 2026-07-16 — M1 architecture foundation complete

- **AG-101 complete:** typed HTML, Figma, legacy-crawl, and image-intake
  request contracts exist under `vanjaro_cli.design.sources`.
- **AG-102 complete:** deterministic registry dispatch rejects duplicate,
  unsupported, and incorrectly owned requests.
- **AG-103 complete:** `figma analyze`, `migrate analyze`, and the offline
  benchmark use compatibility adapters; HTML and Figma byte-equivalence tests
  protect existing Design Document behavior.
- **AG-104 complete:** architecture tests prevent shared matching/planning code
  from importing concrete source adapters and prevent adapters from importing
  portal, command, matcher, or planner layers.
- **AG-105 complete:** Figma traversal/classification and section-boundary
  inference are isolated in pure `figma_tree` and `figma_sections` modules;
  the compatibility adapter imports their stable functions and is 429 lines
  smaller.
- **AG-106 complete:** matcher capability discovery and planner binding now use
  one shared semantic taxonomy, with aliases and slot typing covered by focused
  tests.
- **AG-107 complete:** static HTML boundary discovery, interaction association,
  FAQ/media repair, DOM semantic ownership, responsive inference, and shared
  conversion primitives are isolated in three pure modules. The compatibility
  adapter is 730 lines smaller, and every extracted module remains below 500
  lines.

**M1 acceptance complete:** typed adapters and deterministic dispatch are in
place; existing HTML/Figma commands route through compatibility adapters;
direct and registry output equivalence is covered; package import boundaries
are enforced; and Figma/HTML grouping and semantic ownership are separated from
orchestration.

Verification: 1,339 non-integration tests passed, 16 integration tests were
deselected, and the five-case offline benchmark passed with no threshold or
regression failures. Current evidence is stored under
`artifacts/benchmarks/agency-m1-complete`.

### 2026-07-16 — Keys to Success live portal verification

- Resumed the isolated `keys-to-success` profile on portal 2 without mutating
  the multi-client portal 0.
- Verified DNN/Vanjaro health, authentication, API-key access, 89 modified
  theme controls, ten KTS custom blocks, published header/footer global blocks,
  published Home content, and configured SEO.
- The structural audit passed with a 92.1 site score and 84.2 Home-page score;
  browser checks found no console errors or horizontal overflow at desktop,
  tablet, or mobile widths.
- Release remains blocked on placeholder visitor content, `#` navigation and
  CTA destinations, non-collapsing mobile navigation, and six images without
  responsive-version wrappers.

Evidence: `artifacts/e2e/keys-to-success-2026-07-16/iteration-5/live-e2e-report.md`
and `live-audit.json`.

### 2026-07-16 — M2 project workspace foundation

- **AG-201 complete:** `agency-project-v1` defines strict project identity,
  explicit target profile and expected portal ID, typed multi-source intake,
  agency-pack version, complete stage graph, decisions, fingerprint-bound
  approvals, and audit history.
- Workspace services create the predictable `sources`, `analysis`, `plans`,
  `build`, `qa`, and `history` layout; manifest writes are atomic and
  deterministic; artifact and fingerprint paths cannot escape the workspace.
- Secret-bearing metadata keys, authorization values, and secret URL query
  parameters are rejected before a manifest can be written.
- **AG-203 in progress:** `vanjaro project init` and `project status` are
  available and non-destructive. Analyze, plan, build, and verify orchestration
  commands remain part of AG-203.

Verification: 1,360 non-integration tests passed, 16 integration tests were
deselected, and the five-case benchmark passed without threshold or regression
failures. Workspace usage and safety rules are documented in
`docs/agency-project-workspace.md`; benchmark evidence is under
`artifacts/benchmarks/agency-m2-workspace`.

### 2026-07-16 — M2 resumable stage engine

- **AG-202 complete:** the stage engine enforces the full intake-to-publish
  dependency graph, stores separate input/output fingerprints, persists
  running/completed/failed transitions, and retries interrupted or failed work
  without treating it as complete.
- Completed work is skipped only when inputs are unchanged, declared artifacts
  still exist, and their current hashes match the recorded output fingerprint.
  Changed or tampered evidence reruns the stage and invalidates downstream
  state.
- Dry runs calculate the real transition but never invoke the operation and
  never write the manifest or portal.
- Portal mutation stages require approval of the current plan output; publish
  requires approval of the current verification output. Upstream changes
  supersede stale approvals.
- `vanjaro project approval request/resolve` exposes the auditable operator
  lifecycle without weakening fingerprint checks.

Verification: 1,371 non-integration tests passed, 16 integration tests were
deselected, and the five-case benchmark passed without threshold or regression
failures. Current benchmark evidence is under
`artifacts/benchmarks/agency-m2-stage-engine`.

### 2026-07-16 — M2 draft-build workflow and live Figma E2E

- **AG-203 substantially complete:** `project analyze`, `plan`, audited
  overlays, target pinning, approvals, and `build --through verify` now join
  the existing init/status commands.
- The approved build path now reconciles theme-preserve, 24 managed assets, a
  ten-block project library, isolated page drafts, standard header/footer
  globals, responsive images, and release verification against the exact
  profile/base URL/portal ID.
- Template content is part of the approved plan fingerprint. Managed custom
  blocks and globals use deterministic immutable revisions, so retries recover
  after partial writes without updating or deleting older live records.
- Semantic binding now prefers exact source roles before generic element-kind
  fallbacks. The Keys to Success draft retains all 94 eligible source text
  values, including the previously dropped CTA and media headings.
- Explicitly cleared optional slots are pruned from the component tree rather
  than rendered as empty styled controls. Authenticated visual capture now
  enables Vanjaro edit mode so hidden drafts can be inspected at desktop and
  mobile sizes.
- The live isolated draft reached page 126, version 13, with a 95 structural
  score, 15/15 responsive images, 100% eligible text coverage, and unpublished
  version-2 header/footer globals. A repeat run resumed every stage without
  portal mutation.
- Publication remains correctly blocked: 12 source actions have no URL mapping.
  Visual review also identifies header logo/mobile-menu behavior and exact
  Figma-to-theme color mapping as the next fidelity work.

Verification: 1,418 non-integration tests passed and 16 integration tests were
deselected. Live evidence and screenshots are under
`artifacts/e2e/agency-project-kts-2026-07-16`; the detailed result is
`live-e2e-report.md` in that workspace.

### 2026-07-16 — M2 responsive chrome and theme-planning hardening

- Project headers now use maintainable Bootstrap 5/GrapesJS navbar components,
  a native mobile collapse, source-only destinations, visible non-link labels
  for unresolved actions, and explicit logo evidence with an accessible brand
  fallback. They never promote an arbitrary editorial image into site branding.
- The header-composer contract is recorded in `global-block-plan.json`, and the
  plan execution contract advances with behavior changes. A live replay exposed
  and corrected the case where resumption could otherwise skip regeneration and
  leave an old portal approval attached to changed executable behavior.
- Theme planning is deterministic and GET-only. It records current and proposed
  values separately for all ten Vanjaro palette slots, maps status colors only
  from explicit semantic token names, refuses unavailable font substitutions,
  and emits strict review warnings. Application is intentionally not implemented
  by this mode and the live portal theme remains unchanged.
- Page composition is separated from page reconciliation. Global composition,
  reconciliation, and manifest persistence are also separated. All new modules
  are below the 500-line agency maintainability guideline and preserve the
  existing public APIs.
- The Keys to Success isolated draft is now page 126 version 17 with a one-line
  desktop header and visible collapsed mobile toggler. It retains 94/94 eligible
  source text values, 15/15 responsive images, a 95 structural score, and
  unpublished version-2 header/footer globals. Publication remains blocked by
  the same 12 missing source action URLs, and the absent Figma logo export is
  reported as evidence rather than guessed.

Verification: 1,435 non-integration tests passed and 16 integration tests were
deselected. The five-case HTML/Figma benchmark passed without threshold or
regression failures under `artifacts/benchmarks/agency-m2-header-theme`. Updated
live evidence and screenshots are in
`artifacts/e2e/agency-project-kts-2026-07-16`.

### 2026-07-16 — M3 hash-bound assisted image evidence

- **AG-301 complete:** image sources now use a strict, versioned request and
  evidence contract. Every observation is owned by the exact image SHA-256,
  page slug, breakpoint, viewport, and pixel dimensions, with source-specific
  geometry and provenance retained in the shared Design Document.
- **AG-302 assisted slice complete:** a pure image adapter converts supplied
  section, text, media, token, and repeat-group evidence without filesystem or
  network access. It never turns the screenshot into an editorial source asset,
  invents action URLs, or hides missing desktop/mobile evidence. A future
  evidence producer is still required for autonomous OCR/computer-vision input.
- Project intake requires explicit page, breakpoint, viewport, and evidence
  sidecar declarations for each raster. Acquisition accepts only valid local
  PNG/JPEG/WebP files, rejects workspace escapes and byte/extension mismatches,
  and persists categorized recovery guidance for missing or stale evidence.
- Source-neutral responsive composition now selects desktop, then tablet, then
  mobile as the canonical base regardless of source order. Secondary layout and
  style evidence becomes observed responsive data with explicit ambiguity and
  conflict warnings rather than silent last-write-wins behavior.
- **AG-303 first fixture complete:** a synthetic desktop/mobile raster pair,
  independent annotations, reproducible generator, and hash-bound sidecar run
  through the regular extraction and matcher benchmark. Native-template metrics
  exclude sections explicitly annotated as a required new library template;
  those remain visible planning gaps rather than false existing-template
  failures.

Verification: 1,463 non-integration tests passed and 16 integration tests were
deselected. The five-case HTML/Figma corpus and the assisted-image benchmark
both passed without threshold or regression failures. Image evidence scored
3/3 section precision and recall, 11/11 visitor-content retention, 3/3 repeat
bindings, 6/6 responsive observations, and 2/2 native-template top-1/top-3
matches. Evidence is under `artifacts/benchmarks/agency-image-assisted`.

**M3 remains active:** the current scores measure deterministic translation of
supplied evidence, not autonomous pixel interpretation or original-asset
recovery. A versioned evidence producer and representative agency image project
are still required before screenshot/image support satisfies the milestone and
overall completion rule.

### 2026-07-17 — M3 automatic evidence-provider foundation

- Added a provider-neutral detection contract and pure normalizer between
  multimodal services and the existing strict image-evidence model. Providers
  cannot select hashes, page ownership, breakpoints, viewports, or pixel
  dimensions; orchestration injects those values from verified local bytes.
- Added an OpenAI Responses API provider using inline image inputs, strict JSON
  Schema structured output, `store: false`, categorized secret-safe errors, a
  versioned prompt, configurable model/detail, and no new dependency.
- Added `vanjaro project evidence generate` with a credential-free dry run,
  explicit operator audit, complete-page breakpoint grouping, unique sidecar
  enforcement, valid-sidecar resumption, snapshot-before-overwrite, downstream
  invalidation, and rollback if manifest adoption fails.
- Provider HTTP, pure evidence normalization, project mutation, and Click
  presentation are isolated in separate modules. All new modules remain below
  the 500-line maintainability guideline.
- Independent adversarial review hardened payload/hash binding, provider result
  ownership, malformed response handling, lazy credentials for all-skip runs,
  bounded image/request sizes, manifest and raster drift detection, unique
  temporary files, and exclusive sidecar adoption locking.

Verification: 32 focused provider, normalization, orchestration, rollback, CLI,
concurrency, and architecture tests pass; the wider image/project regression
set passes 88/88; and the full non-integration suite passes 1,492 tests with 16
integration tests deselected. Both hardened benchmark runs pass without
threshold or regression failures. The assisted image case retains 3/3 section
precision/recall, 11/11 visitor content, 3/3 repeat bindings, 6/6 responsive
observations, and 2/2 native-template top-1/top-3 matches. Reports are under
`artifacts/benchmarks/agency-m3-provider-*-hardened`.

A real CLI desktop/mobile workspace dry run also succeeds, and the no-key path
returns structured recovery while preserving the manifest and writing zero
sidecars. A live provider accuracy run remains pending because the local
development environment does not currently define `OPENAI_API_KEY`; no client
image was sent externally. The assisted benchmark remains the acceptance
baseline until a credentialed provider run can be recorded.

### 2026-07-17 — M4 agency-pack governance foundation

- Added strict Semantic Version 2.0 agency-pack contracts with independently
  versioned template and modifier payloads. Pack identity, payload paths,
  schemas, declared versions, and exact byte digests fail closed before a pack
  can be used.
- Added a pure compatibility planner that compares template/modifier additions,
  removals, fingerprint changes, capability schema changes, and explicit
  migration rules against the templates/modifiers actually used by a project.
  Reports contain deterministic fingerprints and stable compatible,
  remediation-required, or blocked outcomes.
- Added `vanjaro project pack upgrade --to-version ... --dry-run`. Dry-run is
  mandatory: the command never writes a report, updates a project, or contacts a
  portal. Missing/malformed composition usage, unknown versions, missing rules,
  unreviewed used changes, and invalid replacements cannot appear compatible.
- Generated immutable Clicks and Mortars pack snapshots: 1.0.0 locks all 29
  validated templates and the modifier catalog; 1.0.1 is an explicit
  governance-only upgrade using the unchanged independently versioned payloads;
  1.1.0 adds exact physical slot ownership and cardinality. Published history
  is digest-locked and never regenerated; the deterministic generator writes
  only the current release.
- An adversarial review found and corrected two false-compatible paths: absent
  project usage and missing/invalid entry template IDs now block or produce
  categorized recovery instead of silently disappearing from assessment.

Verification: 20 focused governance/architecture tests and 115 wider
catalog/planner/project regressions pass. The full non-integration suite passes
1,507 tests with 16 live integrations deselected. Both the five-case HTML/Figma
benchmark (`artifacts/benchmarks/agency-m4-pack-governance`) and assisted-image
benchmark (`artifacts/benchmarks/agency-m4-pack-governance-image`) pass without
threshold or regression failures.

The real planned Figma project reports 1.0.0 -> 1.0.1 compatible after verifying
all ten used templates (report fingerprint
`71e082f45b57944b60ffd9a809370d2dcd9625f067375b0a1b9e89c4c1660020`).
The unplanned image project correctly reports blocked because template usage is
not yet available. Both commands are zero-write.

All 29 templates now carry executable physical-slot ownership and per-owner
cardinality contracts. The planner consumes those exact chunks so optional or
multi-value content cannot slide into another card or footer column.

**M4 remains active:** promotion evidence must aggregate distinct client
projects; reviewed apply/migration must snapshot, lock, replan, and invalidate
approvals; and two fully planned projects must complete that apply workflow.
Current usage and remaining work are documented in
`docs/agency-library-governance.md`.

### 2026-08-30 — M5 agency handoff and maintenance scorecard foundation

- **AG-502 foundation complete:** `vanjaro project handoff DIRECTORY` now
  produces an editor-facing `qa/agency-handoff.md` and a versioned,
  machine-readable `qa/maintenance-scorecard.json` from a verified project
  workspace. The command is local, non-networked, and does not mutate the
  project manifest, approve a gate, contact a portal, or publish.
- Eight weighted checks make publish-readiness explainable: valid plan, zero
  content loss, editable coverage, native/agency-standard component use,
  source-text retention, action destinations, blocker-free verification, and
  visual fidelity. Missing or invalid values fail closed as unavailable rather
  than earning points.
- Every plan/build/verify input is declared by and fingerprint-checked against
  its completed owning stage. The verification target must match the pinned
  profile, portal ID, and base URL. Stale, missing, malformed, non-finite, or
  out-of-domain evidence cannot produce a publish-ready scorecard.
- Output is deterministic and secret-safe: the verification completion time is
  used instead of the wall clock, JSON is strict and stably ordered, all
  evidence strings are recursively redacted, and unchanged reruns are
  byte-identical. The Markdown/JSON pair is staged and installed as one logical
  transaction; pre-commit failures restore the previous pair, while a
  post-commit cleanup failure explicitly reports that the complete new pair was
  installed and identifies the retained recovery backup.
- A three-lane Ringer goal audit identified the remaining source, workflow, and
  release evidence gaps. An adversarial handoff review found four initial
  defects and a bounded re-review found two residual defects; all six were
  confirmed and corrected with executable regression tests.

Verification: 23 focused handoff tests and 66 wider project-workflow tests pass.
The full non-integration suite passes 2,298 tests with 16 live integrations
deselected. The five-case HTML/Figma benchmark and assisted-image benchmark both
pass with no threshold or regression failures.

### 2026-08-30 — M5 exact-authority publication foundation

- **AG-501 publication foundation implemented:** `vanjaro project publish
  prepare` performs a GET-only live preflight and produces a deterministic
  review receipt. Adoption persists that receipt locally without publishing,
  and a changed receipt supersedes stale publish authority.
- `vanjaro project publish apply` requires the exact adopted receipt
  fingerprint, a publish approval bound to that fingerprint, and an identical
  action-time confirmation. The transaction publishes owned hidden global
  blocks before owned hidden pages, with a whole-set preflight, durable action
  journal, final whole-set readback, and GET-only reconciliation on resume.
- Live ownership is structural rather than name-based: globals must carry the
  project marker, while pages must carry both project and page markers. Object
  IDs, versions, content hashes, publication flags, portal identity, verify
  evidence, and handoff evidence are all bound into the receipt.
- Publication locking records the owner token, host, PID, and process-start
  identity. Publish receipt adoption, publish approval changes, and apply share
  the same cross-process authority lock. The guarded `recover-lock` command
  clears only a proven-dead owner using an exact double confirmation and never
  contacts the portal.
- The Vanjaro.AI page and global-block endpoints now advertise exact-version
  capability, read draft details from authoritative storage, and use one
  conditional database update to publish only the requested latest revision.
  Older server modules fail closed at preparation instead of silently
  publishing a different version.
- The current boundary is deliberate: this transaction publishes managed
  hidden content only. It does not rename draft pages, expose navigation, set a
  home page, replace a live route, or change site settings; those launch
  mutations require a separate collision-aware promotion transaction.

Verification: the Vanjaro.AI module builds successfully and emits
`website/bin/Vanjaro.AI.dll` (with existing DNN obsolete-API warnings). The 123
focused publication/recovery/locking tests and 22 architecture/orchestration
tests pass. The full non-integration suite passes 2,333 tests with 16 live
integrations deselected. The five-case HTML/Figma benchmark under
`artifacts/benchmarks/agency-m5-publish-foundation` and the assisted-image
benchmark under `artifacts/benchmarks/agency-m5-publish-foundation-image` both
pass with no threshold or regression failures. An adversarial Ringer review
identified recovery, ownership, authority, journal, and server concurrency
gaps; each confirmed issue was corrected and covered by executable checks.

**M5 remains active:** publication has not yet been exercised against an
authorized live portal with the newly built server module. Three representative
HTML, Figma, and image projects must still reach a current publish-ready state,
complete live smoke validation, and demonstrate the required 60% reduction in
hands-on build/tweak time. Collision-aware launch/navigation/home-page
promotion, reusable-fix promotion reporting, and the remaining M6
reliability/release controls are also outstanding.

### 2026-08-30 — M5 collision-aware launch promotion foundation

- Added `vanjaro project launch plan` as the sole deterministic authority for
  editor-facing page names/titles, explicit navigation visibility, semantic
  sibling order, parent ownership, and either an explicit managed home page or
  an explicit decision to preserve the current home page. Unknown navigation
  evidence and hidden home pages fail closed.
- Added read-only launch preview and adopted `qa/launch-review.json` receipts
  that bind the launch plan, exact hidden-publication receipt/result, current
  project and target, verified portal identity, complete namespace fingerprint,
  exact page metadata before/after states, and home transition. A changed input
  supersedes launch approval.
- Added a narrow Vanjaro.AI launch API. It inventories live pages and DNN
  `TabUrl` aliases, detects route collisions and protected/system pages, and
  performs page metadata plus optional `HomeTabId` changes in one serializable
  database transaction. Conditional predicates cover the DNN metadata token and
  every receipted name, title, path, visibility, parent, raw order, and culture
  value before commit.
- Added `vanjaro project launch apply` with exact receipt, approval, full
  action-time fingerprint confirmation, and separate home-page confirmation.
  Publish and launch share one cross-process authority lock. A durable launch
  journal supports unknown-outcome adoption without a duplicate POST and exact
  GET-only completed reentry; any mixed or third state fails closed.
- DNN raw `TabOrder` values are preserved rather than confused with the design
  document's semantic sibling indexes. Managed relative order is verified before
  adoption. DNN `TabName` remains the route authority; the tool does not claim
  an independently writable slug contract.
- Recovery reconciles the atomic batch only as all-before or all-after. A mixed
  state is an integrity failure and triggers no continuation POST. Automatic
  rollback is not attempted, and temporary agency-draft routes are not retained
  as redirects. Those are visible review warnings rather than hidden behavior.
- The exact transaction intentionally bypasses `TabController.UpdateTab`; it
  rebuilds paths and clears caches but does not create DNN redirect history,
  raise tab-update extension events, or synchronously reindex search/content.
  Public-route, navigation, editor, and search smoke checks remain required for
  authorized production acceptance.

Verification: 35 focused launch/plan/authority-lock tests pass. The full
non-integration suite passes 2,363 tests with 16 live integrations deselected,
and the Vanjaro.AI module builds successfully to
`website/bin/Vanjaro.AI.dll`. The five-case HTML/Figma benchmark under
`artifacts/benchmarks/agency-m5-launch-foundation` and assisted-image benchmark
under `artifacts/benchmarks/agency-m5-launch-foundation-image` both pass with no
threshold or regression failures. A three-lane Ringer re-review confirmed the
home, friendly-URL, apply-result, atomic-recovery, and CLI fixes; its Windows
gate follow-ups found bounded retry, errno-classification, cleanup, and coverage
gaps, all of which were corrected and exercised by Windows-specific tests.

The foundation has not been deployed to or applied on an authorized live
portal. M5 therefore remains active pending live route/navigation/editor/search
smoke evidence, representative HTML/Figma/image project runs against isolated
portals, and measured hands-on time reduction.

### 2026-08-30 — M6 release-readiness foundation

- Added a dependency-free reliability layer for strict canonical JSON,
  atomic writes, non-finite and duplicate-key rejection, redacted
  `diagnostic-v1` errors, manifest-scoped secret scanning, and deterministic
  performance-budget evaluation.
- Added one tracked compatibility policy covering Python/CLI, project, Design
  Document, Composition Plan, agency-pack, template-capability, publish, and
  launch contracts. DNN/Vanjaro versions remain recorded live observations;
  exact capability negotiation is the enforcement boundary.
- Replaced the silent project shape upgrade with explicit schema 1.0 to 1.1
  preview/apply migration. Apply preserves the exact prior manifest and emits a
  deterministic receipt; missing, drifted, and future shapes fail closed.
- Added read-only `vanjaro release verify`. It authenticates declared artifacts
  by SHA-256, recomputes benchmark metrics and performance budgets, validates
  current project artifacts and handoff fingerprints, checks effort reduction,
  binds live captures and smoke receipts, and always reports the complete closed
  gate set as `passed`, `failed`, or `incomplete`.
- Documented dependency direction, contract-change rules, contribution test
  boundaries, and the repeatable local/live release checklist.

The tracked release contract currently passes compatibility, scoped secret
scan, and deterministic-policy checks while reporting all missing benchmark,
project, test, performance, control, and live evidence explicitly. M6 and the
overall goal remain active; an incomplete gate cannot be waived into a release.

### 2026-09-03 — Tool-computed project quality ratios

- Three of the release quality gates (`eligible_section_editable_coverage`,
  `native_agency_component_ratio`, `body_without_generic_fallback`) were fed
  only by an operator-typed worksheet. Added the pure module
  `vanjaro_cli/design/quality_counts.py` that derives all four counts from the
  composition plan and the catalog it was planned against, with the exact
  rules in its docstring: editable coverage over body entries that bind
  content; native when the template's `native_component_ratio >= 0.90` and
  the entry's scoped CSS stays within the plan's own `css_rule_budget`;
  fallback when the template is `Content/rich-text` or the match is blocking;
  desktop/tablet/mobile from caller-supplied capture evidence only, never
  invented.
- Added `vanjaro project quality DIRECTORY [--json] [--candidate-id ID
  --output PATH]`, which prints the per-section rows and writes a
  `project-quality-evidence-v1` document the release verifier accepts. The
  verify report now carries a `quality_counts` key from the same function.
- First real numbers, all from plans rather than worksheets: kts-fidelity
  editable 8/8, native 11/11, body without fallback **5/11**; northstar-recheck
  and edca-pilot 4/4 on all three. Capture evidence is 0/1 everywhere because no
  workspace-wide, page-keyed capture reader exists yet; that reader is the
  follow-up, and the worksheet template remains for that one count.
- The three real workspaces were migrated from project schema 1.0 to 1.1 with
  the reviewed `migrate-contract --apply` path (backups under
  `history/contract-migrations/`).

Verification: 2,637 non-integration tests pass with 16 live integrations
deselected. Five-case HTML/Figma and assisted-image benchmarks under
`artifacts/benchmarks/quality-counts` and `quality-counts-image` are unchanged
from the launch-foundation runs.

### 2026-09-03 — Retention becomes a benchmark gate

- `BenchmarkThresholds.visitor_content_retention` defaulted to `None`, so the
  offline benchmark computed retention but never failed on it, while the
  release contract already required 0.95. The default is now 0.95, matching
  `release/gates.py`, and a test pins it. Both corpora sit at 1.0000 (127/127
  and 11/11), so nothing changes today; a future extraction regression now
  fails the benchmark instead of only the release audit.

Verification: 2,638 non-integration tests pass with 16 live integrations
deselected; both benchmarks pass under `artifacts/benchmarks/retention-gate`
and `retention-gate-image` with no threshold or regression failures.

### 2026-09-03 — One benchmark command across every source kind

- The offline benchmark scored one manifest per invocation, so every prior
  progress entry reported two separate runs and no single number existed
  across the three source kinds. Added `vanjaro migrate benchmark-all
  --output DIR [--manifest PATH ...] [--json]` and the pure
  `vanjaro_cli/design/benchmark_combined.py`, which lays the per-corpus
  `BenchmarkReport` objects out as one metric-by-corpus table. It writes each
  corpus's own `benchmark.json`/`benchmark.md` under its manifest directory
  name plus `combined.json` and `combined.md`, and exits nonzero if any corpus
  fails.
- First combined run (`artifacts/benchmarks/combined`), both corpora passing:

  | Metric | design-benchmarks | design-image-benchmarks |
  |---|---:|---:|
  | section_boundary_precision | 1.0000 (25/25) | 1.0000 (3/3) |
  | section_boundary_recall | 1.0000 (25/25) | 1.0000 (3/3) |
  | semantic_role_accuracy | 1.0000 (25/25) | 1.0000 (3/3) |
  | visitor_content_retention | 1.0000 (127/127) | 1.0000 (11/11) |
  | group_field_association_accuracy | 1.0000 (79/79) | 1.0000 (3/3) |
  | asset_association_accuracy | 1.0000 (15/15) | not_measurable |
  | responsive_observation_coverage | 0.8864 (39/44) | 1.0000 (6/6) |
  | template_top1_accuracy | 0.9200 (23/25) | 1.0000 (2/2) |
  | template_top3_accuracy | 1.0000 (25/25) | 1.0000 (2/2) |
  | high_confidence_precision | 0.9474 (18/19) | 1.0000 (2/2) |

- The image column's small denominators are the honest shape of that corpus:
  one case, three sections. Widening it stays gated on provider credentials.

Verification: 2,648 non-integration tests pass with 16 live integrations
deselected; `benchmark-all` exits 0 with no threshold or regression failures
on either corpus.

### 2026-09-21 — Per-page responsive evidence and truthful quality coverage

- Replaced section-ID punctuation guesses with actual page identities from the
  resolved design document. Empty pages remain in the denominator; absent
  authoritative identities earn zero coverage with a diagnostic.
- Added a shared per-page capture store and reader. Capturing another page
  preserves prior pages; a partial recapture replaces that page's old evidence.
  Coverage requires current local build/target bindings, canonical design
  fingerprints, matching screenshot hashes, valid paired observations, page
  ownership, canonical viewport widths, and safe workspace paths.
- Connected quality reporting and draft verification to the same reader.
  Multi-page fidelity verification reports missing or stale pages as blockers.
  Legacy records remain distinguishable and do not earn current workspace
  coverage.
- Root review rejected the first worker's permissive missing-binding test and
  exposed a malformed-breakpoint crash. Independent acceptance checks now pass
  after both corrections; worker PASS alone was not treated as acceptance.

Root verification: **2,694 passed, 16 integration tests deselected**, plus the
independent binding/page-map check and six malformed-input cases. The real
`kts-fidelity` quality command still correctly reports capture coverage 0/1
because new bound records are absent; editable 8/8, native 11/11, and body
without fallback 5/11 remain unchanged.

Remaining: an operator-facing capture command (the recorder currently has only
test callers), real per-source portal evidence, translation improvements for
fallback-heavy projects, and measured agency effort reduction. Local artifact
binding does not prove the live portal is unchanged. See
`agency-responsive-evidence-contract.md` for the implementation and acceptance
record. The overall goal remains active.

## 2026-09-22 — Current evidence and trial readiness

This snapshot supersedes earlier open-item statements about the absence of an
operator-facing capture command; it does not replace historical test results.

- `project capture` now collects source/output evidence at the required
  breakpoints. The isolated Northstar pilot produced six real browser screenshots,
  but its fidelity score was **56.89**, below the draft threshold of 75.
  The source fixture lacked styling and media, and the output was a historical
  build, so this is capture-workflow evidence, not representative client accuracy.
  See `agency-capture-command-contract.md`.
- Explicit article category/excerpt/byline semantics now reach distinct native
  editing fields. Final root verification passed **2,957 tests**, with two skips
  and 16 integration tests deselected, including independent final-tree and
  deliberate-corruption checks. See `agency-article-retention-contract.md`.
- A separate reproducible probe found that six image destinations across a
  listing and gallery reach design evidence but not clickable composed output.
  The native-image-link correction is now accepted offline: exact native link
  ownership, safe destinations, read-back and existing-link edit compatibility
  pass 22 independent checks. Root's broader regression suite passed **3,039
  tests**, with two skips and 16 integration tests deselected. The composed
  example passes native structural validation; live renderer/editor behavior
  remains unverified.
  See `agency-image-link-retention-contract.md`.
- The card-action diagnostic found eight missing standalone controls. Extraction
  and final native ownership are now integrated offline, including absent-first
  actions, expanded repeats, grouped actions, metadata exclusions and unsafe
  targets. The related native Feature Cards repair is governed by immutable
  agency pack 1.12.0. Root's combined suite passed **3,093 tests**, with two skips
  and 16 live integrations deselected; the generated native example validates.
  Live rendering and representative accuracy remain unproven. See
  `agency-card-action-retention-contract.md`.
- Inspection of all **11** `artifacts/projects/*/project.json` manifests found
  only `live_html` sources: `wwo`, `oasis-probe`, `cmw-blog`, `rendered-home`,
  `oasis-lighting`, `kts-fidelity`, `contact-page`, `edca-pilot`, `post-security`,
  `pilot-measure`, and `northstar-recheck`. None is a Figma or image-source
  project. Benchmark fixtures are not substitutes for those representative
  project trials.
- Broader inspection found a historical real Figma trial outside that directory:
  `artifacts/e2e/agency-project-kts-2026-07-16`. Its manifest targets portal 2,
  pins pack 1.0.0, and names the Keys to Success Figma design. Cached analysis,
  24 downloaded assets, and a July live report exist. The report records 12
  unmapped actions and comparison against the live homepage, not a Figma-frame
  raster. This is a useful revalidation candidate, not current release proof.
- `artifacts/e2e/agency-image-provider-dryrun` also exists, but both source PNGs
  exactly match the committed assisted-image benchmark PNGs by SHA-256. It is
  fixture-derived intake, not a representative designer-image trial. The earlier
  projects-only inventory must not be read as an exhaustive repository inventory.
- Selection of a real Figma design and image mockup has been requested from the
  operator. Real build/capture evidence and baseline hands-on effort are still
  needed to evaluate the required 60% time reduction; no such saving is claimed.

No portal build, publication, or launch is authorized merely by this readiness
snapshot. Reviewed target and mutation receipts remain required. The overall
agency goal remains active.

### Follow-up benchmark and Figma revalidation findings

The refreshed offline reports under
`artifacts/benchmarks/agency-retention-integrated-20260922` retain the previous
aggregate scores. Their configured corpus thresholds pass, but per-case review
shows the freeform Figma fixture still chooses the wrong hero and stats templates
(including a wrong high-confidence stats match). Across the two Figma cases,
top-1 is 8/10; the combined HTML/Figma 23/25 score must not hide that weakness.
A scratch-only diagnostic in `artifacts/agency-figma-match-diagnostic.json`
now traces source geometry/cardinality through extraction and candidate scoring
before any matching change is authorized. Five missing mobile observations in
the HTML fixtures remain another known gap.

The benchmark worker finished PASS on attempt 2, authoritative exit 0. Its
first attempt ran the benchmark successfully but omitted the required notes
deliverable; the retry supplied it. Root read the produced reports and raw
retry evidence. Worker wording that repeat ownership is unavailable refers to
the absence of that exact metric name; the actual proxy reported by this corpus
is `group_field_association_accuracy` (79/79 and 3/3). Neither proxy nor fixture
success proves ownership across representative live projects.

The historical KTS Figma workspace is schema 1.0. Current `project status`
correctly refuses it until explicit migration. A read-only `migrate-contract`
preview proposed schema 1.1 plus a pending launch stage. Its original manifest
SHA-256 remained `de43f34c02c3024bf9d6d8ee01587b3c63a0de1c487d0dd5ce8561ad8295314a`.
No migration, new approval, build, publication, or portal action was performed.

## Completion rule

Passing unit tests or finishing one migration does not complete this goal. The
goal remains active until M1–M6 are implemented and the success measures are
proven from current benchmark, project, and live-portal evidence.
