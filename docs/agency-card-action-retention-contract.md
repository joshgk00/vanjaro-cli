# Card action retention: next scoped accuracy task

Status: implementation running; not yet accepted. The preceding native
image-link correction is accepted offline and must not be conflated with
preserving separate card actions.

The extraction-only diagnostic completed through
`artifacts/agency-card-action-diagnostic.json` as
`measure-card-action-extraction`. It owns only its scratch probe, measured JSON,
and notes. It deliberately did not import the planner/composer being edited
at the time by the independent image-link worker. Final native action retention
remains a later acceptance requirement, not a claim of this diagnostic.

The implementation is dispatched through
`artifacts/agency-card-action-retention.json` as `retain-owned-card-actions`.
Its declared full-check baseline failed as expected and verified preflight
passed in 50.335 seconds. Ownership is restricted to `html_ownership.py`, a new
cohesive `html_card_actions.py`, planner destination safety, and one new
maintained test file. It cannot change templates, thresholds, existing tests,
root acceptance, the image-link helper/composer, or portal state. Acceptance
requires all prior offline/article/image/capture checks plus the new action
checks and a validated composed native example. No overlapping implementation
worker remains active.

## Current evidence

Reviewed on 2026-09-22:

- `vanjaro_cli/design/html_ownership.py` constructs repeated card fields from
  images, headings, and paragraphs. Its card branch currently creates no action
  field. The later section-wide link sweep skips every node inside repeated
  items. A standalone `Learn more` anchor inside a card can therefore disappear
  from the source-neutral document entirely.
- `artifacts/block-templates/Cards/feature-cards-3up.json` already declares
  optional `item.action`, with one native button slot per repeat item. Lack of
  a standard component is not the initial obstacle for this template.
- The maintained linked-image service-card fixture includes both an image link
  and a separate `Learn more` action. Its present assertions prove image-link
  ancestry only. Even if their destinations happen to match, preserving the
  image target does not prove the action label or button survived.

This is code-review evidence of an extraction gap, not a completed quantitative
benchmark. Before implementation, a read-only diagnostic must demonstrate it
through the actual adapter, global/body split, planner, and final composition.

## Required behavior

### Completed diagnostic baseline — 2026-09-22

Run `vanjaro-agency-translation-retention-20260922T043058Z-p55335` completed
PASS on attempt one with authoritative check exit 0. Root reviewed the probe's
source-control counts, actual adapter calls, repeat-item guards, ownership
matching and full-evidence comparison, inspected the harvested findings, and
independently reran `probe.py --check`: exact match.

All four fixtures classified as `feature_cards` and extracted three real items
with title/body/media. Across distinct image/action targets, matching targets,
and a missing first action, eight intended standalone actions yielded zero
owned action elements and eight losses. The negative fixture invented none.
No planner, composer, upload, portal, or browser was involved.

The worker recommends an initial single-action extraction fix with multiple
actions, capacity and unsafe destinations left for later. That scope reduction
is not accepted: requirements 5–7 below are part of the first complete fix.
An action disappearing before planning is confirmed; final native retention
and those boundary cases must still be demonstrated before accepting a fix.

Root-owned implementation acceptance is now executable in
`artifacts/test_card_action_retention_independent.py`. The baseline has eight
failures and one passing negative control. The failures cover missing owned
actions, final native controls (same and different image/action destinations),
action-only paragraph separation, a missing first action, five-card expansion,
multiple actions, and an unsafe destination being silently omitted rather than
explicitly blocked. Current unsafe actions are dropped, so this last failure is
a guard for the forthcoming retention feature, not evidence of script execution
in the present output. Final-action checks inspect exact labels, destinations,
and the containing card's native heading. Asset paths are modeled locally only.

Before implementation edits, root extended that same acceptance file with four
already-required boundaries: unstyled standalone anchors, mixed prose/inline
links, whole-card-anchor non-invention, and source-neutral unsafe action evidence
that bypasses HTML extraction. Expanded baseline: 11 failures and two passing
negative controls. This ensures the safety fix cannot be HTML-only and that
extraction cannot equate every nested hyperlink with a new button.

### First implementation review — not accepted

Root ran the independent action, article and image suites plus maintained article
tests against the first helper/planner changes: **56 passed, three failed**.
All 13 action cases passed, but category links declared with `rel="tag"` or
microdata were consumed as actions before article classification. The final
native category slot then contained byline content instead of its category.
Both root and maintained article tests caught this. The new helper currently
checks metadata class tokens on the anchor itself but does not yet honor the
existing paragraph/descendant metadata contract. This is an implementation
regression, not permission to weaken article tests or discard those semantics.

