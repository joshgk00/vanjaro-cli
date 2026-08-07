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

### 2026-08-06 — VF-101: the vision reviewer, and why it can only be advisory

**Matcher:** top-1 0.9200, top-3 1.0000, precision 0.9091; responsive coverage
0.8864 (39/44) — unchanged, as expected from a module nothing scores from.
Benchmark clean. Suite 1,885 → 1,897.

`design/vision_review.py` reviews the VF-006 captures and returns `ReportFinding`
records: category, severity, section, breakpoint, `PipelineStage`, and the file
most likely responsible. `ReportFinding` gained optional `breakpoint` and
`source_file` fields. Both default to `None`, so every existing construction is
unchanged, and both are typed rather than stuffed into `metadata` because VF-102
clusters on exactly these two.

**VF-2 is enforced, not just intended.** `VisionReviewOutcome` carries only
`findings` and `warnings` — a test asserts that field set exactly, so a score
cannot be added without the test failing. A second test parses all eleven
scoring modules with `ast` and asserts none of them imports this one. The
dependency runs the other way: the reviewer reads captures.

**Provider output is untrusted, and repairing it would be worse than dropping
it.** A model can name a section that does not exist, a category outside the
vocabulary, or a stage that never ran. Each is dropped with a warning naming
what was wrong. A finding attached to the wrong section is not a smaller
problem than a missing finding — it is a work queue entry pointing somewhere no
work exists, and VF-102 is going to rank on these.

Dropped, each with its own test: an unknown `section_id`, an unrecognized
severity, category, or stage, an empty message or recommendation, a
non-object item, and a provider returning a bare string instead of a list.

**A failure never propagates.** A provider raising at one breakpoint costs that
breakpoint's findings and nothing else; desktop and mobile still return theirs.
`review_captures` catches broadly on purpose — a diagnostic layer that can fail
the run turns an advisory signal into a load-bearing one. Breakpoints that never
captured are reported as unreviewed rather than passing silently.

Findings come back in canonical desktop, tablet, mobile order regardless of the
order the captures arrive in, so the output is stable to compare across runs.

**No provider is wired yet.** This is the contract and the validation; the
`VisionProvider` protocol has no production implementation in this commit, which
is why every test runs without a model. VF-102 consumes these findings.

### 2026-08-06 — VF-102: the corpus finding ledger

**Matcher:** top-1 0.9200, top-3 1.0000, precision 0.9091; responsive coverage
0.8864 (39/44) — unchanged. Benchmark clean. Suite 1,897 → 1,912.

`design/finding_ledger.py` aggregates Layer 1 deficits and Layer 2 findings
across every corpus site and clusters them by root cause. It is pure, and it
ranks nothing — ranking is VF-103, and a ledger that sorted by value would
preempt the decision VF-103 exists to make. A test pins that absence.

**Deficits and findings are separate cluster kinds and never merge.** One is a
measurement and the other is an opinion. Collapsing them would let a model's
diagnosis inherit the authority of a deterministic score, which is the exact
inversion VF-2 forbids. Deficits cluster by dimension. Findings cluster by
`(pipeline_stage, category, source_file)` — the unit somebody would actually fix
in one change.

**An unmeasured dimension is not a defect.** `score is None` is excluded, so a
dimension nobody could measure never enters the queue. Ranking "we could not
look" alongside "it is broken" would send the loop to work that does not exist —
and given how much of the corpus is currently unmeasured, that cluster would
have outranked every real one. A forced zero *is* a deficit even with no score,
because VF-005 sets it precisely when the section is invalid.

**Mixed regimes raise.** `build_finding_ledger` refuses evidence spanning more
than one `regime_version`, because clustering across regimes counts numbers that
mean different things. This is the same false signal that moved a site from 79.4
to 59.4 with no quality change.

Determinism is by construction: clusters sort by kind and key, occurrences by
site, section, and canonical breakpoint order. Feeding the same sites in reverse
order produces the same ledger, which a test checks directly rather than by
serializing twice.

A finding with no section or breakpoint is reported in `warnings` and left out
of the clusters, rather than being grouped under a placeholder.

**No corpus data exists to run this on.** Like VF-101, this commit is the
contract and its validation, exercised entirely on constructed evidence. The
VM2 milestone acceptance — that the ranked queue independently surfaces theme,
responsive, and navigation as the top clusters — cannot be checked until VF-008
produces real corpus scores, and VF-008 still waits on the two human gates.

### 2026-08-06 — VF-103: the ranked queue, and the end of unblocked work

**Matcher:** top-1 0.9200, top-3 1.0000, precision 0.9091; responsive coverage
0.8864 (39/44) — unchanged. Benchmark clean. Suite 1,912 → 1,928.

`design/finding_rank.py` implements the goal's formula directly:

    value = (sites × sections × severity weight × breakpoint weight) / effort

`vanjaro fidelity rank <ledger>` recomputes it from the file on every
invocation and caches nothing, so the queue cannot report work the current
evidence no longer supports. A test proves it by ranking, rewriting the ledger,
and ranking again.

**These weights are not part of the scoring regime.** Changing one changes which
work comes first and nothing about what any build measured, so a change here
needs no re-baseline. Keeping that boundary explicit matters: the regime is
frozen precisely so scores stay comparable, and quietly attaching ranking
weights to it would make every reprioritisation look like a measurement change.

**The heaviest breakpoint decides, not the average.** Averaging would let two
desktop occurrences dilute one mobile occurrence, which is backwards — the
mobile instance is the one that can block a ship, because the gate has a
mobile-specific floor.

**Effort is an input, not a guess.** A cluster with no declared effort ranks at
1.0 and is reported as `effort_is_default`, in JSON and in the human output. A
declared effort of zero or less falls back with a warning. The alternative was a
heuristic — file count, cluster size — which would have ordered real work by a
number nobody measured and made the queue look better-informed than it is.

**Blocked clusters sort last and keep their evidence** rather than disappearing,
so the reason something was blocked stays in front of whoever reads the queue.
Ties break on key, so the order never drifts between runs.

**Wave 2 is now code-complete and entirely unexercised on real data.** VF-101,
VF-102, and VF-103 were all built and tested against constructed evidence. That
is three consecutive iterations of machinery that has never seen a corpus score,
and the VM2 acceptance — that the queue independently surfaces theme,
responsive, and navigation as the top clusters — is precisely the thing
constructed evidence cannot check, because I would be writing both the question
and the answer.

**The loop stops here.** Every remaining task needs one of two things only Josh
can provide: `project approval resolve` on the pilot workspace, and a publish,
which today has no CLI entry point at all. Continuing would mean building more
layers against fixtures, and the honest read of three straight iterations of
that is that the next one adds less than the last.

### 2026-08-06 — The first honestly-evidenced score: 48.84, and three corrections

**Matcher unchanged** (top-1 0.9200, top-3 1.0000, precision 0.9091; responsive
0.8864). Benchmark clean. Suite 1,928 → 1,948.

Josh approved the `portal_mutation` gate. The pilot rebuilt end to end on portal
8 and **`global_blocks` completed**, where it previously failed — VF-211 proven
on the real pipeline, with exactly the intended warning: `no global footer was
planned; pages build without one`. VF-212 proven too: the same project replanned
from 101 scoped rules and `valid: false` to **21 rules and `valid: true`**.

**Overall fidelity is 48.84**, from freshly captured and measured evidence at all
three breakpoints with zero warnings. Desktop 37.50, tablet 54.50, mobile 54.50.

| Section | Score | |
|---|---:|---|
| section.1 (nav) | 0.00 | never measured — see below |
| section.2 | 46.50 | |
| section.3 | 67.54 | |
| section.4 | 64.13 | |
| section.5 | 66.00 | |

**This is lower than the 63.0 previously reported, and that is the expected
direction.** Four dimensions that used to contribute nothing now contribute, so
there are four more ways to be measurably wrong. The number did not get worse;
the measurement got honest.

**Correction 1 — the 63.0 was stale, and the gate could not tell.**
`qa/fidelity-evidence.json` was dated 2026-08-05 02:04, written before VF-210,
VF-211, and VF-212. `project verify` scored it and reported 63.0 while the
evidence on disk supported 48.84, because the evidence file was not one of the
verify stage's input files. The stage resumed and published a number the
evidence no longer supported — worse than reporting `not_scored`, because it
looked current. The file is now a stage input, and verify re-executes when it
changes.

**Correction 2 — measuring does not require publishing.** Every prior entry, and
the handoff memory, said a draft renders an empty shell so a build cannot be
measured until it is published. Measuring page 187 directly, while it was still
`Hidden` and unpublished, returned four sections with real geometry. `Hidden`
keeps a page out of the menu; it does not make it unreachable. **No publish
command was built, because publishing turned out not to be on the path to a
score.** `ProjectStage.PUBLISH` remains unimplemented, and that is now a
deliberate gap rather than a blocker.

**Correction 3 — `section.1` scores 0 for a different reason than recorded.**
The nav now builds. It is still never measured, because `MEASURE_SCRIPT` skips
anything inside a `header` or `footer` — the same exclusion that produced the
VF-210 pairing bug. So the nav is unmeasurable on both sides of the comparison,
and scoring it 0 penalises the build for a gap in the measurer. That is a
measurement fault, and by this goal's own stop condition it outranks the fix
loop. **Filed as VF-213.**

**One bug fixed on the way.** `SectionPalette` requires hex, and rendered
analysis now puts the browser's `rgb()` and `rgba()` on the *design* side too.
Only the observed side had been normalized, so recording evidence raised a
`ValidationError` on `rgba(0, 0, 0, 0)`. The normalizer moved to
`design/css_color.py` and both sides now call it — a second copy is exactly what
would drift, and this bug is what that drift looks like.

### 2026-08-06 — VF-213: the nav was rendering correctly and scoring zero

**Matcher unchanged.** Benchmark clean. Suite 1,948 → 1,949.

