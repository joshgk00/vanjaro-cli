# Carry accepted design styles into composed blocks

## Executed evidence

`artifacts/test_composed_style_retention_independent.py` executes the real
planner, library-plan emitter and portal library composer using the maintained
feature-section fixture. An accepted scoped font-size of 19.123px is present
in the composition entry but absent from the composed block: rendered CSS is
empty. The root regression fails at the actual output assertion.

Source inspection: `design/planner.py::emit_library_plan` emits bindings,
identity, digest and form fields, but not the scoped CSS or its scope.
`portal/block_library.py::compose_project_library` applies content overrides
and renders template styles. `orchestration/project_build.py` uses that library
plan and composed catalog for the actual project build. No composition-plan
style application was found in this inspected path.

This is broader than minimum-height translation. Planner metrics and a
successful library-entry presence check are insufficient output proof.

Root `artifacts/test_generated_style_target_independent.py` also executes
`compose_project_pages` and requires both font-size and minimum-height to
reach page style rules, appear in visitor-facing style tags, and have selectors
matching the intended section after namespacing. Both cases failed before the
transport fix. This adds a check against inert or mis-targeted generated CSS.

## Requirements for the corrective lane

Correction to earlier worker audit: current `migration/url_rewrite.py` DOES
rewrite CSS url() references in style rules when supplied an asset lookup.
The blanket claim that it only walks src/href was inaccurate. The observed
page test passed an empty asset lookup, so unchanged output there did not
prove the helper lacked CSS support. Root traced the actual upload stage:
`portal/assets.py::_replace_strings` replaces only entire strings using local
path mappings; it neither substitutes embedded CSS URLs nor maps original
source URLs to uploaded URLs. Two root tests in
`artifacts/test_css_asset_upload_rewrite_independent.py` reproduce that upload
integration gap for local and original-source URLs. The correction must target
that real boundary and reuse existing URL rewrite capability where suitable.

Additional executed root evidence:
`artifacts/test_native_style_transport_independent.py` fails for TEXT_ALIGN
right. The planner selects the platform utility `text-end` without scoped CSS,
but no generated section has that class. This proves a native-style transport
gap independently of CSS transport. Keep it as a separate acceptance item;
after the current scoped-CSS worker is terminal, fix missing native decisions
within explicit ownership. Do not substitute custom CSS for an available native
mechanism merely to make a visual assertion pass. Actual target-platform
support and breakpoint behavior still need verification, not just class output.

Read-only target inspection on 2026-09-22 confirms the installed Basic theme's
Bootstrap source identifies version 5.1.0. In
`C:/Websites/vanjarocli/Website/Portals/0/vThemes/Basic/Theme.css`, text-end,
text-center, d-grid and align-items-center selectors are present, but
object-fit-cover and object-fit-contain are absent. The installed Bootstrap
`_utilities.scss` also contains no object-fit entry. Yet the translator's
unconditional `_UTILITY_VALUES` maps OBJECT_FIT to those missing classes.
This target compatibility gap needs a separate correction: choose only
verified available native utilities and retain safe scoped-CSS fallback when
unsupported. Do not present the installed file inspection as proof that every
portal serves that same stylesheet; confirm effective target CSS during live
validation. No live files were changed during this inspection.

- Preserve accepted scoped declarations through serialization, asset rewrite,
  library composition and final page assembly.
- Apply selectors/classes that actually match the generated component tree;
  do not merely add an unused CSS string to a report.
- Retain desktop/tablet/mobile specificity and correct breakpoint behavior.
- Preserve scope isolation between sections/projects and existing native
  template styles, editor components and content bindings.
- Validate untrusted serialized style payloads before portal mutation; retain
  value safety and budgets rather than assuming a planner once checked them.
- Include styles in content hashes and reviewed action payloads so changed
  CSS cannot silently bypass build receipts or idempotency.
- Audit native/utility/modifier decisions for the same transport gap. Report
  unsupported decisions explicitly; do not claim full translation retention
  from a scoped-CSS-only fix.
- Keep legacy library plans without design-style metadata supported.

## Acceptance

The root regression must pass. Maintained tests must cover matching selectors
on real composed trees, responsive output, malicious payload rejection,
unchanged-template behavior, scope isolation, identity/hash changes and page
namespace rewriting. Fresh browser proof must inspect the generated output at
all three viewports and the 520px-to-560px source variant change, not only
planner decisions. Full offline verification follows stable integration.

No template snapshot, annotation or threshold weakening, new dependencies,
portal writes or publication are authorized here. Assign explicit ownership
after the current source workers finish, then verify the complete build path.

## Browser proof after stable integration

