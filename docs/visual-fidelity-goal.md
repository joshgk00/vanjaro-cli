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

## Closed goal — close the measurement gap (2026-08-04, closed 2026-08-05)

All three tasks below are complete. VF-009 landed in three parts, VF-208 found
five real vocabulary gaps, and VF-209 resolved the last three `media_position`
failures. The first real score followed immediately and is logged at the end of
this document. Retained for the reasoning; see the active goal beneath it.



The scoring stack is built and unfed. Six deterministic metrics, a capture hook,
a gate, and a project-verify blocker all exist and are tested, but no code turns
a rendered page into the observations they consume. Until that changes, every
fidelity number in this document describes the matcher and the adapters, not the
built site — and the loop that VM4 is supposed to run has nothing to rank.

**Scope, in order:**

1. **VF-009 — observation extraction.** The one task that converts a large,
   already-paid-for investment into a working measurement. Everything else in
   this goal is gated behind it.
2. **VF-208 — vocabulary coverage audit.** Cheap, and the last instance of this
   bug class moved a section from 0.836/medium to 0.968/high. Run it while
   VF-009's design settles.
3. **VF-209 — media placement from geometry.** Closes the last three responsive
   failures, which are real but small.

**Out of scope and why.** VF-008's corpus baseline and VF-206's parity run both
need the dedicated per-site portals. Those are decided but not stood up, and
standing them up is Josh's action, not an autonomous one. Do not attempt either
task, and do not substitute the shared portal — a shared portal invalidates the
run, which is worse than not having it.

**Order discipline.** VF-009 before VF-209: media placement is one of the
signals extraction consumes, and fixing it first means fixing it blind.

**Halt and report, rather than proceeding, when:**

- Extraction cannot obtain a signal a metric requires. Emit unavailable and say
  so. Never default, never zero-fill, never infer a value the page did not show.
- Closing a vocabulary gap would require widening an existing leaf's aliases and
  the corpus moves. A new leaf is safe; widening a shared one is a scoring
  change wearing a binding change's clothes.
- The first real scores arrive and they are bad. That is a finding, not a
  failure — report the number. Do not tune the metric toward a nicer one.
- Any task's remaining work needs a portal.

**Per iteration:** implement with tests, run the non-integration suite and
`vanjaro migrate benchmark` to a fresh path, report the matcher figures and the
fidelity coverage before and after, commit only on green, and append here.

**Every prohibition in VF-5 and in the loop definition above still applies.**
Most relevant to this scope: never edit a benchmark annotation, fixture, or
threshold to make a metric move. Coverage rises only because extraction
genuinely derives more evidence.

## Active goal — make the measurement mean something (2026-08-05)

The gate now scores real builds. It scored one, and returned 63.0 while four of
its six dimensions had no evidence at all. The measurement path is real; the
evidence feeding it is a third of what the metrics were designed to consume.
Until that changes, a corpus baseline would freeze a number that mostly reflects
how the source was parsed rather than how the site was built.

**Scope, in order:**

1. **VF-210 — rendered source analysis.** The unlock. A statically parsed HTML
   source carries no geometry and no observed style values, so colour,
   typography, spacing, and media are unavailable on every section and layout
   loses its bounds subscore — 0.60 of the dimension. Everything else here is
   gated behind it.
2. **VF-211 — page chrome tolerance.** A source with a nav and no footer fails
   the `global_blocks` stage, which is what scored `section.1` a zero in the
   pilot run. The zero was correct reporting of a genuinely absent section; the
   build failure behind it was not.
3. **VF-008 — the regime-1 corpus baseline**, once 1 and 2 land and the numbers
   are worth freezing. The dedicated portals now exist, so this is no longer
   blocked on Josh.
4. **VF-206 parity run** — retire the bespoke header composer once a portal run
   confirms the matched navbar reaches parity.

**Order discipline.** VF-210 before VF-008: baselining static-parse scores would
establish a regime-1 baseline that a later rendering change invalidates, forcing
either a re-baseline or a dishonest comparison. Do not start Wave 2 — the ledger
and ranking consume corpus scores that do not exist yet.

**Halt and report, rather than proceeding, when:**

- Rendering a source is not possible for a source kind. Emit unavailable and say
  so. An adapter that cannot render must not fall back to inference wearing
  rendered provenance — that laundered guess is exactly what VF-009 refused.
