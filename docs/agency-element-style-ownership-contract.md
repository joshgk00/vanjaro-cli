# Element-owned styling through semantic binding

Status: confirmed missing transport; implementation follows responsive-condition
work because planner/composer ownership overlaps.

## Evidence

The accepted generated-browser baseline shows a source sans-serif heading and
blue rectangular action becoming the installed template's display heading and
red pill action. This is broader than the confirmed responsive height problem.

Source inspection identifies a concrete transport gap:

- `html_adapter._attach_type_samples` attaches measured font family/size/weight
  to the sampled heading and body `ContentElement.style`.
- `_attach_action_sample` attaches measured background/text colors to the first
  sampled action's own style. These are element-owned observations, not section
  styles; applying them to the section would target the wrong component.
- Planner translation currently consumes section styles/responsive observations,
  while semantic bindings carry element IDs and content values but not their
  executable styles into generated components.

Root check `artifacts/test_element_style_ownership_independent.py` exercises
actual plan -> library -> page composition. It proves the target element is
bound and the section is nonblocking, then requires its style on its exact
generated owner. Both cases fail (2 failed, exit 1): section heading font-size
33.333px and first card action background rgb(12,34,56). These offline cases
prove style loss independently of fonts loading or browser screenshots.

## Required outcome

Supported style observations on content elements follow their semantic bindings
to the exact generated heading/text/action/media component. Prefer actual
native/theme/agency-standard mechanisms, using scoped CSS only when needed.
Never repair a child-style mismatch by styling the section or all sibling cards.
Keep all content editable using built-in components.

## Requirements and acceptance

1. Resolve `source_element_ids` through physical slot ownership. Reject/report
   ambiguous one-to-many and many-to-one style ownership rather than styling an
   arbitrary first node. Distinguish a link wrapper from an image child.
2. Translate element styles with the same target capabilities and reviewed
   configuration as section styles. Do not duplicate the translation hierarchy
   in a second hardcoded planner. Share validation without circular imports.
3. Emit structured owner-aware actions and revalidate serialized input before
   composition. Preserve page namespacing, hashes, approvals and registration
   kind; no arbitrary selectors, HTML fragments or untrusted class families.
4. Preserve base and supported responsive conditions on the right owner, reusing
   the responsive contract rather than interpreting frame width as a breakpoint.
5. Existing template heading/button classes may override inherited section
   values. Verify computed styles at the actual element, and remove/replace
   conflicting known defaults deliberately without flattening native components.
6. Test differently styled sibling cards, section title vs card titles, separate
   buttons/links, linked images and multiple sections/pages. Assert no style
   leakage and unchanged visitor text/action destinations.
7. Root ownership checks must pass. Maintained contract tests and a fresh browser
   fixture must prove heading font metrics and action colors on generated owners
   using real installed theme CSS. Missing fonts must be explicitly reported,
   not quietly counted as visual parity.
8. Keep global theme application distinct from per-element overrides: the browser
   baseline loads installed Theme.css but does not execute a project's theme
   build stage. Do not attribute every theme-level difference to element loss,
   or claim this fix alone closes the full theme/style pipeline.
9. Record remaining unsupported element properties, modifier execution and source
   acquisition gaps. The current adapter's type sample covers only three font
   fields and one representative element per kind; that is not proof of every
   element's color, radius, padding, hover state or responsive typography.

No live portal mutations are authorized by this offline correction contract.

## Implementation sequencing confirmed on 2026-09-22

Root reran both independent ownership checks after the source-condition and
source-adapter changes: both still fail at the final generated-owner assertion.
The content is bound and the matches are nonblocking; this is not a template
selection or missing-content test failure.

Use the actual post-expansion component tree to resolve owners:
`utils/block_compose.py` expands repeated columns and heading/text/image/action
slots before applying overrides. A physical path taken from the original
template can therefore point at the wrong sibling after expansion. Reuse its
slot-walking rules rather than building a competing text-search matcher.
`enumerate_slots` currently exposes values and field kinds, not component
references; any new owner resolver must share its numbering and linked-image
semantics. Resolve image style to the image and image-link style to its wrapper.

`ContentElement` currently has a base `StyleSet` but no responsive observation
list. Do not pretend section-level responsive observations are child evidence.
Supported conditional property observations can use the existing condition
transport; richer per-element acquisition remains a distinct gap unless the
implementation adds and verifies it explicitly.

Do not modify planner/composer/adapter production files while the scratch-only
source-workflow browser audit is recording their behavior. Finish that audit
first, then dispatch the owner-aware implementation with disjoint ownership
from any responsive-cascade correction. Root acceptance must retain the two
existing owner checks and add sibling isolation and unsafe payload cases;
browser validation must separately prove computed values with the real theme.

Additional ownership hazard found during implementation planning:
`apply_overrides` expands slots, applies content, inserts linked-image wrappers,
prunes explicitly empty slots, and finally balances card rows. Simply enumerating
the returned tree can therefore renumber a surviving heading or action after an
earlier empty slot is removed. Capture stable owner references/identities at the
same expanded-tree traversal that applies overrides, then carry those owners
through pruning and wrapping. Do not infer ownership from final text or final
ordinal position. Add a regression with an explicitly cleared earlier heading
and differently styled later heading, plus a cloned repeated-card case. A
removed owner must be reported rather than redirected to the next sibling.

