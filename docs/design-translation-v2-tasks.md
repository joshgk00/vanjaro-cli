# Design Translation v2 — Build Backlog

This backlog turns `design-translation-v2-spec.md` into bounded implementation tasks. Task IDs are stable and should be referenced in subagent handoffs, tests, and review notes.

## Implementation checkpoint — 2026-07-16

| Workstream | Status | Evidence |
|---|---|---|
| DT-001–004 contracts/corpus | Complete | Design Document v1 + schema; 5 cases, 25 sections, 42 repeat items; fixture contract tests |
| DT-101–106 HTML analysis | Complete | Static/legacy/rendered adapters, stable DOM provenance, relationships, interactions, CSS cache, viewport failure isolation |
| DT-111–115 Figma analysis | Complete | Exact 10/10 benchmark section boundaries/roles and 16/16 repeat items; resolver hooks |
| DT-121–123 matching | Complete | Deterministic top three; benchmark top-1/top-3/high-confidence precision all 1.00 on normalized cases |
| DT-131–133 style translation | Complete | Precedence, responsive decisions, scoped CSS budget, modifier/utility tests |
| DT-201–204 planning | Complete | Composition Plan v2, semantic binding, expansion/overflow policy, override audit, compatible library plans |
| DT-211–213 CLI | Complete | `migrate analyze`, additive crawl output, `figma analyze`, `blocks plan`, and `plan-validate` |
| DT-301–302 offline metrics | Complete | Five-case metric/threshold/report engine and passing `migrate benchmark` command |
| DT-303–305 closed-loop QA | Complete | Safe Vanjaro live backend/harness, three-breakpoint visual gate, maintainability/remediation reporting |
| DT-306 release verification | Complete | 25-section E2E path, offline/live suites, benchmark, schema, compatibility, and security gates pass |

## Delivery gates

| Gate | Required evidence |
|---|---|
| G0 — Contracts frozen | Design Document schema, capability schema, benchmark annotation format, compatibility policy |
| G1 — Analysis engines | HTML and Figma fixtures produce valid Design Documents with measured extraction results |
| G2 — Planning engines | Matcher, style translator, and planner produce deterministic, validated plans |
| G3 — CLI integration | Commands produce documented artifacts and preserve legacy workflows |
| G4 — Quality release | Unit, integration, benchmark, responsive, visual, security, and compatibility gates pass |

## Wave 1 — Contracts and evidence

### DT-001 — Create Design Document Pydantic models

**Owner:** WP-1  
**Dependencies:** None

**Requirements**

- Model source metadata, tokens, assets, pages, sections, layout, content elements, repeat groups, style observations, responsive observations, interactions, decorative layers, provenance, warnings, and analysis summary.
- Validate confidence ranges, stable IDs, references, enums, and schema version.
- Keep models pure and free of I/O.

**Acceptance criteria**

- Valid full and minimal fixtures parse successfully.
- Invalid confidence, missing references, duplicate IDs, and unsupported enum values fail with field paths.
- Public API is type hinted and exported.

**Tests**

- Unit tests for every model family.
- Boundary tests for confidence 0 and 1.
- Cross-reference and duplicate-ID failure tests.

### DT-002 — Add deterministic Design Document serialization

**Owner:** WP-1  
**Dependencies:** DT-001

**Acceptance criteria**

- Read/write uses UTF-8, two-space JSON indentation, and a trailing newline.
- Round-trip does not lose data.
- Repeated serialization is byte-identical after excluding documented volatile values.
- No network or portal access occurs.

**Tests**

- Byte-for-byte determinism test.
- Unicode round-trip test.
- Invalid JSON and incompatible version tests.

### DT-003 — Publish Design Document JSON Schema

**Owner:** WP-1  
**Dependencies:** DT-001

**Acceptance criteria**

- `schemas/design-document-v1.schema.json` documents every public field.
- Schema version is `1.0`.
- Committed benchmark documents validate through the project validator.

**Tests**

- Schema/model parity checks for required fields and enum values.
- Valid and invalid fixture validation tests.

### DT-004 — Define benchmark manifest and annotations