- The corpus baseline would need a shared portal, or publishing outside the
  isolated pilot portal. Publishing was authorized for the pilot only.
- Scores fall when rendered evidence arrives. More dimensions scoring means more
  ways to be wrong, and a lower, better-evidenced number is progress. Report it.
- Reproducing the prior baseline fails. That is a measurement fault and takes
  priority over every fix in this list.

**Per iteration:** implement with tests, run the non-integration suite and
`vanjaro migrate benchmark` to a fresh path, report the matcher figures and the
fidelity coverage before and after, commit only on green, append here, **and
update the project memory handoff so it never goes stale.**

**Every prohibition in VF-5 and in the loop definition above still applies.**

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

### Iteration — VF-206 routing (header composition through matching)

**Matcher accuracy:** top-1 1.0000 before and after; top-3 1.0000 before and
after. The measurable change is confidence, not selection: high-confidence
matches rose 11 → 12, all correct in both states. The nav section itself moved
from 0.8363 / medium to 0.9680 / high.

**The real blocker was vocabulary, not routing.** Matching the header was never
the problem — the navbar already won its section. Binding was. The template
declared `brand.title` and `item.action`, but the observed IR emits a section
element with role `brand` and repeat-item fields keyed `label`. Neither leaf had
an alias covering those, so `bind_section` raised on every required field and
the field subscore sat at 0.383. Fixed in `design/semantics.py`, the audited
place for exactly this mapping: new `brand` and `navigation_item` leaves with
their aliases and slot types, plus secondary item aliases so an observed `label`
or `navigation_item` can reach a navbar's repeat field. Both leaves are new, so
no existing template's scoring can shift — confirmed by the corpus being
unchanged at top-1 1.0000. The navbar templates were renamed onto that
vocabulary (`brand`, `item.navigation_item`).

**Routing.** `portal/global_header_matching.py` matches the header section
against the navigation-role subset of the catalog and composes from the winner
when it clears medium confidence and binds cleanly. Unfilled template slots are
blanked before composition so the navbar's six sample links never ship. Every
result carries `composition_path` and `template_id`, which `global_blocks.py`
now records on the desired entry — that is what a portal parity run will compare.

**The composer is still the fallback, deliberately.** A header with no repeat
group, a low-confidence match, or a binding failure routes to
`build_project_header` unchanged. Per Josh's decision the bespoke composer stays
until a portal run confirms parity; this iteration makes that comparison
possible rather than assuming its outcome. VF-206's acceptance criterion "the
bespoke composer is removed, not left in parallel" is therefore still open.

**Agency pack bumped to 1.3.0.** Renaming capability fields changes the template
digests, so 1.2.0 is now locked into immutable history.

Verification: 1,757 non-integration tests pass, up from 1,752. The benchmark
reports no threshold or regression failures.

### 2026-08-04 — VF-009 part one: the expected-side extractor

**Matcher:** top-1 1.0000, top-3 1.0000, unchanged — this iteration touches no
matching code. Benchmark: no threshold or regression failures. Suite 1,757 →
1,780.

**Fidelity coverage is still zero, by design.** This is half of VF-009. The
expected side now exists; nothing yet reads a rendered page, so the gate still
reports `not_scored` and `evaluate_project_fidelity` still blocks on absent
evidence. That number moves in the next iteration, not this one.

`design/fidelity_extraction.py` turns a Design Document page into
`PageObservation` bundles. Three decisions in it are worth recording because
each one chose a smaller honest score over a larger invented one:

**Inferred geometry is dropped, not scored.** `SectionGeometry` has no field for
the observation method, so once an inferred box is in the bundle it is
indistinguishable from a measured one — and bounds carry 0.60 of the layout
dimension. Rather than change a scoring contract (a regime bump) or let a guess
score as a measurement, only `RENDERED` and `API` provenance supplies bounds.
The practical cost: image-adapter sources contribute no geometry at all, and
statically-parsed HTML never did. That is the correct answer, but it means
layout will be measured on fewer sections than it looks like from the outside.

**Geometry is never borrowed across viewports.** A desktop box is not evidence
about mobile. A viewportless record is treated as the desktop base layout and
only there.

**Inferred style values are excluded too**, for the same reason: the colour and
type metrics have no way to weight a reconstruction differently once it is in
the bundle.

