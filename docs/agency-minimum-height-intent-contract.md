# Minimum-height translation contract

## Confirmed gap

The real-browser responsive probe captures authored hero minimum heights of
720px (desktop), 620px (tablet), and 520px/560px (two mobile variants).
The typed Design Document preserves all of them as observed evidence, but
`style_translation._measurement_only_decision` discards all rendered MIN_HEIGHT
values before generating output. The current test explicitly codifies that
policy; it must change deliberately, not be silently deleted.

## Policy correction

Treat a meaningful nondefault `min-height` as a reproducible sizing constraint,
not as the resulting measured HEIGHT of an element. The CSS sizing standard
defines minimum-size properties as non-inherited constraints with initial value
auto and computed length/percentage values:
[CSS Box Sizing Level 3](https://www.w3.org/TR/css-sizing-3/#min-size-properties).
This supports distinguishing the property from a measured box height; it does
not establish the source selector or original author declaration from computed
data alone. Preserve rendered provenance and do not claim author-level proof.

Required behavior:

- Retain supported, safe nondefault minimum-height values per observed viewport.
- Continue preferring native/template/agency mechanisms over scoped CSS.
- Exclude default auto/zero values from unnecessary scoped declarations.
- Keep ordinary rendered WIDTH/HEIGHT and incidental positioning measurements
  measurement-only. Do not widen the entire dimensional property allowlist.
- Keep CSS safety checks, scoped-rule budgets and explicit source provenance.
- Preserve non-rendered declared values and existing palette/utility precedence.
- Prove actual generated mobile CSS changes from 520px to 560px when only the
  source mobile CSS changes, with desktop/tablet values retained.
- Update the historical browser probe's hardcoded explanatory text: its notes
  currently always assert minimum height is dropped, independent of current
  measured output. Report actual decisions dynamically after this correction.

## Acceptance and scheduling

Root test `artifacts/test_min_height_intent_independent.py` distinguishes four
meaningful constraint values from three default values and measured width/height.
Full acceptance also needs a fresh real-browser run, typed evidence checks,
actual plan/library CSS assertions and the complete offline suite.

Do not begin changing the probe outputs while the nested-footer worker owns
them. The pure translator and maintained style tests may run independently with
disjoint ownership. Dispatch the diagnostic script update and shared browser
validation only after the footer worker is terminal.
No fixture thresholds or annotation values may be changed to make this pass.
This contract does not broaden permission to publish or mutate a portal.

## Translator verification result

The implementation now retains nondefault rendered MIN_HEIGHT and filters
auto/zero while leaving rendered WIDTH/HEIGHT measurement-only. Root and
maintained translator checks pass: 42 tests. The implementation run's checks
passed but its handoff failed twice because notes were written to the repository
root instead of the task directory. A subsequent read-only verified run
`vanjaro-agency-translation-retention-20260922T065014Z-p139857` passed on its
first attempt and harvested the report at the correct path.

This accepts only the translator correction. Root separately reproduced that
accepted scoped styles are lost during real library composition; see
`agency-composed-style-retention-contract.md`. Planner declarations are not
proof of effective CSS in generated blocks. The output correction is now
running alongside the semantic-article fix in
`artifacts/agency-structural-output-fixes.json`, with disjoint ownership.
