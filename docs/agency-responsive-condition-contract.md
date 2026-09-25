# Source-backed responsive condition transport

Status: confirmed acquisition/transport gap; browser baseline in progress.

## Evidence and required outcome

`ResponsiveObservation` currently records a named breakpoint, capture viewport,
style delta and provenance, but no authored application condition.
`capture_rendered_observations` reads computed styles without matched CSS media
conditions. `translate_responsive_observations` emits breakpoint-prefixed keys.
`style_transport.py` converts tablet/mobile keys to max-width 768px/390px.
Those are sample sizes, not observed source transition thresholds. The synthetic
source used in the browser proof declares 1023px/480px thresholds instead.

Generated sites must preserve supported source responsive rules between sampled
widths, and distinguish exact source evidence from an agency-approved responsive
interpretation. Changing the two constants to this fixture's values is not a fix.

## Requirements

1. Add a typed, versioned condition representation independent of source kind.
   Keep sample viewport, authored condition and inferred/approved policy distinct.
   Conditions must identify their affected properties/owners and carry provenance.
   One breakpoint label cannot stand in for several different media conditions.
2. For rendered HTML, collect applicable CSS rule evidence from accessible
   stylesheets. Account for source order, inherited/nested media restrictions,
   selector ownership and declaration priority before claiming attribution.
   Do not assign the first media query found in a document to every section.
   Unreadable cross-origin sheets, container queries, unsupported expressions,
   unresolved cascade or script-driven transitions must produce explicit gaps.
3. Preserve existing sample observations when condition acquisition is incomplete.
   Missing threshold evidence must not become a fabricated authored breakpoint.
   Figma/image frame sizes likewise cannot prove transition thresholds. Support
   an explicit reviewed agency breakpoint policy for these sources and record
   that policy as an interpretation, not an observation.
4. Carry supported condition semantics through typed document, planner, serialized
   library, composition and page styles. Keep the generated rule order and
   specificity sufficient to preserve the supported cascade. Stable section
   ownership and page ID namespacing must remain valid at every stage.
5. Apply responsive native choices through known target-supported behavior or
   a deliberate supported scoped-CSS action. Never emit contradictory
   unconditional classes or assume every Bootstrap utility has a responsive
   variant. Unsupported actions must remain visible and actionable.
6. Validate serialized conditions before emission, using a constrained grammar or
   structured numeric fields, not arbitrary CSS strings. Retain HTML/style safety,
   budgets and hash determinism. Any approved policy change invalidates affected
   plans/receipts; old artifacts need an explicit compatibility path.
7. Keep browser I/O in acquisition/orchestration; condition normalization and
   translation should be pure, cohesive modules. Do not enlarge already-large
   adapters with a second monolithic parser. Avoid new dependencies unless needed
   and justified before addition.

## Acceptance criteria

- Browser proof follows actual production capture -> document -> plan -> library
  -> page -> render without hand-authored generated CSS or forced observations.
- The existing base/variant synthetic sources match min-height and background
  position at 1440, 768, 390, 414, 900, 480, 481, 1023 and 1024 pixels. Both
  variant-specific mobile values survive; desktop/tablet remain unchanged.
- A second fixture uses different thresholds and distinct per-section/property
  conditions. Exact output must follow those rules, not hardcoded fixture values.
- Test min/max ranges, nested conditions, rule-order overrides, !important,
  unmatched selectors and inherited values within the supported grammar. An
  unsupported case must report why rather than claim exact reproduction.
- Missing or inaccessible CSS evidence retains observations and requires a
  reviewed policy or explicit unresolved state. Synthetic Figma/image cases
  prove capture width is not silently promoted to an authored condition.
- Malformed or malicious serialized conditions fail before any portal mutation.
- Unit/contract tests cover serialization, hashes, namespaced selectors and
  target utilities; integrated non-live suite and existing root checks pass.
- Browser evidence clearly separates supported property parity from overall
  visual similarity and from real-client quality/time-saving measurements.

## Preliminary browser review, not final acceptance

The active generated-browser worker produced its first full matrix on
2026-09-22. It shows matching min-height/background-position at canonical
widths, and mismatches at 414, 480, 900 and 1023 pixels for both variants.
However, that first evidence gate failed 18 unique-selector assertions because
its generated selector matched the section and six descendants. The worker is
rerunning after harness corrections. Do not accept that matrix as final until
the owning-element assertions and complete evidence gate pass.

Root visually inspected the actual 414px source/generated screenshots. Beyond
height, the generated hero differs substantially in background, heading font,
text color and button appearance. The source has a data-URI SVG background;
the generated page does not visibly retain that background. These observations
do not authorize unsafe data-URI acceptance and are not yet root-cause diagnoses
for each visual difference. They do prove that eventual min-height and
background-position equality alone cannot support a whole-design fidelity
claim. The generated page is explicitly hero-only while the source screenshot
includes later sections; missing later sections in that isolated artifact are
not evidence of pipeline loss.

## Sequencing

### Draft-code review items while implementation is active

Root inspected the in-progress helpers; these are review risks, not accepted
final defects or permission to overlap the worker's writes:

- CSSOM acquisition currently rounds parsed fractional pixel thresholds with
  `Math.round`. If the supported model uses integers, fractional bounds must be
  explicitly unsupported or represented exactly; rounding changes behavior.
