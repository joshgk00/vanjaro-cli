# Freeform Figma matching review

Status: geometry and matching corrections passed focused offline review; full integration and live fidelity remain pending.

## 2026-09-22 integration checkpoint

Ringer run `vanjaro-agency-translation-retention-20260922T054113Z-p89790`
finished with both tasks PASS on attempt 1 (authoritative checks exit 0).
Root independently ran the eight matching acceptance cases together with
maintained geometry, matcher-layout, Figma adapter/section and matcher benchmark
tests: **57 passed in 0.56s**. This proves the checked extraction and ranking
contracts, not real-client visual fidelity or a clean full suite.

Two next lanes have distinct ownership and verified failing baselines:

- `agency-benchmark-gate-test-hardening.json`: replace the CLI rejection test's
  accidental dependence on corpus accuracy remaining below 0.99 with controlled
  degraded predictions evaluated by the real metrics/reporting path.
- `agency-figma-text-role-fix.json`: preserve explicit headline/body ownership
  when font metadata is absent or tied, including shuffled source layers.

The second lane started only after the geometry worker released the adapter.
Neither lane is accepted yet. Re-run the full suite and write a new benchmark
snapshot after both finish. Preserve the historical diagnostic unchanged.
The geometry worker's notes attribute unrelated line-ending changes to the
Windows interpreter; this causal claim has not been independently established
and is not accepted as evidence of file preservation.

### Follow-up review

The benchmark-test lane is now terminal PASS on attempt 1 in run
`vanjaro-agency-translation-retention-20260922T060235Z-p102192`; root independently
re-ran its CLI, matcher benchmark and fresh-process import tests: **15 passed
in 6.36s**. One incorrect selected-template ID is injected at the prediction
loader boundary. The real evaluator computes 24/25, rejects the 0.99 threshold,
and writes both reports. An unchanged-prediction control passes the same gate.
Production thresholds and evaluator code are unchanged.

Text-role work remains active. Root acceptance now checks the actual planner
title/body bindings and covers partial font metadata as well as wholly absent
fonts, both with original and shuffled source order. The in-progress helper
passes the two absent-font cases but fails the two paragraph-font-only cases:
an observed 16px body size incorrectly outranks an unobserved headline size.
Unknown font size must not be interpreted as an observed zero-size font.
These four cases are part of the worker's existing authoritative check path.

Interim root regression run (`pytest tests -m 'not integration' -q
-p no:cacheprovider`) completed **3012 passed, 2 skipped, 16 deselected in
51.93s**, exit 0. This run excludes root-owned `artifacts/test_*.py` acceptance
and occurred while the text-role worker was active. In particular, the two
partial-font failures above are not disproved by this green result. Final
acceptance still requires a stable-tree combined run including those cases.

Subsequent in-progress review: the worker now compares font sizes only when
all title candidates report size metadata. Root re-ran four text-role/binding
cases plus eight geometry/matching cases: **12 passed in 0.73s**. The worker
remains live; its maintained tests, final code review and stable combined suite
are still pending. This is focused evidence, not terminal acceptance.

Read-only follow-up on the five responsive benchmark misses found absent input
evidence rather than proof of discarded observations. See
`agency-responsive-benchmark-evidence-review.md`; do not fix those scores by
inventing source values or changing thresholds.

## Stable integration acceptance

Text-role run `vanjaro-agency-translation-retention-20260922T060351Z-p103228`
finished PASS on attempt 1, authoritative exit 0: four independent text-role
checks and 61 maintained/geometry checks. Root read the harvested notes and
helper/tests, then independently re-ran the same focused scope: **65 passed
in 0.58s**.

After all implementation workers were terminal, root ran `pytest tests` plus
the explicit independent feature-card release, card-action, image-link,
article-semantics, capture summary/collection/CLI/reference/session/shape,
Figma matching and Figma text-role acceptance files, with
`-m 'not integration' -q -p no:cacheprovider`:
**3137 passed, 2 skipped, 16 deselected in 53.40s**, exit 0.

The geometry, scoring, text-role and benchmark-test changes are accepted for
this offline integration scope. This does not establish live portal quality,
three-source representative project results or measured operator time savings.
The text helper remains 94 lines; adapter integration is one import and one
selection call. Existing subtitle/eyebrow assignment without font evidence
still falls back to body and is not claimed fixed by the headline correction.

New benchmark run `artifacts/agency-figma-integrated-benchmark.json` is active,
writing `artifacts/benchmarks/agency-figma-integrated-20260922`. Preserve the
earlier snapshot; read and compare final reports before claiming a score gain.