**Overall fidelity 48.84 → 75.47.** `section.1` went from 0.00 to **93.75** at
every breakpoint. Desktop 59.91, tablet 83.25, mobile 83.25.

| Section | desktop | tablet | mobile |
|---|---:|---:|---:|
| 1 (nav) | 93.8 | 93.8 | 93.8 |
| 2 | 36.6 | 65.0 | 65.0 |
| 3 | 58.1 | 85.8 | 85.8 |
| 4 | 57.6 | 85.8 | 85.8 |
| 5 | 53.5 | 85.8 | 85.8 |

The gate still refuses the build — four sections sit below the 60 section floor
at desktop — which is the floor doing its job. A 75.47 average must not hide a
36.65 section.

**The task's premise was wrong twice, and each wrong answer was one layer
closer.** VF-213 was filed as "the measurer skips header content, so scoring the
nav 0 is a measurement fault." Checking it:

1. `MEASURE_SCRIPT` has no header exclusion at all — it selects
   `[data-agency-section]`. That exclusion is in the *analysis* script, a
   different file. The filed premise was simply wrong.
2. The nav really was absent from the served page, so 0 was correct reporting.
   It was absent because the page content was still **draft version 2 against
   published version 1** — an unpublished global-block wrapper. Publishing the
   block alone changed nothing; the page content had to be published too.
3. With the nav rendering, `section.1` *still* scored 0. The global block
   stamped `data-agency-section="global-header"` — its block key — while the
   design expects the section ID. The measurer pairs on that attribute, so a
   nav that was rendering perfectly could never pair with the section it came
   from, and read as absent from the build.

**The fix is one argument.** `compose_project_global_blocks` now passes
`owner_key=section_id` instead of `entry["id"]`. A section's identity is the
design's section ID; the block key describes *where* it lives, which `page_key`
already records as `global:global-header`.

**Publishing, correctly stated this time.** The page draft is reachable while
`Hidden`, so a *page* need not be published to be measured — but its *content
version* must be, or the measurer sees the previously published version. The
last entry got this half right and half wrong. `content diff` is the check that
settles it: it reports published versus draft version and what differs.

**Nothing caught any of this.** 1,948 tests passed against a build whose nav
scored zero. The new test asserts the design's section ID reaches
`data-agency-section` and that the block key stays in `data-agency-page`.

**Recurring friction worth its own task.** A code change never invalidates a
stage fingerprint, so every fix in this iteration needed
`project analyze --refresh` to cascade. That is correct for input-based
fingerprints and wrong for a pipeline whose behaviour lives in code.

### 2026-08-06 — The desktop gap is a measurement artifact, not a build defect

**Matcher unchanged.** Benchmark clean. Suite 1,949 → 1,954. **No score changed.**

The task was "close the desktop gap": desktop 59.91 against tablet and mobile at
83.25. Breaking the pilot down by dimension shows there is no gap to close.

| | desktop | tablet | mobile |
|---|---|---|---|
| expected bounds | **yes** | no | no |
| expected padding | **yes** | no | no |
| layout score (s2–s5) | 53–64 | 100 | 100 |
| **dimension coverage** | **0.600** | 0.467 | 0.467 |

**Tablet and mobile score higher because less was measured.** VF-009 restricts
geometry to the viewport that supplied it, so the design side carries bounds and
padding only at desktop. At tablet and mobile the layout dimension loses its
bounds subscore — 0.60 of the dimension — and scores 100 on column and order
agreement alone, while spacing drops out entirely. Desktop is the only
breakpoint where those two dimensions are genuinely compared.

**This is a measurement-integrity fault, and the ship gate has a mobile-specific
floor.** Mobile is the least-measured breakpoint and the one carrying its own
release threshold, so the floor was being cleared partly by absence of evidence.
By this goal's own stop condition, that outranks the fix-loop work it was found
during, and chasing "desktop parity" would have been optimising toward a number
produced by measuring less.

`dimension_coverage` is now reported per section, per breakpoint, and in
`draft-verification.json` beside every score. It is a derived property over
dimensions already present — it reports the regime rather than changing it, so
no regime bump and no re-baseline. A test asserts a thin 90 is distinguishable
from a thorough 60, and another asserts coverage never touches a score.

**The spacing zero is real and is a corpus limitation.** Desktop spacing scores
exactly 0.00 on sections 2–5: the design expects `padding: 0px` and the build
renders 48px. The Northstar fixture has no stylesheet, so its computed padding
is the CSS initial value, while the block templates carry deliberate padding.
VF-212 established that a computed initial value states no *intent* — but VF-004
deliberately established the opposite for *scoring*, that zero is a measurement
and only `None` is absence. Reconciling those by treating expected `0px` as
absent would raise the score, and it would be fitting the rule to one
under-specified fixture. Left alone, and recorded here instead.

**Corrected expectation for the next iteration.** Raising the mobile and tablet
scores is not progress while their coverage sits at 0.467. Raising *coverage*
is, and that means responsive evidence on the design side — which is VF-203/204
territory, already at its honest ceiling for this corpus.

### 2026-08-06 — Per-breakpoint geometry was measured and discarded; 75.47 → 61.79

**Matcher unchanged.** Benchmark clean. Suite 1,954 → 1,958.

A rendered crawl measures all three viewports and records the non-desktop boxes
on each section's **responsive observation**, because the section's own
provenance describes its base layout. `_bounds` read only the section, so tablet
and mobile had no geometry: layout lost its bounds subscore — 0.60 of the
dimension — and scored 100 on column and order agreement alone. The evidence was
being captured, written to the Design Document, and thrown away at extraction.

| | before | after |
|---|---:|---:|
| overall | 75.47 | **61.79** |
| desktop | 59.91 | 59.91 |
| tablet | 83.25 | **68.56** |
| mobile | 83.25 | **56.89** |

**The score fell because the flattering numbers were the unmeasured ones**, which
is what the previous iteration predicted. Desktop is unchanged — it was already
comparing real boxes. Mobile fell furthest and is now the lowest breakpoint,
which is the honest ordering: the build reflows and the source does not.

**Two checks before trusting the drop.** The expected boxes come back with
per-viewport widths (1424 / 752 / 374) but identical `y` and `height`, which
looks like desktop geometry leaking. Measuring the fixture with plain Playwright,
outside our harness entirely, returns the same numbers: this fixture's
`#services` genuinely does not reflow vertically, because it is unstyled block
content whose text does not rewrap. The harness is faithful and the drop is real.
The observed side does vary (heights 201 / 249 / 460), and that difference is
the finding: **the built page is responsive and the source is not.**

**`dimension_coverage` did not move** — still 0.600 / 0.467 / 0.467. Layout was
already counted as measured at every breakpoint; what changed is that it is now
measured *properly* rather than on two subscores. The metric is dimension-level
and cannot see subscore completeness, which is a real limitation of the number
introduced last iteration and is recorded here rather than quietly widened.

Provenance still decides what counts: an inferred responsive box is refused, a
box is never borrowed across breakpoints, and a section provenance record naming
the breakpoint still wins. All four are tested.

### 2026-08-06 — Typography measured at last: coverage 0.60/0.47/0.47 → 0.73/0.60/0.60

**Matcher unchanged.** Benchmark clean. Suite 1,958 → 1,962.

**Coverage moved for the first time**, which is what the last two iterations
said to chase instead of the score:

| | desktop | tablet | mobile |
|---|---:|---:|---:|
| coverage before | 0.600 | 0.467 | 0.467 |
| **coverage after** | **0.733** | **0.600** | **0.600** |
| score | 59.91 → 59.14 | 68.56 → 65.95 | 56.89 → 56.62 |

Overall 61.79 → 60.57. Typography scored slightly below the dimensions already
being measured, which moved the mean down a little while adding a sixth of the
regime to every section. That trade is the point.

**The asymmetry.** The build-side measure script samples fonts per element —
`typeOf(node.querySelector('h1, h2, …'))` and `typeOf(node.querySelector('p'))`.
The analysis script recorded computed styles on the section box only, and the
typography metric reads each *element's* style. So the design side had no type
evidence anywhere and the dimension was unavailable on every section of every
breakpoint. The two sides were sampling different things.

The analysis script now samples the same way, and the samples are stamped onto
the first heading and first body element. Only the first of each: `querySelector`
returns the first match, so stamping later elements would assert a measurement
that was never taken.

**A section-level fallback was considered and rejected.** The section's computed
font is available and would have been a one-line change, but it is 16px regular
— the section box inherits body type. Using it for the heading would have
asserted "the design wants a 16px heading" and scored the build's 32px heading
as wrong. That is inventing an expectation to fill a gap, which is worse than
the gap.

**A trap worth recording.** The first attempt stamped the elements before
`enrich_section_from_static_dom`, which *replaces the content list wholesale*.
The samples vanished with no error and no warning — the document simply came
back unstamped. Anything that decorates section content must run after
enrichment.

**Still unmeasured: media, on both sides.** That is now the largest remaining
gap, and the same asymmetry question applies before assuming it is a bug.

### 2026-08-06 — Media is not an asymmetry; three images vanish and nothing says so

**No code changed. The finding is the deliverable.** Suite 1,962, benchmark
clean, matcher unchanged.

The previous iteration set the question: is media unmeasured because the two
sides sample differently, as typography was? **No.** Both sides report zero
media samples, and the reason is worse than a sampling gap: the source has three
images and the build has none.

- `assets-result.json`: `managed_assets: 0`, `uploaded_this_run: 0`
- `composed-blocks.json`: zero `<img>`
- rendered build page: zero `<img>`; rendered source page: three

**The media dimension structurally cannot catch this.** It needs a sample on
both sides. The source's assets point at `/synthetic/*.svg` files that do not
exist, so intrinsics are `None` and no aspect ratio is knowable, so the design
side has no sample either. An image absent from the build reads as *absent
evidence* rather than a missing image. **A build that drops every image scores
identically to one that renders them perfectly.** VF-005's rule that a designed
image absent from the build scores zero cannot fire, because there is nothing
for it to be absent from.