The worker then recognized metadata `rel`/microdata directly on the anchor,
restoring that 59-case combined set. Root review found the same contract was
still broken when class/microdata ownership sits on the enclosing paragraph.
Four parameterized independent cases (category, byline, articleSection, author)
now demonstrate those links being incorrectly inserted ahead of the real card
action. Current action-only result: 13 pass, four fail. Metadata ownership must
be respected on the owning paragraph as well as the anchor without consuming
the paragraph's content as an invented control.

That paragraph-level correction restores the combined 63-case focused suite.
Review of its boundary logic found it still checks only the anchor and immediate
paragraph, and only the selected primary heading. Three further cases now prove
incorrect action invention for category/author metadata on an intervening span
and for a secondary linked heading in the same card. Current action-only
acceptance is 17 passes and three failures. These enforce the existing metadata
and linked-heading exclusions across ownership ancestry, rather than expanding
the feature to preserve additional kinds of linked content.

The next correction passes the 73-case combined focused set and the regenerated
native example validates. Review still found two direct violations of the same
contract: metadata ancestry stops at the action paragraph rather than the card,
so `<div class="byline"><p><a>Writer</a></p></div>` becomes an invented action;
and two standalone buttons grouped within one paragraph are treated as prose,
so neither enters the ordered action list. Both are now executable independent
cases: **20 pass, two fail**. Multiple controls in an action-only paragraph must
remain distinct actions (and trigger capacity blocking if needed); real mixed
prose must still remain prose. Metadata inspection must respect owning ancestors
within the card, without inheriting unrelated page-level markers.

### Native template prerequisite — separate scoped repair

Root independently reproduced native validator failure on both the composed
action example and the unmodified authoring template
`Cards/feature-cards-3up.json`: `tpl-fc3-h0` is directly under `section` and lacks
a heading style preset. This pre-existing defect is not waived by action tests.

`artifacts/agency-feature-card-native-template.json` now dispatches
`repair-feature-card-heading-structure`, owning only that authoring template and
one new focused native-contract test file. Its baseline validator failed for
the two expected reasons. It must preserve the existing title ID/heading_1
identity and all card nodes, add head-style-2 and a standard full-width title
row/column inside the existing grid, and verify three/five-card composition.
This task has disjoint write ownership from the action worker; final joint
regressions remain required. No published agency pack is modified.

The action example was generated before the template repair. Its owner must
regenerate it from the corrected real template before final native validation;
do not hand-edit the example or remove the validator to obtain a passing result.

Template repair completed: run
`vanjaro-agency-translation-retention-20260922T045915Z-p67431` finished PASS on
attempt one, check exit 0. Root reviewed the harvested notes and actual template
hierarchy, confirmed source validation passes with no errors/warnings, reviewed
the new native-contract tests (actual subprocess validation and final image/
button ancestry), and reproduced **145 passing** template/catalog/composer/image
checks. Three- and five-card compositions both validate; the title remains
`heading_1`, is not repeated, and can be cleared without removing card content.
This scoped template repair is accepted offline. The action implementation and
its combined final verification remain pending.

1. Preserve a standalone card action's exact visible label and destination as
   source-neutral content owned by that exact repeat item. Use the existing
   action field and native button/link capabilities where supported.
2. Preserve both an image destination and a separate action, including when
   they point to different pages. Do not deduplicate different visible controls
   merely because their destinations match.
3. Do not reinterpret a linked image, linked heading, category, author label,
   or inline prose link as a new standalone action. Their distinct ownership
   remains intact; a whole-card anchor must not manufacture a button.
4. A paragraph whose entire content is the standalone action must not also
   become duplicate body copy. A paragraph mixing prose and an inline link
   must retain its prose; do not solve this task by dropping that paragraph.
5. Preserve multiple actions in the intermediate representation. If a selected
   native template owns fewer action slots, block with an actionable ownership
   or capacity diagnostic rather than choosing the first action silently.
6. An absent first-item action must not shift the second item's action into the
   first card. Expanded repeats must preserve the same source-item ownership.
7. Unsafe destinations must not become executable native links. Reuse an
   appropriate shared safety boundary where available; do not introduce
   divergent per-adapter scheme allowlists or echo secret-bearing URLs.
8. Extraction stays in the HTML adapter boundary. Do not import final
   composition into source extraction. Prefer a cohesive helper if action
   ownership rules would substantially enlarge `html_ownership.py`.
9. No client-specific text, selector exceptions, new dependency, raw-HTML
   fallback, matching-threshold relaxation, or template-library variant is
   justified without separate evidence and review.

## Diagnostic and acceptance requirements

The diagnostic must record both extracted fields and final native components,
using generic fixtures with distinct labels and destinations per card. Supply
local asset paths only to model acquisition; do not claim an upload occurred.

