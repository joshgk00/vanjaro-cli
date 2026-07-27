# Visual Fidelity Closed-Loop Goal

**Status:** Active
**Started:** 2026-07-26
**Product owner:** Clicks and Mortars
**Related foundations:** `agency-tool-goal.md`, `design-translation-v2-spec.md`

## Goal

Make visual fidelity a measured, deterministic, continuously improving property
of the build pipeline rather than a human judgement made at the end of a run.

An agent must be able to build a site from a design, receive a trustworthy
numeric fidelity score, know which specific defect to fix next to raise that
score the most, apply the fix, and prove the score improved — without a human
in the loop for any step except approval and publish.

The goal is complete when fidelity scores are reproducible across runs, gate
the release path, and have demonstrably risen across the whole benchmark corpus
rather than on one favoured site.

## Problem statement

Extraction is effectively solved. The current offline benchmark scores 1.00 on
section boundary precision and recall, semantic role accuracy, visitor content
retention, repeat-field ownership, and asset association. Fidelity is lost in
the three stages *after* analysis, and none of those stages is measured.

| Gap | Evidence |
|---|---|
| No visual score in the pipeline | `design/visual_gate.py` implements the full three-breakpoint gate; nothing imports it except `tests/test_design_visual_gate.py`. `verify/draft-verification.json` carries only text coverage and URL blockers. |
| Theme never applied | Theme mode is pinned to `preserve`. The planner writes current/proposed palettes and applies nothing, so design colour and typography never reach the portal. |
| Responsive evidence incomplete | `responsive_observation_coverage` is 0.4318 (19/44) — 25 of 30 benchmark failures. All are `actual: null` for focal point, background sizing, stacking, alignment, and width collapse. |
| Navigation is outside the template system | 29 templates, and the Navigation category holds two footers. The matcher returns `footer-4col` as top-1 for `northstar.nav`, which wants `new:global-navbar`. Headers are built by a bespoke composer that cannot be matched, scored, or governed. |

A prior scoring-regime change moved a benchmark site from 79.4 to 59.4 with no
underlying quality change. Any measurement design that does not address score
comparability will produce the same false signal again.

## Product requirements

### VF-1 — Deterministic primary score

- The number that decides pass, fail, and progress is computed from rendered
  geometry, colour, and typography. It never depends on a language model.
- Re-running the scorer on unchanged inputs produces byte-identical output.
- Every score carries a `regime_version`. Scores from different regime versions
  are never compared, aggregated, or plotted on the same series.
- Changing the regime requires re-scoring every baseline in the same commit.

### VF-2 — Vision as diagnosis, not scoring

- Multimodal review produces *findings* — what is wrong, in which section, at
  which breakpoint, attributed to a pipeline stage and a source file.
- Vision output never contributes to the primary score.
- Findings are advisory input to the work queue and to systemic-severity gating.

### VF-3 — Value-ranked work queue

- Findings and metric deficits aggregate across the entire benchmark corpus,
  not per site.
- Work is ranked by measured corpus-wide impact, not by severity label alone.
- The ranking is regenerated from current evidence before each iteration, so
  the queue cannot go stale.

### VF-4 — Anti-overfit discipline

- No fix is accepted if it raises the target site's score while lowering the
  corpus mean.
- Every iteration reports per-site deltas, not just the aggregate.
- At least one corpus site is held out of the active fix loop as a control.

### VF-5 — Autonomous but bounded

- The loop runs unattended through analyse, plan, build, capture, score, rank,
  and fix.
- It never publishes, never applies to a shared portal, never fabricates
  visitor content or action URLs to clear a gate, and never edits a benchmark
  annotation to make a metric pass.
- Each iteration commits its own evidence so any run is resumable and auditable.

## Measurement architecture

Two layers, with a strict division of authority.

```text
rendered output ──┬─► Layer 1: deterministic scorer ──► score (authoritative)
                  │      geometry / colour / type            │
                  │      pure, reproducible, CI-safe         │
                  │                                          ▼
design baseline ──┘                                   visual gate (pass/fail)
                  │                                          ▲
                  └─► Layer 2: vision reviewer ─────► findings (advisory)
                         root cause + stage + file            │
                                                              ▼
                                            corpus finding ledger ──► ranked queue
```