Focal point and crop coverage stay unavailable — both describe how a build
placed an image, so a design cannot supply either side of that comparison. Only
aspect ratio, from asset intrinsics, is knowable up front.

**One bug caught before it shipped.** The first draft treated a measured zero as
missing evidence, so a section with its padding stripped would have dropped out
of the spacing dimension instead of failing it. That is the same defect fixed in
the spacing metric during VF-004, reintroduced from the opposite side. Now
`_pixels` accepts zero and only font size uses the positive-only reader.

### 2026-08-04 — VF-009 part two: the observed side scores end to end

**Matcher:** top-1 1.0000, top-3 1.0000, untouched. Benchmark clean. Suite
1,780 → 1,800.

**Fidelity coverage: still 0 in a real project, but the scoring path now works.**
A faithful build scores 100.0, a degraded build 0.0, and a section that was
never built fails all five comparable dimensions — all proven by test, not by
inspection. What remains before a project reports a number is the browser
measurer that fills `RenderedPage` from a live page.

**Section identity is stated by the build, not guessed.** Every component the
pipeline composes already carries `data-agency-section` with the design section
ID (`portal/page_composition._namespace_components`). The observed side reads
that attribute rather than re-deriving structure from the DOM, so the two
bundles line up by construction. This was the main open risk in VF-009 and it
turned out to be already solved.

**The capture harness measures nothing structural.** `fidelity_capture` produces
screenshots and settle evidence only. Geometry, computed colour, type, padding,
and overflow cannot come from a PNG, so `PageMeasurer` is a second protocol
alongside `PageRenderer` — not a second browser stack. The pure conversion from
`RenderedPage` to observations is fully testable without a browser, which is
where all twenty of this iteration's tests live.

**Media keying.** Both sides number images in document order, so `media_2` means
the second image in the design and in the build. That is the only correspondence
available without round-tripping element identity through the composer, and it
degrades predictably: an inserted image shifts the pairing rather than silently
comparing unrelated slots.

`crop_coverage` is measured on the build but stays unavailable on the design, so
it currently scores nothing. That is correct — a design cannot say how much of a
source image a build cropped away — and it is recorded here so the asymmetry
does not later look like a bug.

### 2026-08-04 — VF-009 complete: the gate scores real evidence

**Matcher:** top-1 1.0000, top-3 1.0000, untouched. Benchmark clean. Suite
1,800 → 1,833.

**`evaluate_project_fidelity` now returns `scored` with no blockers**, proven by
a test that records evidence and reads it back through the real gate. A degraded
build recorded through the same path returns `scored` with blockers. The
`not_scored` path that has been reported since VF-007 is no longer the only
outcome the pipeline can produce.

**Coverage on a real project is still 0, and only a portal changes that.**
Everything is injected — renderer and measurer both — so the sequencing, pairing,
and failure rules are tested offline. But producing genuine numbers needs a built
page to measure, which needs the per-site portals VF-008 is blocked on. This is
the halt condition, reached honestly: the code path is complete and the first
real measurement is a portal run away.

**The browser reports, Python decides.** `MEASURE_SCRIPT` returns geometry,
computed styles, and raw text — no thresholds, no classification. Placeholder
detection in particular reuses the planner's regex rather than growing a second
copy in JavaScript where it could drift unnoticed. Every rule about what a
measurement *means* lives in `parse_measured_page`, which is why 24 of this
iteration's tests need no browser.

**Two measurements that would have been fabrications:**

- A transparent computed background is dropped rather than reported. `rgba(0,0,0,0)`
  means the section inherits what is behind it; recording it as black would have
  scored a colour the page never painted.
- A zero-sized image yields no media sample at all, because a zero box is not a
  measurement of an aspect ratio.

**Half a comparison is never recorded.** If a viewport renders but fails to
measure, neither the design side nor the capture is written for that breakpoint.
Recording the expectation alone would let the gate score a build against nothing.

**Remaining in this goal:** VF-208 (vocabulary coverage audit) and VF-209 (media
placement from geometry) are both unblocked. The first real fidelity numbers
need a portal.

### 2026-08-04 — VF-208 vocabulary coverage audit

**Matcher:** top-1 1.0000, top-3 1.0000, unchanged. High-confidence matches
12 → 13, precision still 1.0000 — strictly better, nothing displaced. Benchmark
clean. Suite 1,833 → 1,839.