**Owner:** WP-0  
**Dependencies:** Contract coordination with DT-001

**Acceptance criteria**

- Manifest identifies source type, fixture paths, expected pages, sections, roles, groups, bindings, acceptable templates, and breakpoint availability.
- Corpus starts with at least one live-HTML fixture, one Figma fixture, and a Keys to Success regression entry or reproducible local reference.
- Fixtures contain no secrets or customer credentials.

**Tests**

- Manifest parser/shape validation.
- Referenced fixture existence checks.
- Duplicate benchmark ID checks.

### DT-005 — Record legacy baseline

**Owner:** WP-0  
**Dependencies:** DT-004

**Acceptance criteria**

- Baseline records current section hints, template selections, known gaps, and available visual scores.
- Results distinguish measured values from unavailable values.
- Keys to Success visual progression and lazy-load caveat are retained as regression evidence.

**Tests**

- Baseline document is machine readable.
- Every benchmark entry has a baseline status.

### DT-006 — Add template capability schema

**Owner:** WP-4  
**Dependencies:** None

**Acceptance criteria**

- Schema covers roles, layout, repeat groups, fields, responsive behavior, interactions, native component ratio, and modifiers.
- Invalid ratios, unknown field policies, and malformed responsive declarations fail validation.

**Tests**

- Valid minimal and full capability fixtures.
- Invalid enum/range/required-field fixtures.

### DT-007 — Annotate all tracked templates

**Owner:** WP-4  
**Dependencies:** DT-006

**Acceptance criteria**

- Every tracked block template has valid capability metadata.
- Template names remain unique and existing composition remains compatible.
- Fields describe actual slot relationships, not inferred numbering alone.
- Responsive behavior and native component ratio are explicit.

**Tests**

- Validate every template.
- Compare declared fields with enumerated slots.
- Existing block-template tests remain green.

### DT-008 — Implement capability catalog loader

**Owner:** WP-4  
**Dependencies:** DT-006, DT-007

**Acceptance criteria**

- Loader discovers templates deterministically.
- Duplicate names and invalid capabilities fail with file paths.
- Callers can query by name, role, category, interaction, and modifier.

**Tests**

- Discovery, filtering, duplicate, invalid-file, and missing-directory tests.

### DT-009 — Generate catalog documentation

**Owner:** WP-4  
**Dependencies:** DT-008

**Acceptance criteria**

- Generated catalog lists every actual template and important capabilities.
- A drift check fails when documentation differs from generated output.

**Tests**

- Golden generated-document comparison.

## Wave 2 — Source adapters and reasoning engines

### DT-101 — Convert legacy crawl sections to Design Document v1

**Owner:** WP-2  
**Dependencies:** DT-001 through DT-003

**Acceptance criteria**

- Existing migration directories can be converted without recrawling.
- Existing files are never edited in place.
- Unrecoverable relationships produce confidence warnings.
- Page, section, content, asset, and global provenance is retained.

**Tests**

- Convert representative legacy hero, cards, gallery, testimonial, pricing, and split sections.
- Missing/malformed legacy fields degrade with warnings rather than crashes where safe.

### DT-102 — Implement source-neutral grouping helpers

**Owner:** WP-2 integration owner or a separately assigned grouping package  
**Dependencies:** DT-001

**Acceptance criteria**

- Helpers group rows, columns, repetitions, and content ownership from normalized observations.
- Algorithms are deterministic and source-neutral.
- HTML/Figma adapters can share interfaces without importing one another.

**Tests**

- Synthetic geometry tests for grids, staggered grids, split media, overlays, and ambiguous groups.

### DT-103 — Produce HTML Design Documents from static crawl data

**Owner:** WP-2  
**Dependencies:** DT-101, DT-102

**Acceptance criteria**

- Static crawl output produces valid Design Documents.
- Semantic markup, headings, repeated units, links, media, and lists retain relationships.
- Chrome, dialogs, and hidden duplicate UI are excluded.

**Tests**

- Benchmark extraction precision/recall and binding accuracy tests.
- Builder-specific regression fixtures already covered by current tests remain green.