### Layer 1 — deterministic scorer (authoritative)

Feeds `score_hook` on the existing gate. Computed per section, per breakpoint,
from the rendered page and the design document:

| Dimension | Measure |
|---|---|
| Layout | Section bounding-box IoU against design geometry; column count; order |
| Colour | CIEDE2000 ΔE between dominant rendered colours and design tokens |
| Typography | Family match, size ratio against the design type scale, weight |
| Spacing | Section padding and inter-element rhythm against design observations |
| Media | Aspect ratio, focal point, and crop against the source asset |
| Integrity | Horizontal overflow, empty slots, placeholder leakage, console errors |

Pure functions over captured observations. No network, no model, no randomness.
This is what proves improvement.

### Layer 2 — vision reviewer (advisory)

Runs on the same captures. Emits structured findings using the existing
`ReportFinding` shape in `design/reports.py` — category, severity, section,
breakpoint, `PipelineStage`, and the file most likely responsible. Answers "why
does this look wrong and what code causes it," which geometry alone cannot.

### The corpus finding ledger

The mechanism that answers "what brings the most value." Findings and Layer 1
deficits from every corpus site land in one ledger, clustered by root cause.
Each cluster is ranked by:

```
value = (sites affected × sections affected × severity weight × breakpoint weight)
        ÷ estimated fix effort
```

A defect appearing on one section of one site ranks below a defect appearing on
twelve sections across five sites, even when the single instance looks worse.
Mobile-breakpoint defects carry a higher weight because the ship gate has a
mobile-specific floor. `PromotionCandidate` already exists in `reports.py` and
extends naturally into this ledger.

## Success measures

| Measure | Required result |
|---|---:|
| Scorer reproducibility | Byte-identical across repeated runs |
| Visual gate wired into `project verify` | Yes, blocking |
| Corpus mean fidelity, single frozen regime | >= 85 |
| Lowest site score in corpus | >= 75 |
| Lowest mobile score in corpus | >= 75 |
| Sections below the section floor | 0 |
| `responsive_observation_coverage` | 1.00 |
| Template top-1 / top-3 accuracy | >= 0.90 / >= 0.97 |
| Theme tokens applied and verified on portal | 100% of planned slots |
| Held-out control site regression | None |
| Non-integration suite | 100% passing |

## Milestones

### VM1 — Make the loop measurable

- Implement the Layer 1 deterministic scorer with a frozen `regime_version` 1.
- Implement a capture hook over the existing three-breakpoint harness.
- Wire `run_visual_quality_gate` into `project verify`; write scores into
  `draft-verification.json` and block approval on the draft thresholds.
- Re-score the whole corpus once under regime 1 to establish the only baseline
  that later runs may be compared against.

**Acceptance:** every corpus site has a reproducible regime-1 score; the gate
blocks a deliberately degraded build.

### VM2 — Make the loop self-directing

- Implement the vision reviewer emitting `ReportFinding` records.
- Build the corpus finding ledger and the value ranking.
- Add `vanjaro fidelity rank` to regenerate the queue from current evidence.

**Acceptance:** the ranked queue independently surfaces theme, responsive, and
navigation as the top clusters — reproducing the manual analysis from evidence
rather than assumption.

### VM3 — Close the top-ranked gaps

Ordered by the ledger, expected to be:

- Theme translation applied under approval, snapshot, and rollback; token
  fidelity metric added to the benchmark.
- Responsive evidence to 1.00 — focal point, background sizing, alignment, and
  width collapse for both rendered HTML and Figma frame pairing.
- Navigation as a first-class template family with capability manifests; retire
  the bespoke composer into normal matching; re-baseline the matcher.

**Acceptance:** each closure shows a corpus-wide gain with no control-site
regression.

### VM4 — Prove sustained improvement

- Run the autonomous loop to convergence across the corpus.
- Demonstrate the success measures from current artefacts.
- Record the regime-1 baseline and the final scores as release evidence.

**Acceptance:** all success measures met under one unchanged regime version.

## Autonomous loop definition

Each iteration:

1. Regenerate the ranked queue from current corpus evidence.
2. Take the top unblocked cluster.
3. Implement the fix, with tests.
4. Run the non-integration suite and the offline benchmark.
5. Rebuild and re-score every corpus site under the frozen regime.
6. Accept only if corpus mean rose and no site regressed beyond tolerance;
   otherwise revert and mark the cluster blocked with its evidence.
7. Commit code and evidence together; append to the progress log.

**Stop when** every success measure is met, or the top three clusters are all
blocked, or a run cannot reproduce the prior baseline — the last case indicates
a measurement fault and takes priority over any fix.

**Never** publish, mutate a shared portal, weaken a threshold, edit a benchmark
annotation to pass, or invent visitor content or action URLs.

## Completion rule

Passing tests, or raising one site's score, does not complete this goal. It
remains active until VM1–VM4 are implemented and every success measure is
proven from current benchmark, corpus, and live-portal evidence under a single
unchanged scoring regime.

## Progress log

### 2026-07-26 — VF-010 agent skills refreshed against the current CLI

- Verified the real command surface with the Click runner rather than recall.
  `python -m vanjaro_cli.cli --help` emits nothing, so command text was taken
  from `CliRunner` output.
- `site-builder` rewritten around the project workspace: intake, target pinning,
  evidence, analyze, plan, approval, build, and verify. Superseded manual
  composition stages were removed rather than left alongside.
- Recorded the two behaviours most likely to mislead an agent: `--theme-mode`
  accepts only `preserve` and `plan` and never applies a theme, and
  `--page-mode isolated` produces hidden drafts that still require deliberate
  publication.
- Added `references/project-workflow.md` covering workspace layout, the stage
  graph and fingerprint rules, source kinds, image evidence requirements, pack
  governance, and failure modes.
- `site-migrator` now routes to the project workspace by default and keeps the
  manual six-stage path for partial migrations and repairs. It documents the
  offline `migrate analyze` to `blocks plan` conversion.
- Added `tests/test_skill_command_references.py`, which parses every skill
  document and asserts each referenced command resolves in the CLI. Verified it
  fails on an injected bogus command rather than passing vacuously.

**Not complete:** the manual six-stage body of `site-migrator` was kept. It is
superseded for new full-site migrations but could not be removed safely without
an end-to-end HTML-source project run, which needs a portal. Removal should
follow the first verified HTML-source project build.

Verification: 1,542 non-integration tests pass, up from 1,528. The five-case
offline benchmark passes with no threshold or regression failures.

Observed, not fixed: `migrate benchmark` fails with a Windows file-exists error
when `--output` points at an existing report path. There is no `--force`. Worth
a separate task.

### 2026-07-26 — VF-001 scorer contracts and regime versioning

- Added `design/fidelity.py` (360 lines) with `DimensionScore`,
  `SectionFidelityScore`, `BreakpointFidelityScore`, and `FidelityReport`.
  Every record carries `regime_version`; `CURRENT_REGIME_VERSION` is 1.
- Weights live in one typed location, `DIMENSION_WEIGHTS`, covering layout,
  colour, typography, media, spacing, and integrity, and summing to 1.0.
  Changing any weight changes the meaning of every score and requires a regime
  bump plus a full re-baseline in the same commit.
- Combining regimes raises. `aggregate_breakpoint` and `build_fidelity_report`
  raise `RegimeMismatchError` directly; direct model construction surfaces the
  same refusal through pydantic's `ValidationError`.
- An unmeasured dimension is excluded from the weighted mean rather than scored
  zero, so missing evidence cannot look like a poor build. Remaining weights are
  renormalized. A section with nothing measurable reports `score is None` and
  `require_score()` raises.
- `to_viewport_visual_score` bridges to the existing gate `ScoreHook` contract
  and refuses to pass an unmeasured section through, so absent evidence can
  never be presented to the gate as a passing score.
- Added a `forces_zero` flag with a mandatory detail, the contract hook VF-005
  needs so placeholder leakage can invalidate a section outright.
- Determinism is covered by repeated-serialization, input-order, and canonical
  breakpoint-order tests. Purity is enforced by a new architecture test
  forbidding network, filesystem, and evidence-provider imports.

Verification: 1,567 non-integration tests pass, up from 1,542. The five-case
offline benchmark passes with no threshold or regression failures.