**Five real gaps, found by running the adapters rather than reading them.**
Static scanning of the adapter modules was useless: roles come from lookup
tables and classifiers, not string literals. Running the real adapters over
every corpus fixture through `analyze_source` produced the actual emitted
vocabulary, and comparing it to the catalog's declared fields exposed five
item-field names that could never bind:

| Emitted name | Now reaches | Why it was invisible |
|---|---|---|
| `benefit` | `item.features`, `item.body` | Resolved to `item.benefit`, which nothing declares |
| `number` | `item.value` | Same |
| `text` | `item.body` | Same |
| `type` | `item.tag`, `item.meta` | Same |
| `event_type` | `item.tag`, `item.meta` | Same |

Every one is a **new key**, so no existing template's scoring could shift —
confirmed by the corpus holding at 1.0000. Closing `benefit` also removed
`pricing-cards-3up: item.features` from the unsatisfiable list, which is the
audit working in both directions at once.

**Nine unsatisfiable required fields remain, and they are deliberately not
"fixed".** `faq-accordion` wants a question and an answer; `pricing-cards-3up`
wants a price; both footers want column titles, column links, and a contact
title. No corpus fixture contains an FAQ, a price, or a multi-column footer, so
nothing can satisfy them. That is a **corpus coverage gap, not a vocabulary
defect** — inventing aliases to clear the list would map real content onto
fields it does not belong in, which is the exact failure this audit exists to
catch. The standing test pins the list, so adding such a fixture makes the entry
disappear rather than requiring a new alias.

**The standing test closes the detection hole.** VF-206's failure mode — a
section matching on every subscore while binding nothing — now fails at
authoring time. `tests/test_design_vocabulary_audit.py` runs the real adapters
over the corpus and asserts no emitted role is unreachable.

### 2026-08-04 — VF-209 media placement, and a reporting correction

**A correction that matters more than the task.** Iterations since VF-206 have
reported "matcher top-1 1.0000". That figure came from an ad-hoc script using
`_section_from_annotation`, which *synthesises sections from the annotation
file* — the answer key — rather than from adapter output. The real numbers, from
the benchmark's own aggregate, have been unchanged throughout:

| Metric | True value |
|---|---:|
| `template_top1_accuracy` | 0.9200 |
| `template_top3_accuracy` | 1.0000 |
| `high_confidence_precision` | 0.9091 |

The benchmark was right all along; the convenience script was measuring the
wrong thing. All matcher figures in the entries above should be read as 0.92,
not 1.00. Two real top-1 misses remain, both in `figma-freeform-nonprofit`:
`riverkind.hero` selects `centered-hero` over `split-hero`, and `riverkind.stats`
selects `stats-grid-4up` over `stats-band-3up` — the latter also costing the
high-confidence precision point.

**VF-209 result:** `responsive_observation_coverage` 0.8182 → 0.8864. All three
`media_position` failures resolved (`orbit.hero`, `riverkind.hero`,
`riverkind.story`); nothing regressed; matcher untouched. Suite 1,839 → 1,847.

**The task's premise was wrong, and the evidence said so twice.** VF-209 asked
for media placement derived from measured geometry. Geometry cannot do it:

- `orbit.hero` and `riverkind.story` have **no element bounds at all** — an
  auto-layout frame and a freeform group where the adapter records none.
- `riverkind.hero` is the only one with geometry, and it *contradicts* a
  horizontal rule: the image sits at x=680 against copy at x=120, so
  "right stacks to bottom" would produce `bottom` where the design says `top`.

What actually decides it is declared child order — the order the designer
arranged the layers — which stacking preserves. Media before all copy stacks
top, after all copy stacks bottom, interleaved stays unavailable. That rule fits
all five `media_position` expectations in the corpus with no contradictions, and
it is the same stacking model the template capabilities already declare as
`stacking_order: "source"`.

**A wrong turn worth recording.** Mid-implementation I concluded that freeform
sections order content by vertical position and rewrote the rationale to say so.
A failing test contradicted it; measuring directly showed order is declared child
order and the measured `y` is never consulted — an image at y=80, above every
text block, still stacks to the bottom when declared last. The original
reasoning was right and the "correction" was wrong. The test
`test_vertical_position_does_not_decide_the_stacking_order` now pins this so the
same mistake cannot be made silently.