Traced to planning: `section.3` has three image elements with asset IDs, its
entry binds only `item.title` and `item.body`, and its sole warning concerns
`section_title`. The images are never mentioned and never offered to
`_bind_element` at all.

**A fix was written and reverted.** A `dropped` sink through `bind_section`
correctly reports an image rejected for an unusable source — and never fires
here, because these elements never reach that branch. A sink that never fires is
dead code wearing the appearance of coverage, so it was reverted rather than
committed. Filed as **VF-214** with the full trace.

**Deliberately not scored.** The source's images are broken references, so the
build could not have included them. Penalising the build would repeat the
spacing mistake: scoring the build for the fixture's silence. What is missing is
a *report*, not a penalty.

**Two iterations, two different answers to the same question.** Typography was
an asymmetry and a real fix. Media looked identical from the outside and is a
content-loss bug with a corpus limitation on top. The question was worth asking
both times, and worth asking again before the next dimension is assumed broken.

### 2026-08-06 — VF-214 part one: the quietest content loss in the pipeline

**Matcher figures unchanged** (top-1 0.9200, top-3 1.0000, precision 0.9091;
responsive 0.8864). Benchmark clean. Suite 1,962 → 1,966. **No score changed.**

Starting where the previous iteration said to — `_observed_fields` in
`matcher.py` — the mechanism resolved completely on the pilot's `section.3`:

| | |
|---|---|
| observed | `item.media`, aliases `('item.media', 'item.icon')` |
| `feature-cards-3up` editable | `item.action`, `item.body`, `item.title` |
| `feature-cards-3up` **static** | `item.icon` |

`represented` is the union of editable and static, so `item.media` matched
`item.icon` and counted as **represented**. It was therefore never listed in
`unsupported_source`, and binding then skipped it because only *editable* fields
bind. The section heading had no match at all and was duly reported; the three
images matched a slot that cannot hold content and were reported nowhere.

That is the whole mechanism, and it is worth naming: **a field that looks
supported but cannot receive content is quieter than one that is unsupported.**
The unsupported case is loud by design. This one passes every check.

The matcher now reports it separately: `source field 'item.media' maps only to a
static template slot, so its content cannot reach the build`. Separately,
because the two failures need different fixes — a static-only match is a library
gap, an unresolvable asset is a source problem.

**Nothing about scoring moved.** `editable_coverage` already excluded static-only
matches, so the metric was right the whole time and only the report was missing.
The warning lands on the plan entry, non-blocking; whether dropped content should
block approval stays Josh's call, per VF-214.

**Still open in VF-214.** This reports the loss; it does not stop it. The pilot
still builds without its images, and it still would even with working assets,
because `feature-cards-3up` has no editable media slot. Closing that is a
template-library change with its own before/after, and the corpus's broken
`/synthetic/*.svg` references remain a separate limitation on top.

### 2026-08-06 — VF-214 part two: why, not just what — and the audit that shrank the task

**Matcher unchanged** (0.9200 / 1.0000 / 0.9091; responsive 0.8864). Benchmark
clean. Suite 1,966 → 1,969. No score changed.

**The static-only report from part one is also an audit tool, and it made the
task much smaller than it looked.** Across the 31-template catalog:

| | |
|---|---:|
| templates with a static-only field | **3** (`feature-cards-3up`, `feature-cards-4up`, `icon-feature-list`) |
| the field, in all three cases | `item.icon` |
| templates with an *editable* media slot | 13 |

So this is not a systemic library gap. It is three icon templates, and `media`
and `icon` are deliberately cross-aliased in `semantics.py`. Both available
fixes — adding editable media slots, or narrowing the alias — reshape what every
card section builds and need a pack version bump and corpus evidence. **Neither
is this iteration's to decide**, so neither was done.

**What was done: the reverted sink, restored with the test that justifies it.**
Last iteration it was reverted as dead code because it never fired on the pilot.
That was true of the pilot and wrong in general: 13 templates have editable
media slots, so an image can reach binding and fail there for a source reason
rather than a library one.

**And the honest finding is better than expected.** On `gallery-3up`, where
`item.media` is *required*, an unresolvable image already raises
`PlanningError: required field 'item.media' is missing or has no slot`. So that
loss was never silent — but the message reads like a library gap when the real
cause is an asset that resolved to nothing. The sink now records *why*
alongside the existing error, and the two causes stay distinguishable because
they need different fixes.

**Which narrows where content can still vanish silently** to exactly two cases:
a static-only slot (reported since part one) and an *optional* editable slot
with an unresolvable asset (reported now). The required case was always loud.

Three tests: the unresolvable image records its reason alongside the raise, a
resolvable one binds and reports nothing, and the sink never changes binding.

### 2026-08-06 — Coverage is uniform across breakpoints for the first time

**Matcher unchanged** (0.9200 / 1.0000 / 0.9091; responsive 0.8864). Benchmark
clean. Suite 1,969 → 1,973.

| | desktop | tablet | mobile |
|---|---:|---:|---:|
| coverage before | 0.733 | 0.600 | 0.600 |
| **coverage after** | **0.733** | **0.733** | **0.733** |
| score | 59.14 | 65.95 → 60.40 | 56.62 → 52.17 |

Overall 60.57 → 57.24. **All three breakpoints now measure the same six-sixths
of the regime**, which is the first time the per-breakpoint numbers have been
comparable to each other at all. Every previous cross-breakpoint comparison in
this log was between differently-measured things.

**`_spacing` replaced the style set instead of merging it.** A rendered crawl
records responsive styles as *changes from desktop* — `changed_styles` in
`html_adapter` is computed by diffing each viewport against the desktop values.
So a property absent from the delta was measured and found equal, not left
unknown. Replacing the section style with the delta discarded every unchanged
property: at tablet the delta was `{width}` alone, so padding vanished and
spacing scored at desktop only, while tablet and mobile had been measured and
thrown away.

**Merging is not the borrow VF-009 forbids, and the difference is the delta
contract.** For geometry there is no such contract, so a desktop box says
nothing about mobile and is correctly refused. For rendered styles, absence is
positive evidence of equality because the adapter computed it that way. The
merge is therefore restricted to observations with `RENDERED` provenance; an
inferred responsive observation merges nothing, and a test pins that.

**The score fell again, and again because more is measured.** Spacing now scores
at tablet and mobile, where it scores the same 0.00 it already scored at
desktop — the design expects `padding: 0px` from a stylesheet-less fixture and
the build renders the template's 48px. That gap was always there; two of the
three breakpoints simply were not looking at it.

That is now four consecutive iterations where the number fell because the
measurement improved. The pilot's *build* has changed once in that time (VF-213);
everything else has been the measurement catching up to it.

### 2026-08-06 — The nav was the least-measured section and the highest-scoring one

**Matcher unchanged** (0.9200 / 1.0000 / 0.9091; responsive 0.8864; boundary
precision 1.0). Benchmark clean. Suite 1,973 → 1,975.

| | desktop | tablet | mobile |
|---|---:|---:|---:|
| coverage before | 0.733 | 0.733 | 0.733 |
| **coverage after** | **0.800** | **0.800** | **0.800** |
| score | 59.14 → 52.18 | 60.40 → 53.91 | 52.17 → 45.58 |

Overall 57.24 → 50.56. **`section.1` fell from 93.75 to about 60**, and that is
the whole story of this iteration: its 93.75 came from scoring two of six
dimensions. The nav was the least-measured section on the page and therefore the
best-looking one.

**The analysis script could not reach page chrome.** Its candidate query is
`main > section, main > article, body > section, [role="main"] > section` — none
of which match a nav inside a header — with a second filter excluding anything
under `header, footer`. So the nav carried `method: static`, no bounds, and zero
style properties, while every body section carried 32. Colour, typography, and
spacing were all unavailable on it.

This is the half of VF-213's original premise that was correct. That task was
filed as "the measurer skips header content"; the *measure* script has no such
exclusion, but the *analysis* script does, and they are different files. Both
halves of that confusion are now closed.

**The chrome root is the outermost element, not the inner nav.** The first
attempt preferred `header nav` and produced `rendered-section-5`, pairing with
nothing: the fixture puts the id on `<header id="site-nav">`, which is also what
the static extractor uses as its selector. Taking the outer element makes it
`#site-nav` and it pairs. A dialog is still excluded — measuring chrome does not
mean measuring everything.

The `rendered_section_unmatched` warning that has appeared on every pilot run
since VF-210 is now gone.

**Verification note.** The observation script only runs in a browser, so the two
new tests pin its intent — that chrome is queried and the outer root preferred —
rather than its behaviour. The behaviour is verified live above: `#site-nav`
captured at y=8.0 with 33 style properties, and the section re-analysed with
`rendered` provenance, bounds, and 32 properties.

**Five consecutive iterations of the score falling as measurement improved**,
from 75.47 to 50.56. The build has not changed since VF-213. Coverage over the
same span went 0.600/0.467/0.467 to 0.800 across the board.

### 2026-08-06 — A `file://` URL was shipped to a live page; 50.56 → 54.73

**Matcher unchanged** (0.9200 / 1.0000 / 0.9091; responsive 0.8864). Benchmark
clean. Suite 1,975 → 1,985.

**The first score rise since VF-213, and the first one not confounded by a
measurement change.** Coverage held at 0.800 across all three breakpoints while
the score rose 4.17 points, so this is the build genuinely improving rather than
the measurement moving underneath it.

| | before | after |
|---|---:|---:|
| overall | 50.56 | **54.73** |
| desktop | 52.18 | 56.35 |
| tablet | 53.91 | 58.08 |
| mobile | 45.58 | 49.75 |
| coverage | 0.800 | 0.800 |

**Found by reading a number nobody had read.** Every section reported integrity
90 with `detail: 1 console error(s)`. The error was
`Not allowed to load local resource: file:///synthetic/northstar-hero.jpg` —
**the build had shipped a `file://` URL into a live page.** A browser refuses it
outright, so on a real site that is a broken hero and one console error for
every visitor.

