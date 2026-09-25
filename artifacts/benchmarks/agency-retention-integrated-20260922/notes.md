# Agency retention benchmark refresh — 2026-09-22

## Ringer routing decision

Classified inline, not Ringer. This is a single bounded operation — run one
deterministic offline benchmark command (no model calls, no conversational
harness, no edit loop), read its produced JSON/Markdown, and write this one
notes.md file. Falls under the Ringer skill's stated inline exceptions
(reading/running a command once; authoring one file straight from context),
not the "calls a model" / "probe or eval harness" / "edit→test loop"
triggers that require a manifest.

## Exact command run

```
cd /mnt/c/Code/vanjaro-cli && /mnt/c/Users/Josh/AppData/Local/Programs/Python/Python311/python.exe -c 'from vanjaro_cli.cli import main; main()' migrate benchmark-all --output artifacts/benchmarks/agency-retention-integrated-20260922 --json
```

## Exit code

`0`

## Raw stdout (JSON)

```json
{"status": "ok", "passed": true, "corpora": [{"corpus": "design-benchmarks", "passed": true, "cases": ["html-bootstrap-agency", "html-elementor-studio", "html-dnn-services", "figma-auto-layout-saas", "figma-freeform-nonprofit"], "json_report": "artifacts\\benchmarks\\agency-retention-integrated-20260922\\design-benchmarks\\benchmark.json", "human_report": "artifacts\\benchmarks\\agency-retention-integrated-20260922\\design-benchmarks\\benchmark.md"}, {"corpus": "design-image-benchmarks", "passed": true, "cases": ["image-assisted-agency"], "json_report": "artifacts\\benchmarks\\agency-retention-integrated-20260922\\design-image-benchmarks\\benchmark.json", "human_report": "artifacts\\benchmarks\\agency-retention-integrated-20260922\\design-image-benchmarks\\benchmark.md"}], "combined_json": "artifacts\\benchmarks\\agency-retention-integrated-20260922\\combined.json", "combined_md": "artifacts\\benchmarks\\agency-retention-integrated-20260922\\combined.md"}
```

Overall: `status: ok`, `passed: true`. Both corpora (`design-benchmarks`,
`design-image-benchmarks`) passed with `regression_failure_count: 0` and
`threshold_failure_count: 0`.

## Measured results (exact numerators/denominators, from `combined.json`)

| Metric | design-benchmarks | design-image-benchmarks |
|---|---|---|
| section_boundary_precision | 25/25 = 1.0 | 3/3 = 1.0 |
| section_boundary_recall | 25/25 = 1.0 | 3/3 = 1.0 |
| semantic_role_accuracy | 25/25 = 1.0 | 3/3 = 1.0 |
| visitor_content_retention | 127/127 = 1.0 | 11/11 = 1.0 |
| group_field_association_accuracy | 79/79 = 1.0 | 3/3 = 1.0 |
| asset_association_accuracy | 15/15 = 1.0 | 0/0 = **not_measurable** |
| responsive_observation_coverage | 39/44 = 0.886364 | 6/6 = 1.0 |
| template_top1_accuracy | 23/25 = 0.92 | 2/2 = 1.0 |
| template_top3_accuracy | 25/25 = 1.0 | 2/2 = 1.0 |
| high_confidence_precision | 18/19 = 0.947368 | 2/2 = 1.0 |

**repeat_ownership**: not present anywhere in this run's schema
(`combined.json` rows, per-corpus `aggregate` blocks, or per-case blocks).
Neither corpus (`design-benchmarks`, `design-image-benchmarks`) emits this
metric — schema_version is `1.0` in both the combined and per-corpus JSON,
and it does not define a `repeat_ownership` key. Reporting as **unavailable**
per instructions rather than inferring or fabricating a value.

## Regression comparison (from design-benchmarks `regressions` array; the
image corpus reports an empty `regressions: []`)

All 7 tracked regression metrics for `design-benchmarks` show `"failed":
false`, current values at or above baseline:

- section_boundary_precision: baseline 1.0 → current 1.0 (delta 0.0)
- section_boundary_recall: baseline 0.9333 → current 1.0 (delta +0.0667)
- semantic_role_accuracy: baseline 0.2857 → current 1.0 (delta +0.7143)
- visitor_content_retention: baseline 0.8293 → current 1.0 (delta +0.1707)
- group_field_association_accuracy: baseline null → current 1.0
  (`comparable: false`, reason "baseline or current metric is not
  measurable")
- asset_association_accuracy: baseline 0.8889 → current 1.0 (delta +0.1111)
- responsive_observation_coverage: baseline 0.0 → current 0.807692*
  (delta +0.807692)

  \* Note: this regression-array value (0.807692) differs from the
  aggregate cell value in `combined.json`/`benchmark.json`
  (39/44 = 0.886364). Both are pulled verbatim from the same produced
  `design-benchmarks/benchmark.json` — reporting both as-measured rather
  than reconciling, since this task does not fix or normalize benchmark
  output.

`threshold_failures: []` in both corpora — no metric crossed a configured
pass/fail threshold.

## New failures vs. prior `artifacts/benchmarks/combined`

**None.** Byte-for-byte diff of every produced file against the pre-existing
`artifacts/benchmarks/combined/` snapshot:

- `combined.json` — identical
- `combined.md` — identical
- `design-benchmarks/benchmark.json` — identical
- `design-benchmarks/benchmark.md` — identical
- `design-image-benchmarks/benchmark.json` — identical
- `design-image-benchmarks/benchmark.md` — identical

No thresholds were changed to force this match — this is the actual output
of the unmodified benchmark-all pipeline run against the same committed
offline fixtures, landing in a new output directory as instructed. History
in `artifacts/benchmarks/combined/` was not overwritten.

## Known imperfections surfaced in `design-benchmarks/benchmark.json`
`failures[]` (corpus still passes; these are below-threshold, not
regressions)

- `html-bootstrap-agency`: 3 missing/differing responsive observations
  (`northstar.hero` mobile min-height + background-position,
  `northstar.testimonials` mobile carousel flag).
- `html-elementor-studio`: 2 missing/differing responsive observations
  (`juniper.hero` mobile min-height, `juniper.testimonials` mobile
  carousel flag).
- `figma-freeform-nonprofit`: template match misses —
  `riverkind.hero` selected `centered-hero`, expected one of
  `split-hero`/`split-media-reverse`; `riverkind.stats` selected
  `stats-grid-4up` twice (once as top1 miss, once as a high-confidence
  precision miss), expected `stats-band-3up`.
- `html-dnn-services` and `figma-auto-layout-saas`: zero failures.

## Gaps and caveats

- **Fixtures are not representative of live client trials.** All cases run
  against committed offline fixture corpora
  (`design-benchmarks` = 5 cases: 3 live-HTML snapshots + 2 Figma exports;
  `design-image-benchmarks` = 1 case). No live network fetch, no live
  Vanjaro/DNN portal, no live Figma API call occurred in this run — a real
  client site will exercise markup/asset/layout variety this fixture set
  does not cover.
- **Image corpus is small.** `design-image-benchmarks` has exactly 1 case
  (`image-assisted-agency`), backing every image-corpus metric off a single
  fixture. A single-case corpus cannot show variance or catch regressions
  that only manifest on a second/different image sample.
  `asset_association_accuracy` is `not_measurable` (0/0) for this corpus —
  the fixture has no asset-association assertions to score.
- `repeat_ownership` is unavailable in this run's output schema (see above)
  — cannot report a numerator/denominator for a metric the pipeline does
  not currently emit.
- This task did not modify source, tests, thresholds, or fixtures. The
  benchmark passed as run; per instructions, no fix would have been applied
  even if it had failed — this run happened to reproduce the prior
  `combined` snapshot exactly.

## Deliverables

- `artifacts/benchmarks/agency-retention-integrated-20260922/combined.json`
- `artifacts/benchmarks/agency-retention-integrated-20260922/combined.md`
- `artifacts/benchmarks/agency-retention-integrated-20260922/design-benchmarks/benchmark.json`
- `artifacts/benchmarks/agency-retention-integrated-20260922/design-benchmarks/benchmark.md`
- `artifacts/benchmarks/agency-retention-integrated-20260922/design-image-benchmarks/benchmark.json`
- `artifacts/benchmarks/agency-retention-integrated-20260922/design-image-benchmarks/benchmark.md`
- `artifacts/benchmarks/agency-retention-integrated-20260922/notes.md` (this file)
