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

## Completion rule

Passing unit tests or finishing one migration does not complete this goal. The
goal remains active until M1–M6 are implemented and the success measures are
proven from current benchmark, project, and live-portal evidence.