### 2026-07-26 — VF-002 layout and geometry metric

- Added `design/fidelity_layout.py` (238 lines) scoring bounding-box IoU,
  column count, and section order. Sub-weights are bounds 0.60, columns 0.25,
  order 0.15, declared once and part of the frozen regime.
- Boxes are scaled by their own viewport width before comparison, so a 1440px
  design and a 1280px render of the same proportional layout score 100 rather
  than registering a false offset.
- **A section missing from the build scores zero; a section whose geometry
  could not be measured is unavailable.** Collapsing these would let a failed
  capture read as a missing section, or hide a missing section from the score
  entirely. Both directions are covered by tests.
- Column mismatch scores by ratio rather than all-or-nothing: a 3-column band
  rendered as 2 columns is measurably closer to correct than one rendered as
  12. Order displacement scales against section count for the same reason.
- Sections built but absent from the design are ignored by this metric.
  Unplanned extra content is a planning concern, not a geometry measurement.
- Purity is enforced by extending the VF-001 architecture guard to the new
  module.

Caught during implementation: the first test helper silently substituted a
default box when a caller passed `bounds=None`, which made the missing-geometry
case untestable and produced two false passes. Fixed with an explicit sentinel.

Verification: 1,591 non-integration tests pass, up from 1,567. The five-case
offline benchmark passes with no threshold or regression failures.

### 2026-07-26 — VF-003 colour metric

- Added `design/fidelity_color.py` (317 lines): sRGB to linear RGB to CIE XYZ
  under D65 to CIE L*a*b*, then full CIEDE2000 including the hue-rotation term.
  Standard library only; no dependency added.
- **Validated against twelve published CIEDE2000 reference pairs (Sharma et
  al.) to within 0.0002**, covering the blue-region and hue-rotation cases that
  a plausible-but-wrong implementation gets wrong. A self-consistent formula
  that ranks colours incorrectly would otherwise pass every internal test.
- Background, text, and accent are scored separately and weighted 0.45 / 0.35 /
  0.20 by perceived area, so a correct background cannot mask a wrong accent
  and the detail names which role drifted.
- Perceptual distance maps to score by linear falloff to zero at ΔE 25. Under
  ΔE 1 is imperceptible, so ordinary drift stays in the upper range while an
  unrelated hue separates clearly. The cap is part of the frozen regime.
- A role missing on either side is unmeasured and excluded, consistent with
  VF-001. Palettes sharing no role return an unavailable score rather than a
  default.
- Greyscale is covered explicitly: neutrals carry near-zero a/b, so only the
  lightness term can move, and a colour swapped for grey is penalised.

Verification: 1,643 non-integration tests pass, up from 1,591. The five-case
offline benchmark passes with no threshold or regression failures.

### 2026-07-26 — VF-004 typography and spacing metrics

- Added `design/fidelity_type.py` (283 lines) producing both the typography and
  spacing dimension scores. Typography sub-weights are family 0.40, size 0.40,
  weight 0.20; spacing is padding 0.60, rhythm 0.40. Both are frozen regime
  values.
- **A refused font substitution scores as unavailable, not as a failure.** When
  the theme planner declines to guess at an unavailable family, that is correct
  behaviour; scoring it as a miss would punish the pipeline for its honesty and
  push the fix loop toward fabricating a substitute. A refusal now scores
  strictly higher than a wrong substitute, which is covered by a test.
- Font stacks normalize to their primary family, so quoting and fallback lists
  are not treated as fidelity differences.
- `type_scale_ratio` exposes the scale itself, so a uniformly shrunk design can
  be told apart from a compressed one during diagnosis. Under compression the
  larger roles drift more, and the section score sits between the extremes.
- Sizes and weights score by ratio rather than exact match, keeping a gradient
  for the fix loop to climb.

Caught during implementation: the ratio helper initially treated a measured
**zero** as missing evidence, so a section whose padding was stripped entirely
would have dropped out of the score rather than failing it. Zero is a
measurement; only `None` is an absence. Fixed, and the test now asserts the
exact resulting score instead of merely "not perfect".

Verification: 1,673 non-integration tests pass, up from 1,643. The five-case
offline benchmark passes with no threshold or regression failures.