**Every unblocked task in this goal is now complete.** What remains needs the
per-site portals: VF-008's regime-1 corpus baseline, VF-206's composer parity
run, and the first real fidelity coverage numbers.

### 2026-08-05 — First real fidelity score: 63.0, and what it actually measures

**The measurement path works end to end.** A build on a dedicated portal was
captured, measured, scored, and gated. `evaluate_project_fidelity` returned
`scored` with an overall of **63.0** against a draft minimum of 75, and blocked.
That is the first fidelity number this pipeline has ever produced from a real
build rather than a fixture.

**The number is honest but narrow, and must not be read as "the site is 63%
right".** Per-section, per-breakpoint:

| Section | Score | Dimensions with evidence |
|---|---:|---|
| section.1 (nav) | 0.00 | all five scored 0 — absent from the build |
| sections 2–5 | 78.75 | layout 75, integrity 90 |

Colour, typography, spacing, and media were **unavailable on every section** —
four of six dimensions contributed nothing. The cause is on the design side: a
statically parsed HTML source carries no geometry and no observed style values,
so there is nothing to compare against. VF-009 predicted exactly this when it
restricted geometry to `RENDERED` and `API` provenance; this run is the
confirmation. **A meaningful corpus baseline (VF-008) therefore requires
rendered source analysis, not static parsing.** Layout scored 75 on column and
order agreement alone, with the bounds subscore — 0.60 of that dimension —
dropping out.

`section.1` scores 0 because the nav was split into a global block and the
`global_blocks` build stage failed: the Northstar fixture has a nav but no
footer, and page chrome requires exactly one of each. The section the design
expects is genuinely absent from the build, so scoring it 0 across every
comparable dimension is correct behaviour, not a defect.

**Two integration bugs that only a real page could find.** Both were invisible
to 1,800 passing unit tests because the fixtures agreed with the code:

- **Computed colours are `rgb()`, not hex.** Browsers report
  `rgb(255, 255, 255)`; `SectionPalette` requires hex; every unit test used hex
  fixtures on both sides. The first real measurement raised a `ValidationError`.
  Normalization now happens in `fidelity_measure`, where the browser's dialect
  is translated — an unrecognized colour form is unavailable rather than guessed.
- **A draft page renders no content to a visitor.** Authenticated, Vanjaro
  serves the editor chrome; anonymous, an empty shell. `data-agency-section`
  never reaches the DOM either way, and the recorder correctly reported "no
  measurable sections" rather than inventing a score. Measuring a build requires
  publishing it, which Josh authorized for the isolated pilot portal only.

**Portals.** Six dedicated benchmark portals plus a measurement pilot portal now
exist on `vanjarocli.local`, created through the new `vanjaro portal create` so
the setup is reproducible. VF-008 is unblocked in tooling terms; it now needs
rendered-source analysis to produce numbers worth baselining.

### 2026-08-05 — VF-210: rendered source analysis, and an off-by-one that looked like evidence

**Matcher:** top-1 0.9200, top-3 1.0000, high-confidence precision 0.9091 —
unchanged, correctly, since no matching or inference code was touched. Responsive
coverage holds at 0.8864 (39/44). Benchmark clean. Suite 1,859 → 1,872.

**On a real project the four dark dimensions now have evidence.** Analyzing the
Northstar pilot source both ways:

| | Static | Rendered |
|---|---:|---:|
| Sections with measured bounds | 0/5 | 4/5 |
| Fidelity-relevant style values | 0/40 | 32/40 |

The rendered path was already built — `capture_rendered_observations` and the
whole rendered-provenance branch of `_build_document` existed and were tested.
Nothing reachable from `analyze` ever called them. This task was wiring plus one
correctness fix, not new measurement machinery.

`project analyze --render` is the explicit opt-in, and it is part of the stage
fingerprint, so switching to rendered analysis re-runs rather than resuming a
static result. A workspace-local source renders from its `file://` URI, never
from the recorded live `source_url`, so analysing a local file cannot silently
reach the network.

**The bug this found is the reason to be glad it ran on a real page.** The
browser's observation script skips anything inside a `header` or `footer`, so
Northstar's nav — which the static parser *does* extract — has no rendered
counterpart. Rendered sections were paired to static sections **by index**:

| Static section | Was given | Should have been |
|---|---|---|
| navigation | `#hero` geometry | nothing |
| hero | `#services` geometry | `#hero` |
| feature_cards | `#testimonials` geometry | `#services` |
| testimonials | `#contact` geometry | `#testimonials` |
| call_to_action | nothing | `#contact` |

Every section carried a real, correctly-measured box belonging to a different
section. Nothing was missing, no warning fired for four of the five, and the
scores would have looked measured. **A wrong box scores worse than an absent
one, because absence is reported and mis-attribution is not.**

`_pair_rendered_sections` now matches on the selector both sides already carry
(`_static_selector` against the rendered `#id`). Position is used only when the
two lists are the same length, where it is the sole available correspondence and
cannot be off by one; when identity is absent and the counts differ, no geometry
is attached at all. Duplicate rendered selectors are discarded rather than
guessed between. The nav now correctly reports unmatched, which is honest: the
browser genuinely did not measure it.

**Not fixed, deliberately.** The nav is unmeasurable through this path at all,
because the observation script excludes header content by design. Widening that
query affects what every rendered crawl considers a section, which is a change
to the evidence base rather than to this task's wiring, and it should be its own
task with its own before/after. The static nav evidence is unaffected.

**One test bug caught, of a familiar shape.** The first rendered-section helper
wrote `styles=styles or {...}`, so passing `{}` — "the browser reported no
styles" — silently substituted the full default set and the test asserting the
absence of measured styles passed vacuously. This is the third appearance of
empty-or-zero being confused with absent, after VF-004's padding and VF-009's
`_pixels`. It keeps arriving from a new direction; only `None` is absence.

**Still not a new fidelity score.** VF-210 supplies the design side. Producing an
updated number needs a build and a publish on the pilot portal, which is VF-008's
territory and the next iteration's work.

### 2026-08-06 — VF-211: page chrome tolerance, and a duplicate that was never caught

**Matcher:** top-1 0.9200, top-3 1.0000, high-confidence precision 0.9091 —
unchanged; no matching code was touched. Responsive coverage holds at 0.8864
(39/44). Benchmark clean. Suite 1,872 → 1,879.

`attach_global_wrappers` required `set(by_kind) == {"header", "footer"}` and
raised otherwise. The Northstar fixture has a nav and no footer, so the stage
refused, and **the nav the source did supply never reached the portal at all.**
That is what scored `section.1` zero in the 63.0 run. Scoring it zero was
correct — the section was genuinely absent from the build — but the build should
never have dropped it.

A page now builds the chrome it has. The absent element is reported as a warning
on the stage message and in `pages-with-globals-result.json`, and nothing is
invented to fill it: a fabricated footer puts made-up links in front of a
visitor, which VF-5 prohibits outright. A source with neither element builds its
body and reports both.

**The old guard was weaker than it looked, in the other direction.** `by_kind`
was built as a dict comprehension over the records, so two headers silently
collapsed to whichever came last and the stage carried on. The check that read
as strict enforced presence and ignored ambiguity — the harder of the two to
recover from, because there is no basis for choosing between two headers.
Duplicates now raise, and an unrecognised chrome kind raises rather than being
dropped on the floor.

So this task relaxed absence and tightened ambiguity at the same time. Those are
opposite moves, and it was the same single expression that got both wrong.

**No test covered this function before.** The full suite passed against the old
behaviour and would have passed against the new one; nothing pinned either. The
seven tests added here cover header-only, footer-only, both, neither, the
no-fabrication rule, duplicates, and an unknown kind.

**Not re-scored.** Confirming that `section.1` now scores above zero needs a
build and a publish on the pilot portal, which is VF-008's work and the next
iteration's.

### 2026-08-06 — VF-008 attempted: rendered analysis makes the plan unbuildable

**No code changed. The finding is the deliverable.** Suite unchanged at 1,879.
Benchmark clean. Matcher top-1 0.9200, top-3 1.0000, precision 0.9091;
responsive coverage 0.8864 (39/44) — all untouched.

VF-211 works. The pilot rebuild reached `analyze` and `plan` with rendered
evidence and did not fail at `global_blocks`. It stopped one step earlier
instead, at the approval gate:

```
cannot approve plan with 4 unresolved validation issue(s)
  section.2: scoped CSS rule count 26 exceeds budget 12
  section.3: scoped CSS rule count 24 exceeds budget 12
  section.4: scoped CSS rule count 25 exceeds budget 12
  section.5: scoped CSS rule count 26 exceeds budget 12
```