`_asset_value` blanked `http`, `https`, and `figma` sources to avoid hotlinking
but let every other scheme through. `file://` is the worst case and the one a
workspace-local source produces by default, so any project analysing local files
with unresolved assets shipped them.

The rule is now stated positively: a built page can load a **relative path or a
data URI**, and nothing else. Absolute schemes blank, which is what makes the
loss *visible* — the binding sink from two iterations ago now reports
`its asset resolved to no usable source` instead of the pipeline shipping a URL
that can never load. Reporting built one iteration became the diagnosis for a
defect found in another.

Verified live: console errors 0, `file://` references 0.

**This is also the first iteration where the fix loop did what it was designed
to do** — an existing measurement pointed at a specific defect, the defect was
real, fixing it raised the score, and coverage stayed put so the rise is
attributable. Ten iterations of measurement work made that possible.

Still unmeasured and needing Josh: media (VF-214), and typography on the nav,
which genuinely has no heading or paragraph to sample.

### 2026-08-06 — Columns were never measured on the build; 54.73 → 57.59

**Matcher unchanged** (0.9200 / 1.0000 / 0.9091; responsive 0.8864). Benchmark
clean. Suite 1,985 → 1,988.

Every section at every breakpoint reported `no geometry evidence for columns`.
The observed side derived columns from `gridTemplateColumns` alone, which sees
an explicit CSS grid and nothing else — and the build is Bootstrap flex
throughout. **A quarter of the layout dimension was dark on all fifteen
section-breakpoint pairs.**

Columns are now measured from geometry: the widest run of children sharing a
top edge, guarded so incidental pairings do not count — siblings must be of
similar width (within 25% of their mean) and together span at least half the
section. An explicit grid template still wins, because it states intent. A
section that renders as a single stack reports **1**, not null, because that is
what the design side states for a collapsed breakpoint and null would leave the
subscore unmeasured exactly where the comparison matters most.

| | before | after |
|---|---:|---:|
| overall | 54.73 | **57.59** |
| desktop | 56.35 | 59.29 |
| tablet | 58.08 | 60.59 |
| mobile | 49.75 | 52.87 |
| coverage | 0.800 | 0.800 |

**This rise is a measurement change, not a build improvement, and it must not be
read as one.** Unlike the previous iteration — where coverage held and the score
rose because a real defect was fixed — nothing about the build changed here. A
subscore that had never contributed started contributing, and it largely agrees:
the build renders 3 columns where the design says 3, and 1 where the design says
1. Mobile `section.4` went 20 → 44 on that agreement alone.

**So measuring more can raise a score as easily as lower it.** Five earlier
iterations lowered it and it was tempting to treat that as the rule. The
direction depends entirely on whether the newly-measured evidence agrees, and
neither direction is evidence about the build on its own.

**And `dimension_coverage` cannot see any of this**, because it counts
dimensions rather than subscores — layout was already "measured". From coverage
alone this iteration looks like a free 2.86 points. That is the limitation
recorded three iterations ago, now demonstrated rather than predicted, and it is
the strongest argument yet for making the metric subscore-aware.

The script only runs in a browser, so the three new tests pin its intent and the
guards; behaviour is verified live above — 3 columns on the card sections at
desktop and tablet, 1 everywhere at mobile.

### 2026-08-06 — Coverage was overstating by a fifth: 0.800 dimensions, 0.592 signals

**Matcher unchanged.** Benchmark clean. Suite 1,988 → 1,994. **No score changed.**

| | desktop | tablet | mobile |
|---|---:|---:|---:|
| `dimension_coverage` | 0.800 | 0.800 | 0.800 |
| **`evidence_coverage`** | **0.5917** | **0.5917** | **0.5917** |

The previous iteration demonstrated the flaw rather than predicting it: a
quarter of the layout dimension was dark on all fifteen section-breakpoint
pairs, and coverage never moved, because a dimension counts as measured the
moment one subscore lands. Layout scoring on column agreement alone read
identically to layout comparing real boxes.

`DimensionScore` now records `measured_subscores` / `total_subscores`, populated
by layout (bounds, columns, order), colour (background, text, accent),
typography (per sample), and spacing (padding, rhythm). `evidence_coverage`
aggregates them **weighted as the regime weights the dimensions they belong to**,
so a signal inside a heavy dimension counts for more than one inside a light
one — the same weighting the score itself uses.

**A dimension that reports no split counts as fully measured when it scored.**
That is the conservative reading: it can only make the number higher, never
invent evidence. Integrity has a single signal and is honestly 1/1.

`dimension_coverage` keeps its meaning exactly. Two numbers, each saying one
thing: how many dimensions contributed, and how much of the evidence they wanted
was actually there. Both now appear in the verification report.

**What this reveals about the last nineteen iterations.** Every "coverage rose"
claim in this log was measuring the coarser number. The real signal figure has
been lower throughout, and 0.592 is the first honest reading of how much of the
regime the pilot actually exercises. The direction of travel was right; the
distance was overstated.

Six tests, including that a thin layout stays distinguishable from a thorough
one at identical dimension coverage, that an unreported split cannot lower the
number, and that coverage still changes no score.

### 2026-08-06 — Colour: effective background and a sampled accent

**Matcher unchanged.** Benchmark clean. Suite 1,994 → 1,998.

The new signal-level metric picked this iteration's work, which is what VF-3 asks
of the queue. Weighted missing evidence across the pilot:

| dimension | missing |
|---|---:|
| media | 2.250 — blocked on Josh (VF-214) |
| **colour** | **2.000** |
| typography | 1.125 |
| spacing | 0.750 |
| layout / integrity | 0.000 |

Colour reported `no colour evidence for background, accent` on all fifteen
section-breakpoint pairs. Two separate causes.

**Background: transparent is not unknown.** Both scripts read the element's own
`backgroundColor`, which is `rgba(0,0,0,0)` for any section that does not paint
its own. A transparent section still shows a colour — the nearest ancestor that
paints one — so both sides now walk up to it. If nothing in the chain paints,
that stays honestly unmeasured rather than assuming the UA canvas is white.

**The Northstar fixture paints nowhere, so this changes nothing for the pilot.**
Verified separately against a page with `body{background:#123456}`: sections
report `rgb(18, 52, 86)` from the ancestor. Reachable and correct, just not
exercised here — checked before keeping it, after iteration 13 reverted a change
for looking dead when it was only dead on this one fixture.

**Accent: the same asymmetry as typography.** `_accent` reads the first action
element's own style, and the analysis script never sampled action elements, so
the design side could never supply an accent. It now samples the first
`a, button` and stamps it, matching what `querySelector` measured.

| | before | after |
|---|---:|---:|
| overall | 57.59 | **54.15** |
| `dimension_coverage` | 0.800 | 0.800 |
| **`evidence_coverage`** | 0.5917 | **0.6317** |

**This iteration is invisible to the old metric and visible to the new one** —
which is the clearest justification yet for the previous iteration. The score
fell because the accent now scores and disagrees: the source's default link blue
against the build's theme colour. Real evidence, real disagreement.

### 2026-08-06 — Body copy is a `div` in the build, so typography compared half a page

**Matcher unchanged.** Benchmark clean. Suite 1,998 → 2,000.

| | before | after |
|---|---:|---:|
| overall | 54.15 | **54.99** |
| `dimension_coverage` | 0.800 | 0.800 |
| **`evidence_coverage`** | 0.6317 | **0.6767** |

The design side had body samples on three of five sections; the build had none
on any. `typeOf(node.querySelector('p'))` finds nothing, because Vanjaro renders
body copy as `<div class="vj-text paragraph-style-1">`. The build page contains
**zero `<p>` elements**.

**This is the third dimension darkened by the two sides sampling different
things** — after typography's heading (per-section versus per-element) and media
(design intrinsics versus rendered images). The pattern is now well enough
established to state as a rule: *whenever a dimension reads unavailable, compare
what each side is sampling before looking for a bug in either.*

Body copy is now defined by shape rather than tag: the first leaf element with
text that is not a heading, link, button, or script. A `<p>` still wins when
present, because it states the author's intent, so the source side is
unchanged and the fix is additive. Both scripts share the definition, and a test
asserts they agree by construction rather than by review.

The score moved little — 54.15 to 54.99 — because the newly compared body
samples largely agree on size and weight while the family differs, which is the
same Times-New-Roman-versus-theme-font gap the heading already reported. The
coverage move is the real result: 0.6317 to 0.6767.

**Remaining weighted gaps:** media 2.250 (blocked on Josh, VF-214), spacing
0.750 (`element-gap` on all fifteen, plus the known corpus padding limitation),
and the nav's typography, which is honestly unavailable — it has no heading and
no body copy to sample.

### 2026-08-06 — Inter-element rhythm measured; 54.99 → 57.21

**Matcher unchanged.** Benchmark clean. Suite 2,000 → 2,004.

| | before | after |
|---|---:|---:|
| overall | 54.99 | **57.21** |
| **`evidence_coverage`** | 0.6767 | **0.6967 / 0.7167 / 0.6967** |

Spacing reported `no spacing evidence for element-gap` on all fifteen pairs.
**This one was not a sampling asymmetry** — the established rule was applied
first, and both sides read `row-gap` and both got `normal`, because that
property applies only to flex and grid containers. The dimension is documented
as *inter-element rhythm*, and `row-gap` is one way to achieve it, not the thing
itself.

Rhythm is now measured as the median vertical distance between consecutive
visible children. A declared `row-gap` still wins, because it states intent.

**Two structural mismatches surfaced on the way, and both are the same shape as
earlier ones.** The first attempt measured the section's own children and found
gaps on the source but none on the build: the source lays elements out as direct
children, the build wraps them in a container, so the build had exactly one child
and no rhythm. Both scripts now descend through single-child wrappers to where
the content actually sits.