### DT-104 — Capture rendered observations at three breakpoints

**Owner:** WP-2  
**Dependencies:** DT-103

**Acceptance criteria**

- Desktop, tablet, and mobile observations are collected independently.
- Lazy loading is triggered, fonts settle, and motion is disabled.
- Partial viewport failure preserves successful observations and emits a warning.
- Geometry and supported computed styles are stored with provenance.

**Tests**

- Playwright-backed fixture test when visual extras are available.
- Mocked partial-failure and deterministic observation tests.

### DT-105 — Detect HTML interactions and responsive deltas

**Owner:** WP-2  
**Dependencies:** DT-104

**Acceptance criteria**

- Accordions, tabs, carousels, menus, videos, forms, and modal triggers are inventoried.
- Mobile navigation expansion/collapse behavior is visible.
- Unsupported interactions are explicit gaps.
- Form fields are inventoried without functional form generation.

**Tests**

- One fixture per interaction type.
- No raw form/script emission tests.

### DT-106 — Analyze page-specific stylesheets

**Owner:** WP-2  
**Dependencies:** DT-103

**Acceptance criteria**

- Stylesheets are cached by normalized URL.
- Page-specific stylesheets are included.
- Rendered values outrank static approximations.
- Failures identify page and stylesheet URL.

**Tests**

- Shared-cache, page-specific, fetch-failure, and precedence tests.

### DT-111 — Segment Figma frames into sections

**Owner:** WP-3  
**Dependencies:** DT-001 through DT-003, DT-102 interface

**Acceptance criteria**

- Page frames segment in visual order.
- Background bands, containment, whitespace, and geometry influence boundaries.
- Decorative overlaps do not create false sections.
- Every section has confidence and Figma node provenance.

**Tests**

- Auto-layout and manually positioned fixtures.
- Section precision/recall against benchmark annotations.

### DT-112 — Infer Figma layout and repeat groups

**Owner:** WP-3  
**Dependencies:** DT-111

**Acceptance criteria**

- Auto-layout fields are used when present.
- Geometry infers rows, columns, repeats, overlap, and alignment otherwise.
- Component instances and overrides become correctly bound repeat items.

**Tests**

- Auto-layout, no-auto-layout, nested instance, staggered card, and overlapping decoration fixtures.

### DT-113 — Extract Figma typography roles and tokens

**Owner:** WP-3  
**Dependencies:** DT-111

**Acceptance criteria**

- Display, heading, body, label, button, menu, and decorative typography may remain distinct.
- Multiple font families are preserved.
- Unresolved font sources are actionable warnings.

**Tests**

- Multi-font and mixed-style fixtures.
- Regression showing a design is not reduced to one global font.

### DT-114 — Associate Figma assets and decorative layers

**Owner:** WP-3  
**Dependencies:** DT-111, DT-112

**Acceptance criteria**

- Every visible fill is associated or explicitly unresolved.
- Original fills are preferred over screenshots.
- Duplicate refs download once and retain multiple owners.
- Editorial and decorative assets are distinguished.

**Tests**

- Duplicate fill, vector export, missing signed URL, and role-classification tests.

### DT-115 — Match Figma desktop/mobile frames

**Owner:** WP-3  
**Dependencies:** DT-111 through DT-114

**Acceptance criteria**

- Paired sections use name, component identity, content, and order evidence.
- Observed and inferred responsive behavior are distinguished.
- Ambiguous pairing emits alternatives and confidence.

**Tests**

- Paired frame, desktop-only, renamed section, reordered section, and ambiguous pair fixtures.

### DT-121 — Implement template candidate scorer

**Owner:** WP-5  
**Dependencies:** DT-001, DT-008

**Acceptance criteria**

- Scores semantic role, fields, repeats, layout, responsiveness, style, interaction, and maintainability.
- Weights are configured in one typed location.
- Results include top three candidates and subscores.
- Required-field or interaction mismatch caps confidence.

**Tests**

- Determinism and each subscore dimension.
- High/medium/low confidence boundaries.
- Required interaction and required field caps.

### DT-122 — Add maintainability scoring and match overrides

