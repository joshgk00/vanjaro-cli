# Responsive benchmark evidence review

## Finding — 2026-09-22

The historical combined benchmark reports responsive coverage of 39/44 for
the five HTML/Figma cases. Read-only inspection confirms that the five missing
expectations are not present in the HTML inputs given to the adapter:

| Case / section | Mobile expectation | Supplied evidence |
| --- | --- | --- |
| Northstar hero | `min_height=520px` | Background-image inline style only; no stylesheet or media query |
| Northstar hero | `background_position=65% 50%` | No background-position declaration |
| Northstar testimonials | `carousel=true` | Two ordinary figures; no carousel script, class, attribute or interaction declaration |
| Juniper hero | `min_height=600px` | Elementor-like wrappers; no stylesheet or media query |
| Juniper testimonials | `carousel=true` | Three static blockquotes inside a testimonial wrapper; no carousel behavior declaration |

Sources inspected:

- `tests/fixtures/design-benchmarks/cases/html-bootstrap-agency/source.html`
- `tests/fixtures/design-benchmarks/cases/html-bootstrap-agency/annotations.json`
- `tests/fixtures/design-benchmarks/cases/html-elementor-studio/source.html`
- `tests/fixtures/design-benchmarks/cases/html-elementor-studio/annotations.json`
- Both corresponding `references/*-mobile.svg` files.
- `vanjaro_cli/design/benchmark_corpus.py::load_benchmark_predictions`.
- `artifacts/benchmarks/agency-retention-integrated-20260922/design-benchmarks/benchmark.json`.

The HTML loader constructs `HtmlSourceRequest` from the HTML string, URL, title
and timestamp only. It does not feed these SVG drawings or captured mobile
computed styles into HTML analysis. The drawings are coarse synthetic shapes
and do not establish the requested minimum heights, focal point or carousel
interaction independently.

## Consequence

These missing observations are not evidence that the adapter discarded those
five values. They show an input/expectation gap. Do not add client-specific
rules, infer an exact pixel height from unrelated text, equate testimonials
with a carousel, or report a fabricated observation as extracted evidence.
Existing fixtures, thresholds and historical reports remain unchanged.

## Next implementation acceptance

Create a separately identified responsive source-backed benchmark case or
versioned corpus revision, preserving the old baseline. Supply reproducible
desktop/tablet/mobile source evidence that actually encodes each expectation:
real responsive CSS and rendered observations for geometry and focal position,
and explicit behavior evidence for a carousel. Exercise acquisition through
adapter output and downstream composition, not hand-built Section objects.

Required tests:

1. The supplied mobile evidence contains the expected value, with source and
   viewport provenance; changing the source changes the extracted observation.
2. Desktop values are not silently assigned to mobile and vice versa.
3. Absent evidence stays absent or explicitly inferred/review-required; it does
   not receive observed status or a fixture-specific default.
4. Static testimonials do not acquire carousel behavior merely from their role.
5. Supported observed styles reach native/agency-standard output where possible;
   unsupported interaction behavior is reported for review, not silently lost.
6. Original benchmark results remain reproducible and separately labeled from
   the new evidence-backed corpus. No denominator or threshold changes are used
   to claim that production translation improved.

This review is an evidence diagnosis, not a completed responsive implementation
or a live-project fidelity result.

## Source-backed browser probe dispatched

`artifacts/agency-responsive-browser-proof.json` runs a separate scratch-only
probe of the real browser capture and HTML adapter. It authors synthetic local
HTML with explicit desktop/tablet/mobile minimum heights and focal positions,
then changes only the mobile CSS and checks that the measured mobile evidence
changes while desktop/tablet stay stable. It also traces downstream composition
without bypassing blockers. No existing fixtures, thresholds, client assets or
portals are in its write scope. The worker remains active; no outcome is claimed
until its executable proof and actual outputs are reviewed.

## Browser proof and downstream findings

Run `vanjaro-agency-translation-retention-20260922T062032Z-p115302` finished
PASS on attempt 1, check exit 0. Root read the actual script and harvested
notes and independently executed a fresh browser run: **35/35 assertions
passed**, exit 0. The script calls production Chromium capture and HTML
analysis, not a fake browser. Both source variants are synthetic local HTML.

Actual desktop/tablet/mobile minimum heights are 720/620/520px in the base
and 720/620/560px in the variant. Mobile background position changes from
65% 50% to 25% 50%; desktop/tablet remain 50% 50%. Typed responsive evidence
retains these values as observed. Root added independent typed-evidence and
planner focal-position assertions in
`artifacts/test_responsive_probe_evidence_independent.py` because the worker's
35 assertions primarily checked raw captures, roles and testimonial grouping.

Two downstream findings remain distinct from the passing capture:

1. `min_height` becomes `measurement_only` in style translation, even for
   this explicitly authored CSS. All three observed heights therefore fail
   to reach generated styling. Background-position does reach scoped CSS.
   Resolve declared design intent versus incidental measured geometry before
   changing the translator; do not blindly reproduce every computed dimension.
2. Nested testimonial `<footer>` attributions are collected as page chrome.
   The no-site-footer page acquires an erroneous fourth global-footer section,
   and browser capture also includes local footer boundaries. Root reproduced
   this independently: one failure and one genuine-footer positive control
   passed in `artifacts/test_nested_chrome_independent.py`.

`artifacts/agency-nested-footer-fix.json` is active with exclusive static and
rendered boundary ownership. Its check regenerates the browser report and
requires exactly the three source sections, retained text ownership and typed
responsive values. The original probe's harvested artifact preserves the
pre-fix evidence. The Ringer preflight failed on the not-yet-created maintained
test file, so the meaningful defect baseline is the separate root test result,
not that preflight failure alone.

These results are not a full generated-site visual comparison or a live
client release. The testimonial plan is also blocked and matched a CTA
candidate; investigate its retained field/capability evidence separately from
the false global-footer boundary before changing matcher rules.

### Footer correction review in progress

The worker's initial structural filter excludes footer candidates owned by
blockquote/article/section ancestors and mirrors that rule in browser capture.
Root's original two testimonial cases pass. Maintained tests then exposed that
article-local bylines can be absent from the typed content even after the false
global footer is removed (2 failed, 9 passed in the focused run).

Root added independent article-byline cases with and without a genuine site
footer. Both fail on missing byline content; the original two cases still pass.
All four are in the worker's existing acceptance path. Removing a false boundary
is not sufficient if visitor content disappears. The worker remains live, so
this correction is not accepted yet.

Minimum-height follow-up requirements and a verified four-fail/five-pass
translator baseline are in `agency-minimum-height-intent-contract.md`.
The pure translator correction is now running in a disjoint ownership lane
(`artifacts/agency-minimum-height-fix.json`); its preflight reproduced the four
constraint failures. The shared browser probe and its outputs remain reserved
to the footer worker until it becomes terminal. Integration is not yet proven.

Additional root inspection explains the isolated-article failure:
`migration/sections.py::_WRAPPER_TAGS` includes `article`, and
`_top_level_sections` unconditionally descends a lone article into its children.
The now-detached footer is subsequently skipped as chrome. Dominant-container
expansion also assumes content never contains a local header/footer. The worker
adjusted its maintained article fixtures to add enough surrounding content to
avoid that pre-existing wrapper path; those tests now pass, but the root's
isolated-article cases remain two failures. That is useful isolation, not proof
that arbitrary article content is retained. Do not accept the broader retention
claim or remove those failing root checks. A correct fix must preserve genuine
semantic article ownership while retaining real layout-wrapper descent.