**Sections 3 and 4 still report no gap on the build, correctly.** Their content
host is a card row whose children sit side by side, so there is no vertical
rhythm at that level — consecutive gaps are negative and are discarded rather
than counted. Two of five sections gained the signal; claiming the other three
would mean measuring a horizontal arrangement as a vertical one.

**A warning of my own making, cleaned up.** The effective-background check
introduced two iterations ago used a JS regex inside a non-raw Python string,
which emitted `SyntaxWarning: invalid escape sequence` on every import. It is
now a plain string comparison, and `python -W error::SyntaxWarning` imports both
modules cleanly.

### 2026-08-06 — VF-206's parity run: neither header path is correct

**No code changed. The finding is the deliverable.** Suite 2,004, benchmark
clean, matcher unchanged.

Media is blocked on Josh, and colour's remaining 1.400 is the Northstar fixture
painting no background anywhere — the ancestor walk added two iterations ago is
correct, and no honest measurement can extract a colour from a page that paints
none. So this iteration took the one substantial item that the pilot portal
finally unblocked: **VF-206's parity run**, open since 2026-07-27 pending exactly
this evidence.

The pilot's header was composed through template matching —
`composition_path: template`, `Navigation/navbar-brand-links`, zero warnings,
and every accessibility attribute VF-205 specified. That establishes the matched
path works. Parity, though, means comparing it against what the composer would
have produced from the same section, and that comparison fails.

The source declares one brand: kind `link`, role `brand`, value `Northstar`,
`href="/"`.

| | links | brand markup |
|---|---:|---|
| bespoke composer | 5 | brand **also** emitted as the first nav link |
| template match | 4 | `<h1 class="navbar-brand">` — **no link** |

**Neither is right.** The composer duplicates the brand into the navigation
list; the template drops the destination the source declared, so clicking the
logo no longer goes home, and renders it as an `<h1>` that competes with the
page heading on any interior page.

**So VF-206 stays open, now for a reason rather than out of caution.** Josh's
standing decision was that the composer stays until a portal run confirms
parity. The run happened; it did not confirm parity; and it also showed the
composer is not the correct target to match. Filed as **VF-215**.

Fixing it means giving the navbar template's brand slot an action, which is a
capability change that trips the M4 governance gates and needs a pack version
bump — Josh's call, exactly like VF-214's static-slot question.

**Every remaining item now needs that same decision.** Media (2.250, VF-214) and
the navbar brand (VF-215) are both template-library changes; colour's residual
1.400 is a corpus limitation this fixture cannot exercise. The loop has run out
of work it can complete on its own, which is the stop condition the goal
defines: the top clusters are all blocked.

### 2026-08-06 — Both blockers cleared: pack 1.4.0 and 1.5.0

**Josh authorized the template-library changes.** Suite 2,004 → 2,006. Benchmark
clean, and **the corpus did not move**: top-1 0.9200, top-3 1.0000,
high-confidence precision 0.9091, identical to the pre-change baseline.

**VF-214 — the first fix was wrong, and the corpus said so.** Narrowing the
`media → item.icon` alias took top-1 from 0.9200 to **0.8400** and precision from
0.9091 to **0.8333**, both under their gates. The alias is load-bearing: it is
how media-bearing sections reach icon templates when nothing better scores. It
was reverted rather than argued with.

The slot was the thing to fix. `feature-cards-3up`, `feature-cards-4up`, and
`icon-feature-list` now declare an **optional `item.media`** with a real image
slot. The decorative `item.icon` stays static, because it renders a Vanjaro
vector component that a photograph cannot fill — which is exactly why aliasing
media onto it was wrong in the first place.

On the pilot, the three card images now **reach binding and report their real
reason**: `its asset resolved to no usable source`, the fixture's broken
`/synthetic/*.svg` references. Before, they vanished with no warning anywhere.
The remaining failure is a corpus limitation, correctly attributed.

**VF-215 — the brand keeps its destination.** The navbar templates rendered the
brand as `<h1 class="navbar-brand">` with no link, and the vocabulary could not
represent a destination at all: `brand` allowed `heading`, `text`, and `image`.
It now allows `link`, and both navbar templates render `<a class="navbar-brand">`.

Parity, measured on the same section:

| | before | after |
|---|---|---|
| composer | 5 links: `/ #work #services #about #contact` | unchanged |
| template | 4 links, brand not clickable | **5 links, identical set** |

**The governance system worked exactly as designed and cost two versions.**
Publishing 1.4.0 locked it immutably, so the navbar change could not amend it and
required 1.5.0. Both are published with audited executable digests and locked
history. Three tests pinned `1.3.0` as "the current release" and would have
silently stopped exercising it after any bump; they now derive the version.

The pilot re-scores at **56.89**, coverage 0.6967 / 0.7167 / 0.6967 — a small
drop from 57.21 as the newly-bound media slots register as empty rather than
absent, which is the more accurate reading.

### 2026-08-06 — Every rendered analysis so far measured an unstyled page

**Matcher unchanged** (0.9200 / 1.0000 / 0.9091). Benchmark clean. Suite
2,006 → 2,009.

With media unblocked, the ranking still put it at 2.250 and colour at 1.400 —
both entirely unmeasured. Applying the standing rule, neither side had anything
to sample, so the question became whether that is a code limit or a fixture one.
**Running the pipeline against a real source answered it, and the answer was
worse than either.**

`artifacts/projects/edca-pilot` holds 93KB of real markup from a live DNN site.
Analysed with `--render`:

| | sections | assets with intrinsics | sections with a background |
|---|---:|---:|---:|
| EDCA (real) | 4 | 0 | **0** |

Zero backgrounds on a real site is not plausible, and the cause is not the
adapter. The page declares **13 external stylesheets**, all root-relative
(`/Portals/...`, `/Resources/...`). **A root-relative URL cannot resolve from a
`file://` document** — there is no site root to resolve against — so the browser
painted its own defaults. `getComputedStyle(document.body).fontFamily` came back
`"Times New Roman"`.

**That is the browser default, and it is what this log has been calling a
"fixture artifact" since typography first scored.** The Times-New-Roman heading
mismatch was never a property of the source. It was the signature of CSS that
never loaded, on every rendered analysis this project has run.

**The detection is the address, not the sheet.** A failed `file://` load still
produces a `link.sheet` object, and reading its `cssRules` throws exactly as a
legitimately cross-origin sheet does — neither distinguishes failure. What does
is the href: on a `file:` document, a root-relative stylesheet cannot resolve.
Protocol-relative (`//host/...`) still can, and is excluded.

An unresolved sheet now raises `rendered_stylesheets_unresolved`, naming the
count and saying plainly what it invalidates: *colour, typography and spacing
describe nothing the author chose*. On EDCA that is 10 stylesheets per
breakpoint; on the synthetic fixture, which declares none, it stays silent.

**This does not fix the evidence, and it is not meant to.** Measuring a real
site's design needs the render to reach its stylesheets — a live URL, or a
local copy with its assets. What changes is that an unstyled render can no
longer be presented as design evidence without saying so.

**It also reframes the standing gaps.** Media at 2.250 and colour at 1.400 are
not waiting on code. They are waiting on a source whose CSS loads.

### 2026-08-06 — Serve the saved page instead of rendering it from `file://`

**Matcher unchanged.** Benchmark clean. Suite 2,009 → 2,012.

Last iteration found that a saved page's root-relative stylesheets cannot
resolve from `file://`. The fix is to give them a root: `serve_local_directory`
puts the source directory on loopback for the duration of the render.

Proven end to end on a purpose-built copy, rather than asserted:

| transport | background | body font | warnings |
|---|---|---|---:|
| `file://` | none | browser default | 3 |
| `http://127.0.0.1` | `rgb(171, 205, 239)` | Georgia | **0** |

Loopback only, an ephemeral port, the source directory alone, shut down on exit.
It resolves the page's own references and reaches no network, which is the
property that made rendering a local file safe in the first place.

**Serving silently broke the detector, and that mattered more than the fix.**
The address test — "root-relative on `file:` cannot resolve" — is exactly wrong
once the page is served: the address now resolves, to a 404 for an asset the
saved copy never included. EDCA went from 3 warnings to **0** while its ten
stylesheets still failed, which is worse than before: a false all-clear rather
than a loud problem.

Chromium creates a `link.sheet` object for a 404 too, so that signal fails on
both transports. **The response status is the only thing that distinguishes it**,
and only the capture session can see it. `capture_rendered_observations` now
watches responses and counts stylesheet requests returning 400 or above. EDCA
reports its ten again; the complete copy stays silent.

**EDCA still yields no rendered evidence**, because its assets were never saved
alongside it — the warning now says so instead of the pipeline pretending
otherwise. Media at 2.250 and colour at 1.400 remain waiting on a source whose
assets are present, and that is a corpus question, not a code one.

### 2026-08-06 — Rendered analysis found nothing on any real page

**Matcher unchanged** (0.9200 / 1.0000); boundary precision and recall both
1.0. Benchmark clean. Suite 2,012 → 2,015.

The standing gaps needed a source whose assets load. The local instance serves
one: `keys-to-success`, a fully built and themed site — 46KB, a real stylesheet,
18 images, reachable, and analysing it is a read-only GET.

**It exposed a gap that had nothing to do with assets.** The rendered candidate
query was `main > section, main > article, body > section` — direct children
only. That page has **13 `<section>` elements, no `<main>`, and none directly
under `<body>`**: they are nested in layout divs. Zero candidates. EDCA found 2
of 4 the same way.

**So rendered analysis has produced nothing on every real page it has ever been
run against**, and the synthetic fixture — hand-written with `main > section` —
is the only shape it ever handled. Widened to outermost `section, article` at
any depth: 0 → 13 candidates, with real backgrounds (`rgb(255, 252, 246)`,
`rgb(240, 112, 157)`) and the real theme font, Poppins. The synthetic fixture
still yields the same 5, so nothing regressed.

**A second locator gap, fixed.** `css_selector_for` returned `None` for any
element without an id or `data-id`, so a section the extractor had chosen could
not be pointed at. It now falls back to an `nth-of-type` chain, stable across
the only span it is used for — the static parse and the render happen on the
same HTML. EDCA's first section had no locator and now has one.