- Selector specificity is estimated with string counts. Functional pseudo-classes
  such as `:where`, `:is` and `:not`, escaped identifiers and comma-containing
  selector arguments require correct semantics or an explicit unsupported path.
  Matching a computed value at one sample does not prove its winning condition.
- `condition_sort_key` orders rules by narrower bounds. Narrower media queries
  do not inherently outrank broader ones in CSS. Preserve relevant cascade
  order/priority or partition the effective ranges; test overlap cases where
  the wider query is later or more specific.
- Conditions active only between all canonical capture widths must not disappear
  merely because no sampled observation changes. Preserve accessible authored
  evidence for those intervals or flag the coverage gap explicitly; three
  agreeing samples cannot establish complete responsive behavior.

Reinspect the final implementation and test these cases before accepting its
claims about supported grammar and exact source condition transport.

Root confirmed one draft failure with an executable regression:
`artifacts/test_responsive_fallback_disclosure_independent.py` currently has
2 failures (exit 1). For both missing condition evidence and explicitly
UNRESOLVED condition evidence, the translator emits legacy mobile CSS keys
without any warning identifying the threshold assumption. Keeping old output
compatible is not permission to present that inferred threshold silently.
Recheck after the active owner finishes; require explicit approximation/policy
disclosure without suppressing the observed source values to make a test pass.

The corrected browser baseline is now accepted as diagnostic evidence.
Run `vanjaro-agency-translation-retention-20260922T080807Z-p214456`
completed on attempt 1, exit 0. Its fresh Chromium 145.0.7632.6 sweep passed
174/174 evidence assertions; the separate `fidelity_pass` remains false.
Root reviewed generated ID selectors (exactly one owner), harvested notes and
the source-linked matrix, then independently ran
`artifacts/test_generated_browser_evidence_integrity.py`: 1 passed, exit 0.
Source/generated/theme hashes agree with files, and per-row parity flags agree
with actual measured values. The former seven-node selector issue is corrected.

The original browser run ended unsuccessfully after a fixed 60-second check
timeout and mismatched expected HTML filenames; its automatic retry was
explicitly canceled before the corrected run started. Do not count that
original run as PASS. Long browser execution now occurs in the worker, with a
fast executable validator checking fresh evidence instead of timing out during
repeated browser execution in Ringer's authoritative check.

Implementation is dispatched via `artifacts/agency-responsive-conditions-fix.json`
only after the corrected browser worker became terminal. The lane owns the
typed condition/acquisition/translation/composition path and its new maintained
tests, with an independent browser acceptance checker at
`artifacts/test_source_condition_browser_acceptance.py`. Keep the accepted
baseline artifacts unchanged. Agency workflow integration and native semantic
action validation remain separate unresolved work; do not overlap their shared
planner/composer files with this implementation.

Complete the typed acquisition/transport implementation under its declared
ownership. Do not parallelize it with agency style workflow edits where
planner/composer ownership overlaps. Rerun equivalent browser measurements
after integration and retain both before/after evidence. No live portal
mutation is authorized by this contract.

### 2026-09-22 integration review: sample coverage is not full fidelity

The responsive implementation run `20260922T081905Z-p225500` is terminal:
PASS on attempt 1, check exit 0, 299 checks passed. Root independently reran
the fresh browser acceptance: 5 passed. All three synthetic source schemes
match generated min-height and background-position across their nine sampled
widths, including the previously failing intermediate widths. This proves those
properties on those fixtures, not complete design fidelity or arbitrary CSS.

The source-adapter forwarding run `20260922T084708Z-p254326` also completed on
attempt 1. Root read the production forwarding change and independently ran
the regression plus maintained source-adapter tests: 21 passed. These tests
use deterministic capture evidence; a fresh real-browser audit through
`HtmlSourceAdapter.analyze` is still required. The earlier browser helper called
the lower-level analyzer directly.

Root reconfirmed two fallback-disclosure failures after both runs completed.
The correction is assigned by `artifacts/agency-responsive-disclosure-fix.json`;
do not treat its dispatch as acceptance. Separately, final code still rounds
fractional CSS thresholds and transports only conditions attached to sampled
style deltas. The scratch-only browser audit in
`artifacts/agency-source-workflow-browser-audit.json` tests the normal adapter,
an interval missed by all three canonical samples, and a 480.5px boundary.
Its checker validates honest evidence; adversarial parity failures must remain
reported failures of the product, even if the evidence-integrity check passes.

The disclosure correction subsequently completed as run
`20260922T085310Z-p260643`, attempt 1, PASS, exit 0 (2 independent and 82
maintained checks). Root reviewed the emitted-warning helper and reran its
independent and newly maintained checks: 7 passed. Values remain emitted;
missing/unresolved conditions now produce property-specific approximation
warnings, including unresolved reasons. This is disclosure, not an improvement
to the underlying fallback widths. A full non-live root suite during this
integration passed 3,231 tests, 2 skipped, 16 integration tests deselected;
the newly added disclosure tests were checked separately afterward.

Both implementation workers are terminal before dispatching the scratch-only
normal-workflow browser audit. It must establish actual adapter-path browser
behavior and assess the unsampled interval and fractional-boundary risks before
claiming those cases supported.