### 2026-07-26 — VF-005 media and integrity metrics

- Added `design/fidelity_media.py` (262 lines) producing the media and
  integrity dimension scores. Media sub-weights are aspect 0.40, focal 0.35,
  crop 0.25; integrity penalties are overflow 40, empty slot 15 each, console
  error 10 each. All are frozen regime values.
- **Placeholder leakage sets `forces_zero`**, driving the whole section score
  to zero through the VF-001 contract. Shipping `Lorem ipsum` or a stock
  placeholder is never an acceptable build at any score. A test confirms a
  section that is otherwise perfect still scores zero when a placeholder leaks.
- Focal point is scored by normalized distance with a cap at half the image,
  which catches a correctly sourced image cropped through its subject. Neither
  geometry nor colour detects that failure.
- A designed image absent from the build scores zero rather than reading as
  absent evidence, matching the VF-002 rule for missing sections. Media that
  exists but cannot be measured is unavailable.
- Integrity with no observations at all returns unavailable rather than 100.
  An unobserved page is not a clean page, and defaulting to clean would let a
  capture failure certify a broken build.
- Placeholder leaks are reported in sorted order so the detail is deterministic
  regardless of detection order.

**Wave 1 metrics are complete.** All six dimensions declared in VF-001 now have
implementations: layout, colour, typography, spacing, media, and integrity.
Remaining in scope are VF-006 capture and VF-007 gate wiring.

Verification: 1,700 non-integration tests pass, up from 1,673. The five-case
offline benchmark passes with no threshold or regression failures.

### 2026-07-26 — VF-006 three-breakpoint capture

- Added `design/fidelity_capture.py` (221 lines) producing source/output pairs
  at the canonical 1440x900, 768x1024, and 390x844 viewports.
- **Reuses the existing Playwright harness** rather than adding a second
  browser stack. `migration.visual._settle` already loads fonts, injects the
  animation-disabling stylesheet, and walks the page to trigger lazy images,
  which is exactly the stability evidence the gate requires. `design` already
  imports from `migration.visual` in `html_adapter`, so no new boundary is
  crossed.
- Browser work sits behind a `PageRenderer` protocol, so sequencing, warnings,
  and partial-failure behaviour are fully tested without a browser. Playwright
  is imported lazily inside the renderer, so the module loads without it.
- **An unsettled capture is discarded, not scored.** A screenshot taken before
  fonts settle or lazy images load silently measures a half-loaded page, which
  is worse than no measurement. Each of the three settle flags is covered.
- **Partial failure preserves successful captures.** A mobile timeout leaves
  desktop and tablet usable and records a warning. The gate then refuses the
  incomplete set through `resolve_visual_captures`. Capture reports what it
  got; the gate decides whether that is enough. Both halves are tested.

Verification: 1,718 non-integration tests pass, up from 1,700. The five-case
offline benchmark passes with no threshold or regression failures.

### 2026-07-26 — VF-007 gate wired into project verification

- Added `design/fidelity_evaluation.py` (220 lines) assembling the six metrics
  into `SectionFidelityScore` records and providing the gate's `score_hook`.
  Expected and observed observations share one shape, so a Figma frame and a
  live page produce the same bundle and the comparison stays source-neutral.
- Added `orchestration/project_fidelity.py` (170 lines) reading
  `qa/fidelity-evidence.json`, running `evaluate_visual_gate` at draft level,
  and returning the report plus blockers.
- `draft-verification.json` advances to schema 1.1 with a `visual_fidelity`
  block carrying overall score, per-viewport scores, per-section aggregates,
  and failures. Because that file is already a fingerprinted stage artifact, a
  score change invalidates downstream publish approval through existing
  machinery; no new invalidation path was needed.
- A section absent from the build now fails every comparable dimension rather
  than reducing to a single layout zero, so one missing section cannot be
  diluted by four unmeasured dimensions.
- Degraded builds are covered by tests: a shifted and recoloured build scores
  below the draft floor, a placeholder leak zeroes an otherwise perfect build,
  and a missing section fails the gate.