**Pairing still fails on that page, and the reason is upstream.** Filed as
**VF-216**: `prepare_static_sections` matches sections to DOM candidates by word
overlap, and on a Vanjaro-built page **none of the 11 sections match any
candidate** — no `_static_selector`, no `_static_html`, no `_static_role`. With
no locator, identity pairing has nothing to key on; counts differ, so position
pairing is correctly refused. EDCA matches 5 of 5, so this is specific to how a
Vanjaro page nests content.

**One test changed its answer honestly.** The position-pairing test supplied
three rendered sections; the fixture now yields four, because the nav is
extracted as a section too and equal length is the precondition for position
pairing. Updated to four rather than relaxed.

### 2026-08-06 — VF-216: rendered analysis works on a real site, end to end

**Matcher unchanged** (0.9200 / 1.0000). Boundary precision and recall both 1.0,
visitor content retention 1.0. Benchmark clean. Suite 2,015 → 2,018.

On the live `keys-to-success` site:

| | before | after |
|---|---:|---:|
| sections with rendered provenance | 0 / 11 | **11 / 11** |
| sections with measured bounds | 0 / 11 | **11 / 11** |
| style properties per section | 0–2 | **32** |
| warnings | 3 unmatched | **0** |

Real backgrounds, and the site's real theme font throughout: Poppins, not the
browser default this project has been measuring since typography first scored.

**The cause was the same blind spot, in the other extractor.**
`static_boundary_candidates` selected
`main > section, main > article, body > section` — the identical direct-child
query the rendered script had. On a Vanjaro-built page it returned **zero**
candidates while the content extractor found eleven sections, so
`prepare_static_sections` had nothing to match against, no section recorded a
selector, and pairing had no key. Widened the same way: outermost `section,
article` at any depth. Thirteen candidates, eleven sections matched, every one
carrying its real id.

**Two extractors that disagree about where sections live cannot pair**, however
good either is alone. A test now asserts both query the same shape, so they
cannot drift apart again silently.

**The builder-specific selectors stay.** Elementor containers and DNN panes are
still matched explicitly; the widened rule is additive, which is why boundary
precision and recall hold at 1.0.

**What this changes about everything measured so far.** Every rendered figure in
this log came from the one hand-written fixture, because that was the only page
shape either extractor could see. The pipeline can now measure a real site, and
the colour, typography and media evidence that has been unavailable throughout
is present on one for the first time.

### 2026-08-06 — A real page's body copy was never extracted

**Matcher unchanged** (0.9200 / 1.0000). Boundary precision, recall and visitor
content retention all 1.0. Benchmark clean. Suite 2,018 → 2,021.

With rendered analysis working on a real site, the next step was to score one
end to end. Planning blocked immediately: nine of eleven sections
`unresolved blocking match or simplification`, each for a required `title` or
`body`.

**The page has 51 `div.vj-text` blocks and 2 `<p>` elements.** Extraction asks
for `<p>` in half a dozen places, so it found almost nothing — sections came
back with empty content and every match blocked on a field the section plainly
had. This is the third time the same shape has appeared: the build renders body
copy as a div, and code that looks for a tag rather than a shape misses it.

A single normalization now rewrites a text-bearing `div` leaf to `<p>` before
extraction, which is safer than teaching six call sites a second spelling. Only
a `div` with text and no element children qualifies — a wrapper around other
elements is structure, not a paragraph, and is left alone.

Sections that extracted nothing now extract their content: one previously-empty
section returns four headings and four paragraphs.

**It does not unblock planning, and the honest reading is that it was never
going to alone.** `editable_content_coverage` on the real site is **0.074**, and
the same nine sections still block. The content is extracted and is not reaching
the fields that require it, so the gap is between extraction and binding —
roles, or repeat-group relationships, not surviving this markup. Filed as
**VF-217** with the per-section evidence.

The corpus is unmoved by the change, which is the check that matters: retention,
boundary precision and recall all stay at 1.0.

### Iteration 29 — VF-217, binding on a real site

**Result:** `editable_content_coverage` on `keys-to-success` 0.074 → **0.3977**.
Blocking sections 9 → 5. Corpus unchanged on every metric: boundary precision
and recall 1.0, visitor content retention 1.0 (127/127), group-field
association 1.0 (79/79), top-1 0.92, high-confidence precision 0.909. Suite
2,021 → 2,029.

Two causes, both the shape this loop keeps meeting — code that names a *tag or
a class* where it means a *kind of thing*.

**Repeat items were discovered by vocabulary.** `find_all("article")` then
`.card, .e-loop-item, .service-list > *`. A Vanjaro page emits Bootstrap
columns and has none of those, so a four-card section produced no groups, and
every `item.*` field went unbound. Its images and links fell through to the
generic `section_media` and `primary_action` loops, which is exactly the
signature the evidence showed: four media, four actions, one title, no groups.

`repeating_subtrees` now finds cards by the repetition itself — the outermost
set of like-signatured elements that each hold a heading or an image. Grouping
by signature rather than by parent is load-bearing: the four cards were split
across two `.row` containers, and a single-parent scan would have found two
groups of two. It runs only when vocabulary discovery finds nothing, so the
corpus path is untouched.

**Iteration 28's normalization never reached this pass.** It was applied inside
`extract_sections`, but `enrich_section_from_static_dom` parses the source
subtree captured by `static_boundary_candidates` — raw page HTML that has been
through no normalization at all. That is why the previous fix moved nothing.
The helper is now public and called on both soups. Eight sections that reported
no body copy now report it.

Sections 5, 6, 7 and 8 bind their cards; four-item groups carry title, media
and body.

**The five sections still blocking are not binding failures**, and the earlier
task file was wrong to group them. Section 1 is the site header — one image and
eight links — classified `call_to_action` instead of `navigation`. Section 2 is
a hero whose heading is not a heading element. Both are role and heading
recognition, upstream of binding. Filed as VF-218 and VF-219; VF-217 stays open
for the coverage gap that remains against the corpus.

**Known imprecision, not hidden:** card body picks the first paragraph, which
on this page is a short pill tag rather than the description below it. Coverage
counts it; a reader would not. Recorded in VF-217.

### Iteration 30 — VF-218, the site header stops being a call to action

**Result:** `editable_content_coverage` on `keys-to-success` 0.3977 → **0.4430**.
Blocking sections 5 → **4**. Design warnings 0. Corpus unchanged on every
metric: boundary precision and recall 1.0, semantic role accuracy 1.0, visitor
content retention 1.0 (127/127), group-field association 1.0 (79/79), top-1
0.92, high-confidence precision 0.909. Suite 2,029 → 2,036.

`static_role` recognised navigation only by `<header>`, `<nav>`, or a
descendant `<nav>`. A Vanjaro page puts its whole site header in a plain
`<section>`, so the header was classified as a call to action and matched
`CTAs/cta-banner`, which wants a title the header does not have and owns one
action slot for its eight links.

`_is_link_bar` adds the structural reading: **no heading, three or more links,
and at least eighty per cent of the section's text inside those links.** The two
things a link bar is most likely to be confused with both fail it — a footer
carries headings and a copyright line, a call to action carries the prose that
makes the call. On the real page the header measures 85 of 92 characters inside
links; the footer measures 123 of 432.

**A stale reading nearly became a false report.** The first measurement after
the change showed no movement at all. The analyze stage had *resumed* — the
input fingerprint covers the source, not the code, so a code-only change
reproduces the cached artifact by design. `--refresh --render` is required to
measure a code change against a real site, and every real-site figure in this
log from here on is taken that way.

**Fixing the classifier exposed a mispairing it had been hiding.** Navigation
candidates were withheld from matching, but the extractor still emits the
header as an ordinary section — so that section matched whatever subtree was
left, and the header came to wear the *footer's* DOM. The footer then landed at
position 2 and the last real section had no rendered match at all.

Candidates are no longer withheld. A section whose best match is a navigation
candidate *becomes* the navigation section, and only unclaimed chrome is
prepended, so the header is recorded once and nothing is displaced. Section
roles are also keyed on document order now rather than on position within the
shrinking pool — `section_index` means "how far down the page", and the
pool-relative index drifted as earlier candidates were claimed.

The page now reads as it looks: navigation with eight items, footer last,
no unmatched sections.

### Iteration 31 — VF-219, a heading that is not a heading element

**Result:** `editable_content_coverage` on `keys-to-success` 0.4430 → **0.4444**.
Blocking sections 4 → **3**. Warnings 0. Corpus unchanged on every metric:
boundary precision and recall 1.0, semantic role accuracy 1.0, visitor content
retention 1.0 (127/127), group-field association 1.0 (79/79), top-1 0.92,
high-confidence precision 0.909. Suite 2,036 → 2,042.

The hero carried `MUSIC FOR EVERYONE` in a `div` of two spans. It is not a
heading element and it is not a text leaf either, so neither the heading query
nor iteration 28's normalization saw it: the section reported one body element,
no title, and blocked on `Heroes/centered-hero`'s required field.

`implied_title` promotes **the first text-bearing block in the section, when it
is under eighty characters and more text follows.** The rule is positional
rather than a guess at class names — naming `.hero-title` or `.vj-heading`
would be the same mistake this loop keeps correcting. A section that is one
block has no title to promote, and a long first block is prose. Nothing is
promoted when a heading element exists.

The promotion is recorded as `implied: true` on the element rather than passed
off as an observation, and the promoted block is excluded from the body-copy
sweep so it is not counted twice.

**Two narrower fixes came out of the same read.** The heading query stopped at
`h3`, so a section titled with an `h4` had no title at all; it now runs to
`h6` and records the real level. And the phrasing-tag set used to keep card
discovery off leaf nodes was reused here at first, which excluded `<p>` —
a paragraph is not a card but it is certainly a text block. The two sets are
now separate, with the reason written next to them.

