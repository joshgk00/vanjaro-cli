# Article-card semantic retention

## Purpose

Keep article categories, excerpts, and bylines in distinct, native editable
fields. A card must not need manual reconstruction merely because its category
or byline was counted as another body paragraph.

This is an HTML adapter correction, not a planner scoring adjustment or an
increase in template capacity. Figma and image evidence continue through the
same source-neutral planning contract.

## Evidence and implementation boundary

The current-code retention review reproduced the saved KTS and EDCA planning
summaries. KTS has five blocked body sections and editable coverage 0.3837;
EDCA has no blocked body sections and coverage 0.6923. These are planning
metrics, not visual fidelity or measured time savings.

KTS's article cards contain category, excerpt, and author/date values all
recorded as `body`. The existing `Cards/blog-post-cards-4up` template already
has separate `item.tag`, `item.body`, and `item.meta` native slots. Increasing
body slots would preserve text at the expense of its intended editing position.

The saved KTS document does not contain sufficient explicit semantic evidence
to safely relabel these fields automatically. Its source uses styling classes
for some of these values. This implementation must not recognize a particular
site ID, custom class prefix, or text value to make that saved result pass.
Current saved project plans will not be rewritten by this task.

## Requirements

1. Recognize explicit category/tag and article metadata evidence in HTML cards,
   including supported exact class tokens, `rel=tag`, and relevant semantic
   attributes. Do not infer meaning from paragraph position, short text,
   `text-muted`, or arbitrary substring matches.
2. Classify an entire paragraph only when its evidence applies to its complete
   owned content. An excerpt containing a category link remains an excerpt.
3. Keep every observed value in document order and in its original card.
   Multiple values for a field remain multiple values; no concatenation or
   truncation may hide a template capacity mismatch.
4. Preserve existing date extraction and ordinary feature/gallery-card
   behavior unless stronger explicit article semantics justify a difference.
5. Use the existing native tag, body, and metadata slots. Preserve planner
   constraints and all quality thresholds.
6. Isolate classification in a focused helper and keep the ownership module's
   integration small. Add no dependency.

## Acceptance and verification

- Root-owned `artifacts/test_article_semantics_independent.py` covers explicit
  semantics, card ownership, ambiguous styling, mixed descendant content, and
  multiple metadata values. Initial three-case baseline: two failures for
  explicit semantic extraction, one passing ambiguity safeguard.
- Maintained tests must exercise two structurally different generic HTML
  fixtures through the actual adapter, planner, and native component composition.
  Assert the exact final slot values, not only scores or binding counts.
- Ambiguous multi-paragraph content must remain visible and fail capacity
  checks when the chosen template cannot hold it.
- Run the full offline suite and inspect the resulting code and assertions.
  A worker's prose or a passing extraction-only test is insufficient evidence
  of correct composed output.

## Verification record

The implementation task `retain-article-field-semantics` completed with PASS
on its first attempt. Root review verified the focused classifier and the
delegation from HTML ownership; templates and planner thresholds were unchanged.

Root's expanded verification passed **2,953 tests**, with two skips and 16
live-integration tests deselected. It included the full offline suite, the
capture acceptance checks, and nine independent article-semantic checks.
The latter verify exact values in the final native component tree for both
class-marked and microdata-marked fixtures, plus the ambiguous overflow blocker.
This is offline composition evidence, not browser rendering or a live rebuild.

Before the fix, the planner blocked these over-capacity cards. It did not
silently truncate them into successful builds. The original worker's notes
describe truncation incorrectly; the unchanged planner constraints and the
independent ambiguous-overflow test are authoritative.

Review also found that the new maintained end-to-end tests checked the override
dictionary rather than exact values in the final component tree. Two additional
root mutation guards deliberately corrupt final text nodes; both initially
failed because the maintained checks did not detect the corruption. The narrow
test-hardening task `assert-composed-article-content` fixed that gap and passed
on its first attempt. Root reviewed actual-tree assertions, exact excerpts,
conflicting-marker coverage, and the maintained overflow regression.

Final root verification: **2,957 passed, two skipped, 16 deselected** in 46.21
seconds, including both deliberate-corruption guards and the independent capture
acceptance tests. The focused article/ownership run passed all 33 cases.
`git diff --check` passed for the implementation, tests, and this contract.
This closes this bounded semantic-retention change, not the overall agency
goal or any live fidelity requirement. The artifact for both tasks is
`vanjaro-agency-translation-retention`.

## Remaining accuracy work

This change does not prove visual parity, live migration quality, Figma/image
accuracy, or reduced operator effort. Those require representative projects and
current build/capture evidence.

Repeated-card link destinations also need separate investigation: the current
ownership adapter extracts heading/paragraph text and skips links inside
already-owned repeated nodes in its general link sweep. Correct text placement
alone must not be presented as proof that all original interactions survive.
Any follow-up must verify source destination ownership through final native
components without silently converting a linked category or title to plain text.