**Behaviour change worth review.** Absent fidelity evidence is now a publish
blocker, not a silent pass. Two existing tests asserted `valid is True` for
builds with no visual evidence; they were updated to assert the new behaviour
rather than relaxed, since weakening the gate is prohibited. Until an
observation-extraction step exists to populate `qa/fidelity-evidence.json`,
every project will report `valid: false` with a single `not_scored` blocker.
That is intentional — an unmeasured build has not been shown to be correct —
but it changes what `project verify` reports today and should be confirmed.

**Wave 1 in-scope work is complete.** VF-010 and VF-001 through VF-007 are
done. VF-008 requires dedicated per-site portals that do not exist yet, so the
autonomous loop halts here as instructed.

Remaining before the loop can resume: stand up the per-site portals, then add
the observation-extraction step that converts a rendered page and a Design
Document into the `PageObservation` bundles this gate consumes. That extraction
is the real remaining gap and overlaps VF-203/VF-204.

Verification: 1,737 non-integration tests pass, up from 1,718. The five-case
offline benchmark passes with no threshold or regression failures.

### 2026-07-27 — VF-203/204 scoping: the 1.00 target is unreachable

VF-203 and VF-204 are being run ahead of the VF-102/103 ledger. The ledger needs
corpus scores, which need the portals VF-008 is blocked on, while the offline
benchmark already ranks the extraction metrics objectively. Responsive coverage
is 25 of the 32 remaining benchmark failures, so it is the top-ranked work by
the evidence available today.

Before implementing, the 25 responsive failures were audited against the
fixtures that must supply their evidence. **Coverage cannot reach 1.00 by
improving the adapters, because five expectations have no evidence in the
corpus at all.**

All three HTML fixtures contain no `<style>` element, no `<link>` stylesheet,
and no `@media` query. Both Figma fixtures contain only a desktop frame
(`Home / Desktop` at 1440 and `Home Freeform`); there is no mobile frame to
pair.

| Category | Count | Status |
|---|---:|---|
| No evidence, not inferable | 5 | Unreachable |
| Genuinely derivable | 20 | Implementable |

Unreachable: `min_height` `520px` and `600px`, `background_position`
`65% 50%`, and `carousel: true` on two sections. The pixel values appear in no
stylesheet, and the testimonial markup is plain `<figure>` elements with no
carousel. No honest adapter can produce these.

**Realistic ceiling is 39/44 = 0.8864**, not 1.00.

Three ways to reach 1.00 were considered and rejected. Editing annotations or
thresholds is prohibited outright. Adding `@media` blocks and a mobile Figma
frame to the fixtures would raise the number while measuring nothing new,
because the same author would be writing both the question and the answer —
the precise false-signal failure this goal exists to prevent. The corpus is
under-specified relative to its own annotations; that is a corpus defect and
should be fixed deliberately by someone authoring realistic sources without the
answer key in view, not silently inside a coverage-raising loop.

The 20 derivable observations map to standard responsive rules that a
design-translation tool should encode regardless of this benchmark, and which
DT-132 already specifies:

- Alignment read from utility classes such as `text-center` (observed, 3)
- Multi-column grids collapsing at tablet and mobile (6)
- Media moving above or below content by its desktop source order (3)
- Full-width buttons at mobile (4)
- Overlapping decorative layers flattening at mobile (2)
- Logo bars wrapping (1), horizontal action rows stacking vertically (1)

Implementation of those follows in the next iteration, targeting 19/44 → 39/44.

No code changed in this iteration; the finding is the deliverable.

### 2026-07-27 — VF-203/204 implemented: coverage 19/44 to 36/44

Coverage rose from **0.4318 (19/44) to 0.8182 (36/44)** with no threshold or
regression failures. No annotation, fixture, or threshold was touched.

VF-203, static HTML (`html_ownership.py`): alignment and button width are now
derived additively rather than as further branches of the exclusive elif chain,
because a hero can both stack its media and keep left-aligned copy.

- Alignment reads centering utilities such as `text-center`. **Absence of a
  centering utility is itself evidence** — the section inherits the document
  default — which is what `juniper.hero` and `juniper.contact` expect.
- Full-width mobile actions trigger on a styled button, or on any anchor inside
  a section whose role is a call to action. The DNN fixture carries its styling
  on an ancestor `id`, not a class, so a class-only check missed it.