## Independent review of the in-progress implementation

Root added `artifacts/test_element_style_sibling_isolation_independent.py`:
two actions deliberately share the label `Learn more`, but have different hrefs
and background colors. The generated styles must resolve to exactly one owner
per color and retain its original destination, without mutating source evidence.
The pre-implementation run failed due to missing styles, as expected.

Root also added `artifacts/test_element_condition_scope_independent.py`. Against
the draft implementation, a title's source-observed `text-align:right` under
`max-width:480px` becomes an unconditional `text-end` class. The check fails at
that exact class assertion. Recheck the final worker output before acceptance;
the supported conditional rule must retain its width scope on the heading.
Reusing the base-style translator without preserving conditions on native
decisions is not sufficient. Do not change the independent check to accept an
unconditional class or silent omission.

The additional root boundary check
`artifacts/test_element_style_payload_boundary_independent.py` rejects explicit
`None`, `False`, zero, empty string and object metadata. Draft result: four
pass, but explicit JSON null silently succeeds. An omitted legacy field or an
explicit empty list is valid absence; null is not a valid list of actions.
Recheck this independently after the worker finishes. Keep old artifacts that
omit the field compatible without treating malformed supplied data as absent.

### Terminal implementation review

Run `20260922T091514Z-p285094` completed on attempt 1 with exit 0: its declared
check passed 2 root regressions and 218 maintained checks. Root reviewed the
owner-capture traversal, element translation/serialization/application helper,
and maintained test coverage. Independent root checks now pass for heading
font size, button background color and same-label sibling isolation. The latest
combined root and maintained element check returned 40 passed and 2 failed.

The two failures are conditional native alignment and explicit null metadata,
confirmed again after the worker became terminal. They are not waived by the
manifest PASS. `artifacts/agency-element-style-boundary-fix.json` assigns the
follow-up with the independent failures as its meaningful preflight baseline.
Full real-theme browser proof remains pending; no live portal work is implied.

### Conditional and malformed-input correction verified

Run `20260922T093459Z-p307265` completed on attempt 1, exit 0: 6 independent
regressions and 171 maintained checks passed. Root reviewed the shared
translation guard (conditioned observations avoid unscoped class/modifier
paths; unresolved conditions without a breakpoint produce manual diagnostics)
and the explicit-null rejection. Root separately ran 25 focused checks and
24 combined independent ownership, responsive, native and HTML-boundary checks,
all passing. A fresh root full non-live suite completed with 3,280 passed,
2 skipped and 16 integration tests deselected in 54.88 seconds.

This accepts scope semantics and malformed-input rejection, not computed-style
parity. Root read the installed Basic Theme.css and confirmed `.text-center`
and `.text-end` declare text-align with `!important`. A scoped normal-priority
rule will not automatically defeat such a utility on the same owner. Preserve
base behavior as well as the conditional override when addressing that case;
do not use broad source-important authorization as a shortcut. Fresh actual
browser proof and the pending source-workflow browser audit remain outstanding.

### Same-owner utility precedence: independent verification

On 2026-09-22, the root regression was expanded to four pipeline cases:
section and child-element ownership, each with and without an explicit source
base-alignment observation. This exposed a second collision: the feature-card
heading template already carries `text-center`, even when source evidence only
supplies a conditional alignment. Checking source decisions alone missed it.

The current correction inspects the actual owner's classes after validated
native actions are applied. It uses the canonical platform utility families to
promote only colliding CSS properties, preserving the conditional bounds and
the template's base behavior. It does not broadly authorize source-supplied
important syntax or arbitrary unknown utility mappings.

Root reran all four independent precedence cases: 4 passed. The focused
maintained style, safety and sibling-isolation suite returned 138 passed.
A fresh root non-live repository suite returned 3,292 passed, 2 skipped and
16 integration tests deselected in 55.78 seconds. The Ringer worker was still
running its final checks at the time of this entry; this records current-tree
verification, not a terminal run acceptance. Actual browser computed-style
validation, broader CSS cascade coverage and representative client fidelity
remain unproven. No portal mutation or publication was performed for these
checks.

### Terminal precedence run: tests pass, handoff fails

Run `vanjaro-agency-translation-retention-20260922T094755Z-p320970`
finished with status `fail` after two attempts. Its executable checks exited 0
on the final attempt (4 independent and 138 maintained checks), but Ringer
could not find the required task-local `notes.md`. The worker wrote to the
repository-root notes instead and incorrectly described the missing deliverable
as a transient race. Do not report this run as verified PASS.

After the terminal result, root independently reran the precedence, native,
malformed-input and style-safety subset: 78 passed. The worker also reported
line-ending normalization in `planner.py`, outside its declared ownership;
that ownership violation is not excused by passing tests. Preserve the current
tree and review overlapping serialization work carefully. The next manifest
uses an explicit absolute task-local notes destination to avoid repeating the
handoff ambiguity. Browser parity remains outstanding.