Required fixtures and assertions:

- Three service cards with image links plus standalone actions pointing to
  distinct destinations: exact labels, destinations, and item-to-component
  ownership survive the real adapter-to-composition chain.
- Same-target image/action pairs: both visible controls survive exactly once.
- First action absent and later actions present: no ownership shift.
- More cards than the template's default: correct expanded native actions.
- Two actions in one card: both extracted, then faithfully represented or
  explicitly blocked by the selected template's capacity.
- Action-only paragraph versus mixed prose/inline link: no duplicate action
  text and no lost prose.
- Linked heading, metadata, image-only anchor, and whole-card anchor negatives:
  no invented standalone controls.
- Unsafe destination: explicit blocker/error and no executable emitted target.
- Existing article semantics and image-link independent acceptance remain
  passing. Run the full offline suite and validate an actual composed native
  example; inspect final labels and ancestry, not override inputs alone.

## Execution boundary

### Integration checkpoint — 2026-09-22

Final offline integration checkpoint: both integration tasks finished PASS on
attempt 1 (32 pack checks and 191 adapter/action checks, exit 0). The original
action worker finished FAIL after two attempts because its combined check ran
before integration resolved the six failures; that historic result is not
relabeled. Root subsequently ran the complete non-integration suite plus all
independent card/image/article/capture checks and the new independent pack
checks: **3,093 passed, 2 skipped, 16 deselected in 48.03 seconds**, exit 0.
The generator's read-only consistency check also returned exit 0.

Root reviewed the new immutable 1.12.0 registry payloads and generator diff:
the prior 1.11.0 digests are frozen, only Feature Cards 3up's template hash
changes, capabilities and modifiers do not change, and its upgrade rule from
1.11.0 is explicitly narrow. Independent checks use pre-change literal hashes
and mutate an unrelated template contract to prove the real upgrader blocks it.
The worker's rule-membership-only negative test was insufficient by itself.

Worker notes incorrectly call the heading repair committed and refer to an
earlier attempt for the integration task; authoritative Git/run evidence shows
the template remains a working-tree edit and this integration task took one
attempt. Accept the code's offline integration evidence, not those prose claims.
Process violations below remain recorded; tests cannot prove all prior bytes
were preserved by unauthorized restore operations. No client workspace was
upgraded by this release, and no live fidelity or time-saving result is claimed.

Root independently reproduced 58 passing focused tests across the independent
card-action checks, maintained card-action tests, and maintained/independent
article semantics tests. Grouped actions and metadata wrappers are included.
This is focused offline evidence, not final integration or live-site acceptance.

Subsequent root review of the adapter test correction reproduced 191 passing
tests (`tests/test_design_html_adapter.py` plus the independent card-action
checks). The positive test resolves each item's actual action element and
asserts its label, href, role, and title ownership. The negative test removes
one action's label and destination from actual arrival evidence before the
real section-loss reconciliation; it asserts the exact affected boundary and
missing-content count. It does not mock the loss result. The generated native
card example also passed the native validator with zero errors and warnings.
The immutable-pack worker is still live; these checks do not accept the full
combined tree while its generation changes are in progress.

The combined changes still require an immutable agency-pack release: the
accepted Feature Cards heading-structure repair changes its executable digest.
Five governance/apply failures are introduced integration regressions, not
pre-existing failures to waive. A separate stale adapter test expects a now
retained action destination to be lost; its replacement must preserve both
positive retention and genuinely missing-destination detection coverage.

`artifacts/agency-card-action-integration.json` assigns disjoint workers to
version 1.12.0 generation and that test correction. Previous release bytes,
existing client workspaces, and portal state must remain unchanged. Final
acceptance still requires a fresh complete offline suite and native validation.

Process exception: the action worker reported prohibited git stash/pop use and
claimed immediate restoration. Its claim is not independent proof of byte-level
restoration. Further workers explicitly forbid all git writes, including stash.

Integration review also caught the versioning worker using `git show HEAD:`
with shell redirection to rewrite the two read-only governance/apply test files
and its owned generator, claiming CRLF-only restoration. The two test files
currently have no Git content diff, but this does not establish original
byte-for-byte preservation. This was outside its declared write ownership and
must not be treated as an authorized cleanup. No wider restoration is approved.

First run a bounded read-only diagnostic with scratch-only outputs. Review its
evidence before specifying production ownership. Do not modify the active
image-link worker's files concurrently. Any subsequent implementation must use
the verified Ringer route and declare exact file ownership and executable checks.

No portal creation, content changes, publication, live-site fidelity claim, or
operator-time saving is authorized or proved by this task. Representative
Figma/image/live-HTML trials remain separate requirements of the agency goal.