Use the existing two loopback-only synthetic source variants and real Chromium
capture at desktop 1440x900, tablet 768x1024 and mobile 390x844. Produce actual
blocks and page payloads using production planner/emitter/composer functions.
Render their visitor-facing HTML/CSS, not a hand-written imitation of their
styles. Select the generated hero via its production ownership marker or a
verified component identity; record that selector and matched-node count.

At all viewports, inspect computed min-height and background-position on that
generated hero. Expected heights are desktop 720px, tablet 620px and mobile
520px for base / 560px for variant; expected mobile focal positions are
65% 50% / 25% 50%. Desktop and tablet must remain unchanged between variants.
Retain the raw capture, typed evidence and planner decisions as trace stages,
but the assertion must fail if the final generated DOM/CSS differs.

The source testimonial section has a separate blocking mapping; do not hide
that in a whole-page success claim. If isolating the hero for this proof, make
that subset explicit and report remaining sections separately. A passing hero
transport proof does not establish complete migration fidelity or live DNN
editor parity. Update the probe's hardcoded explanatory notes from actual
results and preserve historical outputs rather than rewriting prior evidence.

## Intermediate-width acceptance, discovered during implementation review

### Backend registration kind: source-backed integration blocker

Read-only inspection of
`C:/Code/Vanjaro.Platform/DesktopModules/Vanjaro/UXManager/Library/Controllers/BlockController.cs`
shows AddCustomBlock delegates to BlockManager.Add. In
`Core/Library/Managers/BlockManager.cs`, Add chooses custom-block storage only
when both Html and Css are empty; otherwise it takes the global-block branch.
The CLI `_registration_form` sends nonempty rendered Css when styles exist,
despite IsGlobal=false. Root
`artifacts/test_custom_block_registration_kind_independent.py` reproduces this
request-shape failure without contacting a portal. Fix after the safety worker
releases block_library.py. Keep StyleJSON/ContentJSON for editor composition and
page-level visitor CSS intact; do not discard styles to preserve block kind.

The inspected PageManager.FilterStyle and BlockManager.FilterStyles retain
rules by matching selector IDs against component IDs; they do not explicitly
reject mediaText. Thus the historical global-block media-loss observation must
not be blindly generalized to correctly targeted custom-block rules. The exact
installed server behavior, persistence, editor behavior and second-run reuse
still require a separately authorized live readback test. Source inspection is
not proof of deployed binary parity. No backend files or live objects were
modified during this investigation.

### Safety blocker from root review

The in-progress transport passes the root declaration-retention case and both
generated-selector cases (3 passed). Native text alignment still fails its
separate root check. More importantly,
`artifacts/test_style_html_boundary_independent.py` has two failing rejection
cases: an untrusted font-family value containing an HTML closing style tag and
script/image markup is accepted by `compose_project_library`. The current CSS
syntax filter only excludes braces/semicolons; it does not protect the HTML
style-element boundary used by page composition. No payload was opened in a
browser or sent to a portal during this check.

Treat this as an acceptance blocker for the new transport. Reject HTML-breaking
syntax before composition, keep safe quoted family names supported, and add
maintained regressions through the actual visitor HTML path. Review CSS escapes,
comments/URLs and malformed falsy metadata too; a few substring checks alone
are not a complete serialized-input contract. Preserve the original root cases
and do not weaken safety requirements to make the transport pass.

Safety follow-up in progress: root reran all six rejection cases together with
the declaration and generated-selector checks; 9 passed. The current change
rejects literal HTML angle brackets and CSS escape/comment syntax, and replaces
the truthiness guard with explicit metadata-presence validation (empty dict is
a documented no-style case). Maintained tests include safe quoted font lists
and rejection before portal client calls. The worker is still active, so final
acceptance and broader integration remain pending. Escape/comment rejection is
a supported-syntax restriction, not a claim that every valid CSS expression
is supported; do not describe it as a complete CSS parser.

Verified follow-up results: safety run
`vanjaro-agency-translation-retention-20260922T071030Z-p157969` passed on
attempt 1 (9 root checks, 86 maintained tests). Target-utility run
`vanjaro-agency-translation-retention-20260922T071354Z-p161065` also passed
on attempt 1 (12 root checks, 74 maintained tests). Root then pinned the exact
25-class independently inspected target set and reran the expanded utility/
minimum-height checks: 13 passed. The target configuration can explicitly
enable known classes or disable native utilities; it does not discover support
from a live portal. Native class transport is still not implemented.

The custom-block request-shape correction is now dispatched in
`artifacts/agency-custom-style-registration-fix.json`, after both prior workers
became terminal. Its preflight reproduced the registration-kind failure while
the nine style safety/output checks passed. No live mutation is authorized by
that offline correction task.

The in-progress style transport initially defines tablet/mobile media maxima
as 768px/390px, the capture sample widths. These are not authored breakpoints.
The actual synthetic source files use tablet max-width 1023px and mobile
max-width 480px. Thus the original three sampled widths alone could pass while
the generated layout differs at 900px or 414px. Recheck the final worker output
before attributing this provisional implementation choice to accepted code.