**Owner:** WP-5  
**Dependencies:** DT-121

**Acceptance criteria**

- Native, editable templates outrank raw code by default.
- Custom Code is not selected when medium-or-better native candidates exist.
- Overrides record section, selected template, reason, author, and prior candidates.

**Tests**

- Native-vs-custom ranking and override audit tests.

### DT-123 — Meet matcher benchmark gates

**Owner:** WP-5  
**Dependencies:** DT-004, DT-121, DT-122

**Acceptance criteria**

- Top-1 accuracy >= 0.85.
- Top-3 accuracy >= 0.95.
- High-confidence precision >= 0.90.

**Tests**

- Offline corpus benchmark with per-case explanations.

### DT-131 — Implement theme and utility translation

**Owner:** WP-6  
**Dependencies:** DT-001, DT-008

**Acceptance criteria**

- Properties follow theme -> platform utility -> template modifier -> agency utility -> scoped CSS precedence.
- Decisions record source value, target, distance, and confidence.
- Raw source CSS is never copied automatically.

**Tests**

- Color, typography, spacing, radius, alignment, and unsupported-property cases.

### DT-132 — Implement responsive translation

**Owner:** WP-6  
**Dependencies:** DT-131

**Acceptance criteria**

- Column counts, order, visibility, navigation, image crop, and media placement map to breakpoint decisions.
- Inferred decisions remain labeled.
- Expanded mobile navigation cannot silently pass when collapse is required.

**Tests**

- Desktop/tablet/mobile grid and ordering fixtures.
- Navigation and focal-point regression tests.

### DT-133 — Implement modifier and CSS decision engine

**Owner:** WP-6  
**Dependencies:** DT-131, DT-132

**Acceptance criteria**

- Common decorative treatments use generic modifiers.
- Generated rules are scoped and measured.
- `!important` requires an allowlisted reason.
- More than 12 new section rules triggers a review finding.

**Tests**

- Modifier resolution, CSS scoping, budget, duplicate-rule, and accessibility metadata tests.

## Wave 3 — Planning and orchestration

### DT-201 — Implement semantic binding planner

**Owner:** WP-7  
**Dependencies:** DT-121 through DT-133

**Acceptance criteria**

- Design elements bind through declared capability fields.
- Repeat items bind item-by-item.
- Missing required fields fail; optional fields blank or prune placeholders.
- No placeholder text or placeholder image URL is emitted.

**Tests**

- Every supported repeat-group family.
- Missing required/optional and placeholder leakage cases.

### DT-202 — Implement Composition Plan v2 models/schema

**Owner:** WP-7  
**Dependencies:** DT-201

**Acceptance criteria**

- Plan records source section, chosen match, alternatives, block metadata, bindings, modifiers, style decisions, simplifications, and warnings.
- Serialization is deterministic and schema validated.

**Tests**

- Minimal/full round-trip, invalid references, duplicate name, and confidence-policy tests.

### DT-203 — Emit backward-compatible library plans

**Owner:** WP-7  
**Dependencies:** DT-202

**Acceptance criteria**

- Output dry-runs with existing `blocks build-library`.
- Existing assembly artifacts can mix with planned v2 sections.
- Block names are unique and deterministic.
- Global-section eligibility is preserved.

**Tests**

- Current library-plan validation and dry-run fixtures.
- Mixed legacy/v2 assembly tests.

### DT-204 — Classify simplifications and blockers

**Owner:** WP-7  
**Dependencies:** DT-202

**Acceptance criteria**

- Traits classify as omit, approximate, modifier, new template, or manual module.
- High-severity omissions block approval.
- Gap reports can consume machine-readable decisions.

**Tests**

- Severity/policy matrix tests.

### DT-211 — Extend live crawl/analyze commands

**Owner:** WP-8  
**Dependencies:** DT-103 through DT-106

**Acceptance criteria**

- Crawl can write Design Document output while preserving legacy artifacts.
- Legacy-only and re-analysis paths work.
- JSON errors use defined categories and recommended actions.

**Tests**

- CliRunner happy, legacy-only, malformed artifact, and partial viewport cases.