The page reads correctly end to end: navigation, hero with its title, four card
sections, footer. Three sections still block, all `call_to_action` and
`contact` variants at the foot of the page.

### Iteration 32 — VF-220, and a finding that stops the run

**Result:** blocking sections **3, unchanged**. Coverage 0.4444, unchanged.
Corpus unchanged on every metric: boundary precision and recall 1.0, semantic
role accuracy 1.0, visitor content retention 1.0 (127/127), group-field
association 1.0 (79/79), top-1 0.92, high-confidence precision 0.909. Suite
2,042 → 2,045.

**VF-220 is not a matcher bug, and the task as I wrote it was wrong.** Its
acceptance criteria said matching should "prefer a template that can hold
them". It cannot: **every template in the library owns exactly one `action`
slot and one `body` slot.** `contact-section` owns three `contact_items` and is
the widest thing available. A footer with ten links has nothing to match.

| section | wants | widest template |
|---|---|---|
| 9 | 2 body | 1 |
| 10 | 2 background media | 1 |
| 11 | 10 actions, 2 body | 1 action, 3 contact items |

The scoring change is still right and landed. Field *presence* was the whole of
the field score, so a template owning one action slot scored exactly as well as
one owning four against a section with ten actions — and the plan then failed
at binding, after the choice had been made. `_capacity_fit` now folds the ratio
of slots to values into the field score and reports the shortfall as
`action needs 10 slots, template owns 1`.

Section 11's score fell from 0.889 to 0.819 and its overflow is now legible
before binding rather than after. Nothing unblocked, because there is nothing
to unblock it with.

A manifest with no `physical_fields` is schema 1.0 and takes no penalty —
absent is not zero. That distinction has now caused three bugs in this project
and is worth stating every time it comes up.

**Halting here rather than continuing.** Closing this gap means adding
templates to the shared library — a link-list or footer template that owns many
actions, and wider body slots — which is a pack version bump and a change to
the governed agency library. Josh authorized that class of change once, for
VF-214 and VF-215 specifically. I am not extending that authorization to a new
template family on my own reading. Filed as VF-221 with the measured
requirement.

### Iteration 33 — a stats band read as a card grid

**Result:** blocking sections **3, unchanged**. Coverage **0.4444, unchanged**.
Corpus unchanged on every metric: boundary precision and recall 1.0, semantic
role accuracy 1.0, visitor content retention 1.0 (127/127), group-field
association 1.0 (79/79), top-1 0.92, high-confidence precision 0.909. Suite
2,045 → 2,049.

**Neither headline number moved, and the section is nonetheless right now.**
Section 6 of the real page is a stats band — `10 Professional Instructors`,
`∞ Happy Students`, `80+ Combined Years of Experience`. It was classified
`feature_cards`, which bound `10` as the section title and left the three
labels as loose body copy. It now reports a three-item `stat` group with
values and labels in the right places. Coverage counts fields, not whether they
are the right fields, so it cannot see the difference. The section can.

Two vocabulary tests were behind it, the seventh and eighth instances in this
log. `_looks_like_stats` scanned direct children only, and the band nests under
a container and a row. And a stat value had to match a digits pattern, so the
infinity sign did not count — what makes a stat a stat is a short token
carrying no letters, not that it is a numeral.

**Classifying it correctly made things briefly worse, which is the useful part
of this iteration.** With the band reading `stats`, ownership ran the stats
path — `find_all("li")` filtered by `find("strong")` — and a Vanjaro band has
neither. Coverage fell 0.4444 → 0.4304 and the numbers were lost. A fix to
classification that its downstream path cannot honour is not a fix.

`_stat_parts` now splits a block by shape: the value is the leaf that reads as
a value, the label is the next leaf that is not it. That covers both the
`<li><strong>` shape the corpus uses and the heading-plus-div shape the real
page uses.

**Two corpus regressions caught and fixed before commit**, both from the same
mistake — assuming the new shape was the only shape. Requiring a stat-shaped
value dropped `<li><strong>Since 1998</strong>` items whose value does not read
like a number (retention 0.76, then 0.96). A block that has already been judged
a stat keeps its first leaf as the value. The structural fallback is separately
gated on a block genuinely carrying a value, so a group of service cards is not
claimed as stats.

### Iteration 34 — no code change; responsive coverage has a fixture ceiling

**Result:** no commit to source. Corpus unchanged. Suite 2,049, unchanged.

I went looking for unblocked work with corpus-visible value and took
`responsive_observation_coverage`, which the problem statement at the top of
this document still lists as one of the four headline gaps at 0.8864 (39/44).

**The five outstanding failures cannot be extracted, because the evidence is
not in the sources.**

| case | expected at mobile | present in source |
|---|---|---|
| bootstrap-agency | `min_height: 520px` | nothing |
| bootstrap-agency | `background_position: 65% 50%` | nothing |
| bootstrap-agency | `carousel: true` | nothing |
| elementor-studio | `min_height: 600px` | nothing |
| elementor-studio | `carousel: true` | nothing |

`html-bootstrap-agency/source.html` is 24 lines and contains **no CSS at all** —
no `<style>` element, no linked sheet, no `@media` rule, and no `min-height`,
`background-position`, or carousel markup anywhere. The elementor source has
none of those tokens either. The annotations describe a rendering the source
does not declare.

Passing these would require inventing the values or editing the annotations.
Both are prohibited, and the prohibition is the right one: a metric that can
only be moved by fabrication is not measuring extraction.

**So 0.8864 is a ceiling, not a deficit.** 39 of 44 is every responsive
observation these fixtures can support. This is recorded so the next iteration
does not spend itself rediscovering it, and so the gap table at the top of this
document is not read as an open work item. Closing the remaining 5 needs
fixtures that declare what they expect — a fixture change, not an extraction
change, and one that changes the denominator for every historical score.

**Stopping the loop here.** VF-221 is gated on Josh. VF-008 needs the six
benchmark portals, which are not authorized. VF-206 needs a portal parity run.
What remains is either gated, or work invented to keep the loop moving, and the
loop is worth less than an honest stop.

### Iteration 35 — VF-221 authorized, and it turned out not to be needed

**Result:** blocking sections **3 → 1**. Coverage **0.4444 → 0.5672**. Warnings 0.
Corpus unchanged on every metric: boundary precision and recall 1.0, semantic
role accuracy 1.0, visitor content retention 1.0 (127/127), group-field
association 1.0 (79/79), top-1 0.92, high-confidence precision 0.909. Suite
2,049 → 2,059. **No template was added, and no template's contract changed.**

VF-221 said the library had nothing that could hold a footer's ten links. It
was wrong, and the error was mine: I checked three CTA and contact templates
and generalised from them. **`Navigation/footer-4col` already exists** — brand
column, two `navigation_column` items owning six links each, and a contact
block. It is an exact structural match for the real footer.

The footer never reached it because it was never a footer. `<footer>` is
excluded from boundary discovery, so the only footers that path ever sees are
the ones a builder wrapped in a plain `<section>` — and nothing recognised
those. The header got this treatment in VF-218; the footer did not.

Recognition is now symmetric, and the footer routes to global chrome exactly as
the header does: `global_section_count` is 2 and the body is 9 sections rather
than 11. A footer labels its columns and labels are small, so a section heading
of `h1`–`h3` disqualifies; position is required too, within the last two
candidates behind a possible copyright bar. **A test I wrote caught the first
version claiming a mid-page services grid** — it scanned backwards from the end
without requiring the match to be near it.

**Two more misreadings fell out, both one line.** `#tpl-ctas-s1` was a call to
action because `"cta" in hints` is a substring test and `"ctas"` contains
`"cta"` — the section has a heading, an image and two paragraphs and no link at
all. Hints are matched as whole words now. And a media block whose thumbnail is
wrapped in a link satisfied "one action, one heading, short text"; an action
with no label is not the call.

**A deck is not body copy.** `JOIN US AT KEYS TO SUCCESS MUSIC STUDIO` over
`and give your child the gift of music.` was two body values against templates
that own one. The first line finishes the headline. It binds to `subtitle` now,
which `Content/split-media` has had all along. The rule is narrow — the deck
must directly follow the title, be short, and have real copy after it — and it
was found by looking for one section's fix, which is worth saying plainly.

**The last blocker is not capacity either.** Section 9 needs a required `media`
field and every asset in the workspace has `local_path: null`, so the remote URL
correctly refuses to bind rather than leaking into a build. That is asset
acquisition, not the library. Filed as VF-223.

### Iteration 36 — VF-223, and the first valid plan on a real site

**Result:** blocking sections **1 → 0**. Coverage **0.5672 → 0.8060**.
`valid: true` — **the first valid plan this project has produced from a live
page.** All 17 assets acquired, 0 warnings. Corpus unchanged on every metric:
boundary precision and recall 1.0, semantic role accuracy 1.0, visitor content
retention 1.0 (127/127), group-field association 1.0 (79/79), top-1 0.92,
high-confidence precision 0.909. Suite 2,059 → 2,067.

A live page analysed with `local_path` unset on **every** asset. Nothing
downloaded them: the legacy crawl path builds an asset manifest, and the Figma
path has `acquire_figma_image_fills`, but a `live_html` source had no
equivalent. So every image stayed an absolute remote URL, and the planner
blanked each one rather than hotlink another origin — correct, and invisible.

`acquire_html_assets` fills that gap, built on the existing
`migration.assets.download_assets` rather than a second downloader. It writes
`sources/<id>/assets/` and an `asset-manifest.json` with digests, mirroring the
Figma module. Only absolute http(s) sources are fetched — a relative path
already loads in a portal page, and downloading it would mean fetching the site
being built.

**Coverage rose far more than the one blocking section explains.** Media fields
across the page were dropping silently: optional ones simply bound nothing and
said nothing. One section blocked because its template *required* media, which
is the only reason this was visible at all.