Extend browser proof to 414px (mobile values) and 900px (tablet values), plus
boundary-adjacent checks around source breakpoints where source evidence is
available. Do not silently equate sample width with transition threshold.
Preserving exact source behavior requires source-backed media thresholds or
an explicit documented approximation policy; a three-sample observation alone
cannot prove the location of an authored transition. If threshold evidence
does not survive the current typed pipeline, report and fix that acquisition/
transport gap rather than hardcoding fixture thresholds or claiming exact
responsive fidelity from sampled points.

### Independent upload acceptance review (2026-09-22)

While the corrected CSS asset worker remains active, root added
`artifacts/test_css_asset_upload_rejection_independent.py` to check the
manifest's existing rejection requirements through `upload_project_assets`.
Both cases currently fail (2 failed, exit 1):

- Two assets sharing one original source URL but resolving to different
  uploaded URLs return success; the ambiguous CSS reference is silently left
  unchanged rather than producing an actionable error.
- A fake upload response containing a `javascript:` URL returns success.
  Filtering it out of the CSS lookup does not reject it from the rewritten
  document, ordinary image overrides, or persisted upload records.

These are offline fake-client checks, not live portal findings. Do not accept
the upload lane solely because the ordinary local/original URL cases pass.
After its current owner finishes, review its final output against these checks
and fix any remaining failures without overlapping that worker's writes.
Validate new and reused destinations before exposing them as successful build
inputs. Reject conflicting aliases explicitly; do not guess a destination or
silently discard the rewrite report. Preserve successful safe uploads across
partial retries and retain the immutable caller-input contract.

### Native transport review and generated-browser evidence dispatch

Native transport run
`vanjaro-agency-translation-retention-20260922T072655Z-p172352` completed on
attempt 1 with exit 0: 14 root checks and 113 maintained checks. Root reviewed
the harvested notes and source integration and independently reran 35 focused
checks, all passing. Platform alignment and supported theme classes now reach
actual generated section nodes. This is not full native-style completion:
template modifier execution, media-specific ownership, responsive native
actions and agency-utility configuration through the project CLI remain open.
Direct-call agency-utility tests do not prove the CLI workflow supports them.

Fresh generated-browser verification is dispatched through
`artifacts/agency-generated-browser-proof.json`. It reads production code and
existing synthetic source fixtures without changing them. The new evidence
must follow capture -> typed document -> plan -> library -> page -> browser
and compare 1440, 768, 390, 414, 900, 480, 481, 1023 and 1024 pixel widths.
It also measures native alignment with actual installed target CSS. The
focused hero subset, other sections' blockers, actual file hashes and browser
version must be explicit. Diagnostic evidence success is separate from
responsive fidelity success; no whole-site or real-client acceptance is
implied. Do not modify the measured production path while this run is active.

Asset run `vanjaro-agency-translation-retention-20260922T073130Z-p176946`
completed on attempt 1, exit 0 (2 root + 117 maintained checks), but root's
expanded acceptance still failed the two rejection cases above. Corrective
run `artifacts/agency-css-asset-rejection-fix.json` is active. Its scope is
upload validation and does not overlap the browser probe's measured path.

### Integrated offline verification after upload rejection correction

Run `vanjaro-agency-translation-retention-20260922T074018Z-p185979`
completed on attempt 1, exit 0: 4 root checks and 122 maintained checks.
Root reviewed the harvested report, upload acceptance implementation and tests.
Unsafe fresh and reused destinations are rejected at the acceptance boundary;
conflicting original aliases are rejected before upload; safe earlier uploads
are retained when a later response fails. The alias guard is deliberately
conservative: distinct asset IDs sharing a source URL are rejected even before
their eventual destinations are known. URL checks are syntactic, not proof of
live resource availability or target-portal ownership.

With both production workers terminal, root ran the integrated suite:

```
python -m pytest -m "not integration" -q -p no:cacheprovider
3157 passed, 2 skipped, 16 deselected in 54.69s
```

Exit 0. A separate root run of 11 independent artifact test files covering
upload rejection/rewrite, native class transport, minimum height, nested chrome,
semantic article ownership, composed CSS, generated selectors, HTML safety,
custom registration kind and target utilities passed all 33 checks (exit 0).

These results do not include the known failing agency serialization regression
`artifacts/test_agency_style_serialization_independent.py`: its required fix is
tracked in `docs/agency-style-workflow-integration-contract.md`. The normal
suite does not automatically collect artifact checks. Generated-browser run
`vanjaro-agency-translation-retention-20260922T074332Z-p189422` remains active
and is read-only against production code. No live integration, publication or
real-client fidelity claim follows from these offline passes.