### DT-212 — Add `figma analyze`

**Owner:** WP-8  
**Dependencies:** DT-111 through DT-115

**Acceptance criteria**

- Writes design document, tokens, palette, and asset manifest.
- Ambiguous frames require `--node` or `--all-page-frames`.
- Dry-run does not download assets.
- Existing Figma commands remain compatible.

**Tests**

- Mocked REST CliRunner coverage for all modes and errors.

### DT-213 — Add block planning and validation commands

**Owner:** WP-8  
**Dependencies:** DT-201 through DT-204

**Acceptance criteria**

- Commands support output paths, dry run, confidence policy, simplification policy, explain, and template overrides.
- Validation covers schemas, references, template availability, bindings, placeholders, CSS budget, confidence, and blockers.

**Tests**

- CliRunner tests for each option and error category.

## Wave 4 — Metrics, portal validation, and release

### DT-301 — Implement offline extraction and matching metrics

**Owner:** WP-9  
**Dependencies:** DT-004, Wave 2 engines

**Acceptance criteria**

- Computes section precision/recall, role accuracy, content retention, binding accuracy, asset association, responsive coverage, and matcher metrics.
- Per-case failures identify expected and actual values.
- Metric regression > 0.02 can fail CI.

**Tests**

- Known synthetic metric examples and zero-denominator cases.

### DT-302 — Add offline benchmark command

**Owner:** WP-9/WP-8 integration  
**Dependencies:** DT-301

**Acceptance criteria**

- Default execution uses only committed fixtures.
- Writes JSON and human reports.
- Threshold failures return a non-zero exit.

**Tests**

- Passing, failing, filtered, missing-fixture, and JSON-output cases.

### DT-303 — Add isolated live-portal benchmark harness

**Owner:** WP-9  
**Dependencies:** DT-203, DT-211 through DT-213

**Acceptance criteria**

- Uses isolated pages or portals and snapshots before overwrite.
- Publishes, verifies anonymous render, captures, and cleans up/restores.
- Never changes unrelated pages, theme, or branding.
- Zero source URLs and placeholders remain.

**Tests**

- Marked integration tests with cleanup in `finally`.
- Failure-path cleanup tests where practical.

### DT-304 — Add three-breakpoint visual gate

**Owner:** WP-9  
**Dependencies:** DT-303

**Acceptance criteria**

- Captures settled desktop, tablet, and mobile output.
- Produces per-section and overall scores.
- Initial draft target: >=75 overall and no section <60.
- Ship gate: >=85 overall, no section <75, no mobile score <75, and no high systemic finding.

**Tests**

- Lazy-load, font-settle, animation-disable, viewport, and score-policy tests.

### DT-305 — Add maintainability and remediation reports

**Owner:** WP-9  
**Dependencies:** DT-204, DT-304

**Acceptance criteria**

- Reports native/editable coverage, blocks, templates, Custom Code, CSS size, modifiers, and manual modules.
- Findings map to section, match, style decision, and pipeline stage.
- Re-runs show score deltas and reusable-promotion candidates.

**Tests**

- Report aggregation and threshold policy fixtures.

### DT-306 — Full regression and security verification

**Owner:** Integration owner  
**Dependencies:** All tasks

**Acceptance criteria**

- Full unit suite passes.
- Live integration suite passes against the configured local target.
- Offline benchmark gates pass.
- Selected live portal/visual gates pass.
- Existing migration artifacts remain readable.
- No secrets or signed asset URLs are present in committed artifacts or command output.
- `git diff --check` passes.

**Tests**

- `pytest -m "not integration"`
- `pytest -m integration`
- Offline benchmark command
- Selected portal benchmark and visual capture
- Secret-pattern and artifact-validation scan

## Subagent handoff template

Every implementation handoff must include:

1. Task IDs completed.
2. Files changed.
3. Public interfaces added or changed.
4. Tests run and exact results.
5. Acceptance criteria satisfied.
6. Known gaps or deferred decisions.
7. Shared-contract changes requested.
8. Confirmation that unrelated dirty files were not modified.