VF-204, Figma (`figma_adapter.py`): the desktop-only path emitted no tablet
observation at all, and mobile emitted only deltas.

- Tablet observations are now emitted, halving grids wider than two columns.
- **Mobile inference now describes the layout at mobile rather than only what
  changed.** Emitting deltas alone silently omits facts true at 390px
  regardless of the desktop value: a single-column section is still single
  column, and nothing overlaps. This is a modelling correction, not a fitting
  exercise — both statements hold for any mobile viewport.
- Logo bars keep a two-column wrapped grid instead of a long single-file list.
- Call-to-action sections stack vertically, and gain full-width buttons when
  they actually contain an action element.

Not implemented, deliberately: the three remaining `media_position`
expectations (`orbit.hero` bottom, `riverkind.hero` and `riverkind.story` top).
The adapter derives `MediaPosition.NONE` for those sections, so emitting a
position would assert placement it never detected. Real media-placement
derivation from freeform and flex geometry is the honest fix and is larger than
this task.

Remaining 8 of 44: five unreachable per the audit above, three requiring that
media-placement work.

Verification: 1,750 non-integration tests pass, up from 1,737. Matcher metrics
are unchanged at top-1 0.9167 and top-3 1.0000.

### 2026-07-27 — VF-205 and VF-207: navigation template family

Top-1 rose from **0.9167 (22/24) to 0.9200 (23/25)**. The denominator grew
because the nav section is no longer excluded, and the numerator grew because a
navbar won it. Top-3 is 1.0000 (25/25); high-confidence precision is unchanged
at 0.9000.

**VF-205.** Added `Navigation/navbar-brand-links.json` and
`navbar-brand-links-cta.json`, both schema 1.1 with exact physical slot
contracts. Markup mirrors the live-verified composer: Bootstrap 5 navbar,
`navbar-expand-lg`, native toggler with `data-bs-toggle="collapse"`, and the
accessibility attributes the KTS portal run validated. The catalog is 31
templates and `docs/template-capability-catalog.md` was regenerated by its
documented generator.

**VF-207 — the sanctioned annotation edit, and why it is legitimate.** The nav
annotation moved from `["new:global-navbar"]` to the two real template slugs.
The `new:` prefix means "no such template exists", and the metric deliberately
skips such sections as annotated library gaps. Removing it after building the
template records that the gap was filled.

The risk was circularity: authoring a template, naming it in the annotation,
then tuning its manifest until it wins. Matcher subscores were inspected before
and after to rule that out. The navbar wins on merit:

| Candidate | Score | semantic_role | repeat_group | layout |
|---|---:|---:|---:|---:|
| `navbar-brand-links` | 0.7826 | 1.00 | 0.96 | 0.835 |
| `navbar-brand-links-cta` | 0.7726 | 1.00 | 0.96 | 0.835 |
| `footer-4col` | 0.5775 | 0.62 | 0.62 | 0.541 |

It wins by 0.21 on exact semantic role, exact repeat kind, and layout, while
carrying an `interaction` subscore of 0.0 as a penalty. The CTA variant ranks
below the plain one because its required `action` field is unfilled, which is
the correct ordering for a nav with no button. No other benchmark section
mis-matched to a navbar, and no other annotation, fixture, or threshold changed.

**Field naming corrected during implementation.** `item.links` is plural, so
the planner supplied two values per repeat item against a single physical slot.
A navigation item has exactly one destination, so the field is `item.action`,
which the taxonomy maps to `button`/`link`.

**Agency pack bumped to 1.2.0.** Adding templates to a digest-locked catalog
correctly tripped the M4 governance gates: audited executable digests, current
release digests, and immutable history all refused the change until a new
version was published. That is the governance system working as designed, not
an obstacle. Version 1.1.0 is now locked into history.

**VF-206 is not complete.** Per Josh's decision, `portal/global_header.py`
stays: it is 406 lines of live-verified composition consumed by
`portal/global_blocks.py` and `orchestration/project_planning.py`, and deleting
it on unit-test evidence alone would discard portal-proven behaviour. Routing
header composition through template matching, then retiring the composer once a
portal run confirms parity, remains outstanding.

Verification: 1,752 non-integration tests pass, up from 1,750. The benchmark
reports no threshold or regression failures.
