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