**The plan also reported the wrong cause**, which is the part worth keeping in
mind. `required field 'media' is missing or has no slot` was printed for a
section that had the element and lacked only its bytes. `_unmet_reason` now
separates the three cases: no candidate at all, a candidate whose asset was
never acquired, and a candidate that could not bind for another reason. A wrong
diagnosis sends a reader looking for absent content.

A failed download is recorded twice — as `missing_reason` on the asset and as a
document warning — and never as a silent drop.

**Where the real page stands:** 11 sections, header and footer as global chrome,
9 body sections all matched and bound, `editable_content_coverage` 0.8060, zero
blocking issues, zero warnings, and a valid plan.

### Iteration 37 — the over-fit check VF-4 asks for, run at last

**Result:** corpus unchanged on every metric: boundary precision and recall 1.0,
semantic role accuracy 1.0, visitor content retention 1.0 (127/127),
group-field association 1.0 (79/79), top-1 0.92, high-confidence precision
0.909. Suite 2,067 → 2,073. `kts-fidelity` holds at coverage 0.8060, 0 blocking,
valid.

`kts-fidelity` cannot advance: its next stage needs the `portal_mutation`
approval, which is a human gate, and its source portal is not the pilot. So the
useful move was the one VF-4 has demanded since this document was written and
that nine iterations of fixes never got — **a second real site**.

**`edca-pilot`: coverage 0.10, 2 of 4 sections blocking, plan invalid.**
Against `keys-to-success` at 0.8060 and valid. That gap is the honest state of
this pipeline: strong on the page it was tuned against, weak on the next one.

**Nothing regressed there, which is the part that matters.** Section 1 went from
`hero` carrying a lone image to `navigation` with eleven items — the VF-218
link-bar rule generalises to a second builder untouched. Every other section
held or improved. The changes are not over-fitted; they are simply incomplete.

Two general defects came out of running it.

**A text-free image band was rich text.** `#dnn_BannerPane` holds one image and
no words at all, and the role fallback gave it `Content/rich-text`, whose body
is required — a section with no text can never satisfy that. It reads
`photo_band` now and matches `Heroes/photo-band`, which requires only
`background_media`. A photo band's picture is the band rather than an
illustration beside one, so it owns `background_media` rather than
`section_media`; only that role reaches the full-bleed slot.

**`--json` was not machine-readable.** `SimpleHTTPRequestHandler` logs every
request to stderr, so a saved page missing ten stylesheets emitted thirty lines
into the middle of the JSON. I hit this while parsing my own output. The
loopback handler is silent now.

**And a defect in iteration 36's own work.** The crawl downloader avoids
collisions by appending a number — right for a crawl, wrong for a workspace:
re-analysing wrote `hero-1.png` beside `hero.png` and kept two copies of every
image, seventeen becoming thirty-four. Workspace assets are named by a digest
of their source URL now, so a re-run overwrites in place, and a previous
acquisition's recorded files are removed first. Only paths the manifest
recorded are ever deleted, which a test pins.

**Section 3 now blocks for the right reason**, and says so: `required field
'background_media' has 1 value(s) whose asset was never acquired`. That is
iteration 36's `_unmet_reason` doing its job on a site it was not written for.
The saved copy's images are relative and were never saved beside it, so
`acquire_html_assets` correctly leaves them alone.

**Next on edca:** a saved page's relative images have to exist in the workspace
or be fetched from the origin, and a `biography` section with three bodies and
three media has no template that fits. Filed as VF-224.

### Iteration 38 — VF-224, and edca's source turns out to be incomplete

**Both real sites, before → after:**

| site | coverage | blocking | valid |
|---|---|---|---|
| `edca-pilot` | 0.10 → **0.125** | 2 → 2 | false |
| `kts-fidelity` | 0.8060 → 0.8060 | 0 → 0 | true |

Corpus unchanged on every metric: boundary precision and recall 1.0, semantic
role accuracy 1.0, visitor content retention 1.0 (127/127), group-field
association 1.0 (79/79), top-1 0.92, high-confidence precision 0.909. Suite
2,073 → 2,077.

**A layout pane was counted as a section.** `#dnn_content` wraps `#dnn_TopPane`,
`#dnn_Full_Screen_PaneB` and `#dnn_BottomPane`, and all four were boundaries.
The sectioning rule keeps only the outermost `<section>`; the builder rules
below it had no such filter, so every word inside the wrapper was counted twice
and one boundary held the same content as three others. That is why section 2
reported three media where the page has one.

Outermost is the wrong tie-break for a pane — the wrapper is layout and the
panes are the sections — so the test is **contribution**: a candidate stays if
it carries any text or media of its own, and is dropped only when the nested
candidates account for all of it. The corpus never showed this because it has no
nested candidates at all.

**Then the remaining gap stopped being an extraction problem.**
`artifacts/projects/edca-pilot/sources/` contains **one file: the HTML.** No
images, no stylesheets. The saved copy's URLs are root-relative, so they joined
against the file URI and became `file:///Portals/0/...` — the drive root, where
nothing exists. Both remaining blockers are assets that were never saved:

- `section.3` needs `background_media`; the plan says the asset was never
  acquired, which is exactly right.
- `section.2` needs media and three body slots; `Content/bio-about` owns one of
  each.

The ten unresolved stylesheets and the three sections with no rendered match
have the same single cause.

**No extraction change can recover an image that was never saved**, and I am not
going to guess the origin it came from — a wrong guess binds someone else's
pictures into a build. The mechanism to fix it already exists and needs no code:
a source that records `metadata.source_url` resolves its relative URLs against
that origin, and `acquire_html_assets` then fetches them exactly as it does for
`keys-to-success`. That is a workspace configuration and a question for Josh.

**Reading the catalogue first, as VF-221 taught:** `Content/rich-text` is the
only template owning more than one body slot (four), and it has no media field.
So a three-paragraph about-section with a picture genuinely has nothing that
fits. That is a real capacity gap — the first one this loop has found that
survives actually checking — but it is worth nothing until edca has its images.

### Iteration 39 — a valid plan that silently drops eleven pieces of content

**Both real sites:**

| site | coverage | blocking | valid | content losses |
|---|---|---|---|---|
| `edca-pilot` | 0.125 | 2 | false | 0 |
| `kts-fidelity` | 0.8060 | 0 | true | **11** |

Corpus unchanged on every metric: boundary precision and recall 1.0, semantic
role accuracy 1.0, visitor content retention 1.0 (127/127), group-field
association 1.0 (79/79), top-1 0.92, high-confidence precision 0.909. Suite
2,077 → 2,080.

`kts-fidelity` reports `valid: true` and `issue_count: 0`. It will also drop:

| section | template | lost |
|---|---|---|
| 3, 10 | Rich Text Block | its image and its button |
| 5, 7 | Feature Cards (4-up) | its heading and its body copy |
| 8 | Feature Cards (4-up) | its heading, body, and button |

`MOST POPULAR CLASSES` would not reach the built page. The evidence existed —
one warning per field, inside the composition plan's per-entry list — but
nothing a reader looks at said so. `editable_content_coverage` of 0.8060
encoded it as a number with no names attached.

`content_losses` and `content_loss_count` now sit in `validation.json` beside
`valid`, naming the section and the fields. Not blocking: a template that fits
imperfectly is still buildable, and forcing a block would stop plans that are
fine. Visible, though, which is the whole of VF-214's lesson applied to a
different quiet loss.

**Measuring the change required a second fix.** `project plan` had no
`--refresh`, and its fingerprint covers the analysis and the policy — not the
planner. So a change to planning reproduced the cached result exactly, and my
first reading of the new field was of a file written before it existed. That is
the same resume trap as iteration 30, on a stage that had no way out of it at
all. `--refresh` exists on `plan` now, matching `analyze`.

**The cause is a template gap, and it is not mine to close.** No card template
declares a `section_title` field — neither `feature-cards-3up` nor `-4up` has
one, so *every card section on every site* loses its heading. `Content/rich-text`
declares `title` and `body` and nothing else, so an image or a button in a
rich-text section has nowhere to go. Both are governed library changes. Filed as
VF-226 with the measurement attached.

### Iteration 40 — a picture beside its copy was a one-column stack

**Both real sites:**

| site | coverage | blocking | valid | content losses |
|---|---|---|---|---|
| `edca-pilot` | 0.125 → 0.125 | 2 | false | 0 |
| `kts-fidelity` | 0.8060 → **0.8358** | 0 | true | 11 → **9** |

Corpus unchanged on every metric: boundary precision and recall 1.0, semantic
role accuracy 1.0, visitor content retention 1.0 (127/127), group-field
association 1.0 (79/79), top-1 0.92, high-confidence precision 0.909. Suite
2,080 → 2,085.

Iteration 39 named eleven pieces of content a valid plan would drop and put the
cause in the library, where I could not go. Two of them were not a library
problem at all.

`#tpl-split-s1` lays a picture beside its copy — a row with an image column and
a text column. The layout was recorded as `kind: stack, columns: 1`, so the
section read `rich_text` and matched a template that has no media field and no
action. Its image and its button were going to be dropped by a plan that
reported no issues.

`media_text_split` reads the shape: a container whose element children are
exactly two blocks, one carrying the pictures and one carrying the words. The
role is `split_media` and `Content/split-media` holds all four fields, so
nothing is lost.

**My first version claimed a four-card grid and a stacked media feature**, and
the tests I wrote for those two cases are the reason I noticed. A card grid's
inner row is two columns with a picture in one of them; a media feature carries
a mascot and a thumbnail. Both are excluded now by the same sentence that
describes what a split actually is — **one picture beside one block of copy** —
plus a check that the two columns account for the section's content rather than
one band inside it.

Which side the picture sits on is recorded from source order. A mirrored build
reads as a different design, and `media_position` was hard-coded to `left`.

**The remaining nine losses are the library gap**, and VF-226 still needs Josh:
no card template declares a `section_title`, and `Content/rich-text` declares
only `title` and `body`. Section 10 is a stacked media feature with two
pictures — correctly not a split — and loses its image and action to that same
gap.
