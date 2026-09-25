# Native image-link retention

## Confirmed problem

The HTML ownership adapter records an enclosing anchor's destination on an
image's `attributes.href`. The planner currently binds only the image source
and alt text. Composition therefore produces an ordinary image, without a
clickable owner.

The read-only probe under
`artifacts/ringer-agency-card-link-review/prove-card-destination-retention/`
reproduces this through the actual adapter, planner, library emission, and
composition APIs. A listing classified as feature cards and a project gallery
each retain three image destinations in their design data and lose all three
in the final component tree. The first listing fixture with extra unclassified
paragraphs blocked on an unrelated capacity issue; the final link probe uses
one excerpt per card to isolate destination retention. These are generic
offline fixtures, not a live client-site migration or a visual-fidelity score.

The adapter's suppression of duplicate `Read More` warnings only proves that
a destination arrived in the Design Document. It must not be interpreted as
proof that visitors can use it after composition.

## Required behavior

1. Carry a retained image destination through source-neutral planning and
   composition. Use an explicit paired image-link override such as
   `image_1_href`, retaining the owning image's source-element and repeat-item
   identity. Do not manufacture a separate text button or visitor copy.
2. Produce a standard Vanjaro `link` component around the correct image,
   with anchor semantics, `vj-link` class (`active: false`), and a unique,
   deterministic `attributes.id`. Keep the existing image component, source,
   alt text, classes, style, and ID intact.
3. Preserve unlinked images unchanged. Never create empty or placeholder
   click targets merely because a template has images.
4. Do not nest anchors or silently overwrite an existing multi-content link's
   unrelated destination. Reuse a compatible existing single-image link, or
   surface a clear unsupported/ambiguous case. Applying the same overrides
   repeatedly must not multiply wrappers or shift other link/button targets.
5. Integrate paired destinations with slot validation, overflow checks,
   missing-item bookkeeping, repeat expansion, and page URL rewriting.
   A destination counted as bound must reach a real native link in the output.
6. Allow ordinary safe destinations (including relative paths, query strings,
   fragments, and supported web/contact schemes). Reject script/data and other
   unsupported schemes explicitly, including mixed-case/control-whitespace
   disguises. The planner must report an unsafe source destination as an
   actionable blocking issue, not silently call it retained.
7. Keep the implementation source-neutral, with a cohesive helper instead of
   further expanding the planner/composer monoliths. No new dependency or
   client-specific template/HTML override is justified by this problem.

## Acceptance evidence

The independent root acceptance file is
`artifacts/test_image_link_retention_independent.py`.

Its initial seven-case baseline had six failures and one pass: image-link overrides were not yet
supported, final gallery images have no clickable owner, and future unsafe-link
rejection is absent; the unlinked-image safeguard already passes. Unsupported
overrides are currently ignored by composition, so these security guard failures
are requirements for the new feature, not evidence of a newly exploited URL.

Three additional independent checks cover repeated composition with an existing
link, explicit link removal while retaining the image, and unsafe source-neutral
image evidence becoming a structured planner blocker. Before implementation,
the expanded ten-case baseline has nine failures and one pass. The baseline
gallery check uses the production global/body split to avoid conflating a
separate navigation-template blocker with the image-link defect.

The completed implementation must also demonstrate:

- Exact destination-to-image ownership across multiple cards and a second
  independent layout, not merely matching a set of URLs somewhere in JSON.
- Native structure validation using the repository's block-template validator.
- Missing images and expanded repeats without off-by-one link association.
- Existing link/button numbering and ordinary unlinked output remaining correct.
- Input immutability, stable wrapper IDs, no duplicate IDs or nested anchors.
- Unsafe source URLs yielding explicit planner blockers and unsafe direct
  overrides yielding explicit errors.
- Internal URL rewriting of the generated native links.
- Full offline regressions plus the independent article and capture suites.

No implementation is yet accepted. The diagnostic review finished with PASS
on attempt two; its first attempt produced reproducible measurements but timed
out before completing the report. Root independently reproduced the evidence
and reviewed the probe, report, and final native trees.

The correction task `retain-native-image-destinations` has been dispatched
through the verified Ringer workflow. Its manifest is
`artifacts/agency-native-image-links.json`; it owns the planner/composer
integration, a focused native-link helper, and scoped regression tests. The
authoritative check includes all offline tests, independent article/image-link
checks, and native-template validation of a composed example.

Root did not adopt the review report's proposed dependency from HTML extraction
to final composition. Source-adapter warnings remain extraction evidence;
planning/composition must preserve supported destinations or explicitly block
unrepresentable ones. Keeping those responsibilities separate is part of the
agency tool's architecture requirement.

Test-portal content remains unchanged.

### Independent implementation review — 2026-09-22 (not yet accepted)

