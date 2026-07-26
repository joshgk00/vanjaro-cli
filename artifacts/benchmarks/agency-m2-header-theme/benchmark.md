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
| `responsive_observation_coverage` | 0.4318 (19/44) |
| `template_top1_accuracy` | 0.9167 (22/24) |
| `template_top3_accuracy` | 1.0000 (24/24) |
| `high_confidence_precision` | 0.9000 (9/10) |

## Cases

| Case | Failures |
|---|---:|
| `html-bootstrap-agency` | 5 |
| `html-elementor-studio` | 4 |
| `html-dnn-services` | 1 |
| `figma-auto-layout-saas` | 6 |
| `figma-freeform-nonprofit` | 12 |

## Per-case failures

| Case | Metric | Section | Expected | Actual | Message |
|---|---|---|---|---|---|
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.hero` | `"520px"` | `null` | responsive observation is missing or differs |
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.hero` | `"65% 50%"` | `null` | responsive observation is missing or differs |
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.testimonials` | `true` | `null` | responsive observation is missing or differs |
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.contact` | `"center"` | `null` | responsive observation is missing or differs |
| `html-bootstrap-agency` | `responsive_observation_coverage` | `northstar.contact` | `"100%"` | `null` | responsive observation is missing or differs |
| `html-elementor-studio` | `responsive_observation_coverage` | `juniper.hero` | `"left"` | `null` | responsive observation is missing or differs |
| `html-elementor-studio` | `responsive_observation_coverage` | `juniper.hero` | `"600px"` | `null` | responsive observation is missing or differs |
| `html-elementor-studio` | `responsive_observation_coverage` | `juniper.testimonials` | `true` | `null` | responsive observation is missing or differs |
| `html-elementor-studio` | `responsive_observation_coverage` | `juniper.contact` | `"left"` | `null` | responsive observation is missing or differs |
| `html-dnn-services` | `responsive_observation_coverage` | `harbor.cta` | `"100%"` | `null` | responsive observation is missing or differs |
| `figma-auto-layout-saas` | `responsive_observation_coverage` | `orbit.hero` | `"bottom"` | `null` | responsive observation is missing or differs |
| `figma-auto-layout-saas` | `responsive_observation_coverage` | `orbit.logos` | `true` | `null` | responsive observation is missing or differs |
| `figma-auto-layout-saas` | `responsive_observation_coverage` | `orbit.logos` | `2` | `1` | responsive observation is missing or differs |
| `figma-auto-layout-saas` | `responsive_observation_coverage` | `orbit.features` | `2` | `null` | responsive observation is missing or differs |
| `figma-auto-layout-saas` | `responsive_observation_coverage` | `orbit.testimonials` | `1` | `null` | responsive observation is missing or differs |
| `figma-auto-layout-saas` | `responsive_observation_coverage` | `orbit.cta` | `"100%"` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.hero` | `"top"` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.hero` | `1` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.stats` | `1` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.programs` | `1` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.programs` | `false` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.story` | `false` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.story` | `"top"` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.cta` | `"100%"` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `responsive_observation_coverage` | `riverkind.cta` | `"vertical"` | `null` | responsive observation is missing or differs |
| `figma-freeform-nonprofit` | `template_top1_accuracy` | `riverkind.hero` | `["split-hero", "split-media-reverse"]` | `"centered-hero"` | selected template is not an acceptable annotated match |
| `figma-freeform-nonprofit` | `template_top1_accuracy` | `riverkind.stats` | `["stats-band-3up"]` | `"stats-grid-4up"` | selected template is not an acceptable annotated match |
| `figma-freeform-nonprofit` | `high_confidence_precision` | `riverkind.stats` | `["stats-band-3up"]` | `"stats-grid-4up"` | high-confidence selection is incorrect |