### Benchmark review reopened mobile-overlap integration

The new report improves top1 from 23/25 to 25/25 and high-confidence precision
from 18/19 to 19/19, but responsive coverage declines from 39/44 to 38/44.
New missing observation: `riverkind.hero` mobile `overlap=false`.
`_infer_mobile` emits overlap removal only for `LayoutKind.FREEFORM`; the
geometry correction now classifies this modestly overlapping hero as SPLIT
and stores `text_overlaps_media`, bypassing that branch. Focused and full
tests did not cover this cross-stage contract. This reopens integration
acceptance for mobile-overlap behavior despite all prior checks passing.
Preserve the new snapshot as regression evidence and correct the inference
contract without declaring mobile layout observed or changing annotations.

Root added two original/mirrored adapter acceptance cases requiring inferred
mobile `overlap={from: true, to: false}`. Both failed with missing `overlap`,
confirming the branch diagnosis. After the benchmark worker finished exit 0
(its green threshold status does not erase this regression), dispatched
`artifacts/agency-figma-mobile-overlap-fix.json` with a verified failing baseline.
This worker owns only mobile inference in the adapter and a new maintained test
file. The completed benchmark snapshot remains unchanged as regression evidence.

In-progress overlap correction now carries explicit `text_overlaps_media`
metadata from geometry-inferred SPLIT sections into the mobile flattening
inference. Root independently re-ran all matching and text-role acceptance:
**14 passed in 0.73s**, including both original and mirrored overlapping heroes.
The worker remains live; maintained observed-mobile precedence tests, final
review, stable full suite and a separate post-fix benchmark remain required.

### Mobile correction stable test result

Run `vanjaro-agency-translation-retention-20260922T061657Z-p112308`
finished PASS on attempt 2, authoritative exit 0 (14 independent and 58
maintained checks). Root inspected the retry log: the first attempt omitted
the required notes.md; the retry supplied notes and reverified the existing
implementation. No code-check failure was the reason for this retry.

Root reviewed all five maintained mobile tests and independently ran them with
the matching/text acceptance: **19 passed in 0.40s**. After the worker was
terminal, the full combined suite previously listed here passed **3144 tests,
2 skipped, 16 deselected in 55.51s**, exit 0.

Post-fix measurement is active under `agency-mobile-overlap-benchmark.json`,
writing a separate `agency-mobile-overlap-fixed-20260922` snapshot. Benchmark
recovery is not yet accepted merely from the test result.

### Benchmark recovery verified

The post-fix benchmark worker is terminal PASS, exit 0. Root compared the
actual JSON metrics to the pre-change snapshot: the only changed aggregate
metrics are top1 **23/25 -> 25/25** and high-confidence precision
**18/19 -> 19/19**. Responsive coverage is restored to **39/44**, with exactly
the original five HTML source-evidence misses. The assisted-image report is
text-identical to the original report. Boundary, content, repeat-field and
asset-association measurements are unchanged.

This closes the mobile-overlap regression for the tested offline integration
scope. The stable **3144-pass** combined suite and post-fix benchmark support
that conclusion together; neither establishes live-site fidelity or agency
time savings. Current measurement artifact:
`artifacts/benchmarks/agency-mobile-overlap-fixed-20260922/combined.md`.

## Verified diagnostic and implementation baseline

The diagnostic process finished exit0 and root replay passed for both sections.
Layout contributes +0.062917 toward Centered Hero over Split Hero despite
fields/maintainability favoring Split Hero; correcting only the copied layout
flips the ranking. For stats, layout contributes +0.028846 toward4up while
repeat fit favors3up by0.006. Even a counterfactual measured3-column GRID still
favors4up, exposing a spatial-versus-presentation compatibility problem beyond
missing source geometry. Counterfactual layouts are experiments, not source
observations or accepted fixes.

Root's new independent acceptance has four verified baseline failures: right
and mirrored-left hero layout, and three stats with missing or measured layout.
`artifacts/agency-figma-match-fixes.json` starts two disjoint workers: a Figma
geometry helper/integration and a source-neutral matcher scoring correction.
Both authoritative baseline checks failed for the intended requirements.
No acceptance thresholds, fixture annotations, or published templates may change.

During implementation, the initial matcher patch passed the two original stats
cases but retained unsupported FREEFORM preferences across other spatial labels.
Root added two same-evidence/different-capability-label checks for FREEFORM and
OTHER; FREEFORM fails (four different layout scores with no observed geometry).
These are the original neutral-missing-evidence requirement, not permission to
change only the benchmark's grid-versus-band ranking. The active worker's
authoritative stats check includes them; no production acceptance is claimed.

