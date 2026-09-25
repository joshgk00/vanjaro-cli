# Design Translation Offline Benchmark

Corpus: **Vanjaro Design Translation Offline Corpus**

## Aggregate metrics

| Metric | Result |
|---|---:|
| `section_boundary_precision` | 1.0000 (25/25) |
| `section_boundary_recall` | 1.0000 (25/25) |
| `semantic_role_accuracy` | 1.0000 (25/25) |
| `visitor_content_retention` | 1.0000 (127/127) |
| `group_field_association_accuracy` | 1.0000 (79/79) |
| `asset_association_accuracy` | 1.0000 (15/15) |
| `responsive_observation_coverage` | 0.8864 (39/44) |
| `template_top1_accuracy` | 0.9200 (23/25) |
| `template_top3_accuracy` | 1.0000 (25/25) |
| `high_confidence_precision` | 0.9474 (18/19) |

## Cases

| Case | Failures |
|---|---:|
| `html-bootstrap-agency` | 3 |
| `html-elementor-studio` | 2 |
| `html-dnn-services` | 0 |
| `figma-auto-layout-saas` | 0 |
| `figma-freeform-nonprofit` | 3 |

## Per-case failures

| Case | Metric | Section | Expected | Actual | Message |
|---|---|---|---|---|---|
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.hero` | `"520px"` | `null` | responsive observation is missing or differs |
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.hero` | `"65% 50%"` | `null` | responsive observation is missing or differs |
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.testimonials` | `true` | `null` | responsive observation is missing or differs |
| `html-elementor-studio` | `responsive_observation_coverage` | `juniper.hero` | `"600px"` | `null` | responsive observation is missing or differs |
| `html-elementor-studio` | `responsive_observation_coverage` | `juniper.testimonials` | `true` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `template_top1_accuracy` | `riverkind.hero` | `["split-hero", "split-media-reverse"]` | `"centered-hero"` | selected template is not an acceptable annotated match |
| `figma-freeform-nonprofit` | `template_top1_accuracy` | `riverkind.stats` | `["stats-band-3up"]` | `"stats-grid-4up"` | selected template is not an acceptable annotated match |
| `figma-freeform-nonprofit` | `high_confidence_precision` | `riverkind.stats` | `["stats-band-3up"]` | `"stats-grid-4up"` | high-confidence selection is incorrect |