The current focused maintained suite passes 186 tests across image-link,
composer, and planner tests. Root reviewed the two adapter-to-composition
fixtures: they compare each source image's destination to its actual final
native link ancestor, not merely to the emitted override values. Asset paths
are supplied locally; these fixtures do not prove upload or live rendering.

The expanded independent suite currently has 14 passing checks and two failures:

- `enumerate_slots` reports an empty `image_1_href` even after composition has
  created the correct clickable owner. Read-back must reflect the native tree.
- An authored single-image link is incorrectly excluded from the pre-existing
  `link_N` numbering, so the following text link's existing `link_2` overrides
  are rejected as overflow. Newly generated wrappers must avoid adding slots
  without renumbering links already authored in a template.

The implementation run is still live. The maintained suite alone is therefore
insufficient acceptance evidence; both independent failures, the full offline
regression check, and composed native-template validation remain acceptance
requirements. No portal mutation or live-fidelity claim follows from this review.

Follow-up review: read-back is now correct, and the original 16 checks pass.
However, the numbering correction identifies generated wrappers solely by
missing/null `content`. That is not a reliable provenance distinction: authored
links without `content` were previously numbered too. Root parameterized the
existing compatibility check across empty, missing, and null content. The
result is 16 passes and two failures (missing and null), confirming the remaining
compatibility defect rather than adding a new feature requirement. Acceptance
must preserve all three prior authoring shapes.

Further review in the same live run found and added the control-plus-space
unsafe URL case (`U+0000`, space, then a script scheme). The initial validator
accepted it; the corrected control/space normalization now rejects it. Root
also independently ran native validation of `validated-example.json`: passed
with zero errors and zero warnings.

A subsequent numbering approach counted every wrapper but skipped generic
link writes to all single-image links. This made unchanged-value idempotence
tests pass while breaking actual later edits. Root strengthened the existing
tests to change the navigation destination after composition and to update an
authored image-link destination through its legacy `link_1_href` key. Current
result: 15 passes, four failures. The three authored content shapes silently
ignore their legacy override, and the post-composition navigation edit is also
ignored. These are compatibility requirements of this feature, not permission
to make existing links read-only. Generated-wrapper provenance must be
distinguished without guessing from ordinary authored content shape.

The retry fixes those four checks, but uses the generated wrapper's ID naming
convention as provenance. An authored link can legitimately have the same
`<image-id>-link` name. Root parameterized the authored-link compatibility test
with that natural ID as well: 19 pass, three fail (all three content shapes for
the image-derived authored ID). Excluding components by an ID pattern is still
guessing; generated ownership needs an explicit durable distinction, while
unmarked authored components retain their existing generic slot behavior.

The explicit marker fixes the ID-collision case, but the current retry also
marks reused authored wrappers. This still renumbers their historical slots
on the next edit. Root extended the existing six authored-owner cases with a
second edit through their original generic keys: 16 pass, six fail. The marker
must describe wrappers newly inserted by this feature, not any authored wrapper
whose destination was updated. Reusing an authored node must keep its original
slot identity across subsequent composition, including legacy destination edits.

## Boundaries and remaining work

### Accepted offline implementation — 2026-09-22

The correction run `vanjaro-agency-translation-retention-20260922T035658Z-p43979`
finished PASS on attempt two, authoritative check exit 0. Attempt one timed out
after 1,800 seconds and lacked the final notes; its partial changes were not
accepted. Root reviewed the retry history, final source changes and maintained
tests, harvested notes, and the actual composed example.

Final behavior uses a dedicated `vj-image-link` marker only on newly created
wrappers. Reused authored wrappers keep their prior generic link slots; normal
IDs and empty/missing/null content are not treated as provenance. Slot read-back
uses the actual native owner. A small stale docstring referring to ID-based
classification was corrected after the worker finished; behavior was unchanged.

Verification:

- All 22 independent image-link cases pass, including subsequent edits to
  authored links, colliding authored ID conventions, image removal without
  destination shifts, URL-safety disguises, and native ownership/read-back.
- Worker full offline check: 2,993 passed, two skipped, 16 integration tests
  deselected; native validator passed.
- Root's wider suite including independent article and capture checks:
  **3,039 passed, two skipped, 16 integration tests deselected in 47.39 seconds**.
- Root reran the native validator on the regenerated example containing the
  creation marker: passed with zero errors and zero warnings.

These results accept the scoped offline implementation, not live renderer/editor
round-trip fidelity. The separate card-action acceptance baseline is deliberately
not included as passing coverage: it still has eight failures and one pass, and
has not been implemented. No portal state changed during this work.

This addresses destinations already attached to image evidence. Linked headings,
inline text links, separate card actions, source-role classification, complete
live migrations, and measured operator-time savings still require their own
evidence. Do not claim that preserving image links preserves every interaction.