The scoring worker subsequently removed the unsupported FREEFORM kind
preferences. Root reproduced all four independent stats checks passing, then
six maintained matcher/layout and benchmark tests passing. This is interim
focused evidence only: the worker is still running broader checks, and the
geometry negatives and queued headline-role defect remain unresolved.

The initial geometry helper passes original/mirrored side-media cases but root
reproduced two false positives: an image under an invisible ancestor is still
used, and media moved entirely below the text (within a taller section) is
called a split merely because its x-position differs. Both negative cases are
now in the root hero acceptance subset. Side-media inference must respect
ancestor visibility and require actual vertical coexistence, not just horizontal
separation. The current independent file contains eight cases in total.

The revised geometry helper now prunes invisible ancestor subtrees and requires
vertical overlap between candidate media and qualifying text. Root reviewed
those changes and reproduced **all eight independent matching checks passing**
in0.67 seconds. This is not final acceptance: maintained geometry regressions,
both terminal worker checks, the full combined suite, and refreshed benchmark
evidence remain required. The separately failing headline-role checks are not
included in those eight and remain queued.

The diagnostic also found a genuine headline/body role swap when font metadata
is missing; that is separate follow-up, not hidden by the template-ranking fix.
Root reproduced it in `artifacts/test_figma_title_roles_independent.py`: both
original and shuffled layer order fail because the longer paragraph replaces
the explicitly named, geometrically higher headline. These two intentionally
failing baseline checks are outside the active geometry/scoring task checks.
Implementation must wait for the geometry worker to release figma_adapter.py.
The eventual combined acceptance must include these checks once fixed; template
ranking alone cannot close the text-role fidelity defect.
A separate fresh-process import cycle was independently reproduced and is being
fixed under `artifacts/agency-benchmark-import-boundary.json` with subprocess
regression tests. Historical diagnostic snapshots must remain pre-fix evidence.

Root reviewed that import correction and reproduced **54 passing focused tests**
in17.09 seconds. The production diff only defers `load_benchmark_predictions`
inside `_run_current_benchmark`; it does not change exports, gate behavior,
scoring, or fixture data. Six new subprocess scenarios cover direct and varied
import orders, actual Figma predictions, and deterministic release benchmark
execution. The worker remains live pending final check/artifact completion;
combined regression with the concurrent Figma changes is still required.

Follow-up: the import-boundary process has now finished exit0. Its focused
implementation is accepted offline after root code/test review; a combined
regression run is still deferred until both Figma workers stop editing.

The refreshed benchmark has two incorrect top-1 selections in the synthetic
freeform Figma case: Riverkind hero selects centered-hero instead of a split
alternative; three stats select stats-grid-4up instead of stats-band-3up. The
stats selection is high confidence. Aggregate corpus passing does not close
these defects or prove representative Figma fidelity.

## Independently inspected source facts

- Hero group 110:1 has a 1440x820 bounding box. Its image is at x=680,y=80,
  size620x620. Text boxes are at x=120 with widths620,520,180. The headline
  partially overlaps the image horizontally; a simplistic zero-overlap rule
  would miss this layout. Other text is to the image's left.
- Stats group120:1 has a parent1280x300 box and six text children representing
  three value/label pairs. None of those children has a bounding box. Source
  count is available, but actual child column geometry is not.
- Current Figma `_layout` has a side-image geometry branch restricted to
  call_to_action. Other freeform sections use direct-child row counting and
  emit media_position=none. These are code facts, not yet a verified causal
  attribution of both benchmark failures.
- Both native stats templates can expand. Their default item counts differ
  (three and four). The matcher gives FREEFORM a grid compatibility score of
  0.5; band is absent from that map and receives the0.25 fallback. How these
  values combine with other scores must be measured before choosing a fix.

## Fix acceptance constraints

Preserve source-only evidence and distinguish known cardinality from unknown
geometry. No fixture names, node IDs, client text, forced template choices,
annotation weakening, or threshold reduction belongs in production fixes.
Hero tests must cover mirrored media, partial overlap, backgrounds, decorative
images, and missing bounds. Stats tests must vary counts and measured versus
missing geometry; do not fabricate columns merely from repeat count. Keep
source-specific inference inside the Figma adapter and source-neutral scoring
inside the matcher. Preserve all existing adapter and native ownership tests.

The scratch-only diagnostic manifest is
`artifacts/agency-figma-match-diagnostic.json`; its findings must be reviewed
and replayed before implementation ownership is assigned. Representative live
Figma trials and hands-on time measurements remain separate acceptance gates.