Controlled comparison on one source, changing only the analysis mode:

| | Static | Rendered |
|---|---:|---:|
| `issue_count` | 0 | 3 |
| `scoped_css_rule_count` | 0 | 75 |
| `scoped_css_bytes` | 8 | 1678 |
| `valid` | true | false |

**Measurement evidence and reproduction instructions are not the same thing,
and one property set is currently doing both jobs.** `MEASURE_SCRIPT` records
about thirty computed properties per section because the metrics need them to
compare. `style_translation` maps nearly all of them to CSS because it treats
every observed property as design intent to reproduce. `display`, `position`,
`visibility`, `opacity`, `transform`, `order`, and `flex_wrap` are incidental
computed state. Emitting them as scoped CSS pins a block to one browser's
layout, and works directly against the native-component and editable-coverage
ratios the same validation file tracks.

Filed as **VF-212**, which is now the top unblocked task and gates VF-008.

**The budget will not be raised.** `max_scoped_rules_per_section` is 12 because
blocks are meant to stay native and editable. Raising it clears the gate and
keeps the over-fit, which is the same move as widening a threshold to make a
metric pass.

**Halted before publishing, as instructed.** Two boundaries were reached and
neither was crossed:

- `project approval resolve` is a human decision by this goal's own definition —
  "no human in the loop for any step except approval and publish". The loop
  raised no approval it could then grant itself.
- There is no `project publish` command; `PUBLISH` is a gated stage with no CLI
  entry point. The loop could not have published even if it had tried.

**Pilot workspace state.** `analyze` and `plan` re-ran under rendered evidence
and are complete; the plan is invalid pending VF-212; `global_blocks` onward are
unbuilt. The portal itself was not mutated — the run stopped before any POST.

### 2026-08-06 — VF-212: a rendered plan is buildable again

**Matcher:** top-1 0.9200, top-3 1.0000, precision 0.9091; responsive coverage
0.8864 (39/44) — unchanged. Benchmark clean. Suite 1,879 → 1,885.

Same source, same fixtures, only the analysis mode differing:

| | Static | Rendered before | Rendered after |
|---|---:|---:|---:|
| `issue_count` | 0 | 3 | **0** |
| `scoped_css_rule_count` | 0 | 75 | **21** |
| `scoped_css_bytes` | 8 | 1678 | **558** |
| `valid` | true | false | **true** |

Static output is byte-identical to before. **Scoring lost nothing**: the pilot
source still yields measured bounds on 4 of 5 sections and 32 of 40
fidelity-relevant style values, exactly as at VF-210. Narrowing what gets
reproduced did not narrow what gets measured, which was the point.

**Two filters, both on rendered observations only.**

`_RENDERED_REPRODUCIBLE_PROPERTIES` names the properties worth reproducing.
`display`, `position`, `opacity`, `transform`, `order`, `flex-wrap`, `width`,
and `height` are not among them. The filter is keyed on provenance rather than
on the property alone, because **the same property means different things from
different sources**: a Figma frame declaring `min-height: 520px` is stating
intent, and a browser reporting `min-height` is reporting a computed fact.
Filtering by property would have discarded the Figma case, which the corpus
actually expects.

`_CSS_INITIAL_VALUES` drops a measured value equal to the CSS initial value.
`box-shadow: none`, `letter-spacing: normal`, `border-radius: 0px` — each is the
absence of a decision rather than a decision to use the default. This is the
larger of the two effects, and it generalises: any future measured property
inherits it.

Both produce a `measurement_only` decision, so the value stays in the record
with its reason. Nothing is silently dropped.

**A native utility is still allowed to claim an incidental property.** The
platform-utility layer runs first and maps `display: block` to a utility class.
That costs no scoped rule and leaves the block editable, so the filter sits
after it deliberately. Moving the filter earlier would also have suppressed
`flex-direction: column` on rendered mobile observations, which is genuine
responsive intent.

**The budget was not raised.** `max_scoped_rules_per_section` is still 12, and a
rendered section now sits around five.

`schemas/composition-plan-v2.schema.json` was regenerated by its own generator;
the only change is the new `measurement_only` enum member.

**VF-008 is unblocked in tooling terms.** It still needs the two human gates:
`project approval resolve`, and a publish path that has no CLI entry point.
