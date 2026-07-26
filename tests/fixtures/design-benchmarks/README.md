# Design Translation Benchmark Corpus v1

This directory is the committed, offline evidence set for Design Translation v2.
All source fixtures and visual references are synthetic and contain no customer
content, credentials, analytics identifiers, or production asset URLs.

## Contract

`manifest.json` discovers cases and canonical viewports. Each case points to one
source fixture, one annotation document, and desktop/mobile SVG references.
`annotation.schema.json` defines the expected extraction result without coupling
the corpus to a particular adapter implementation.

Annotations measure:

- section boundaries and order;
- semantic roles;
- visitor-facing content retention;
- repeat-group item/field associations;
- asset-to-element associations;
- responsive-observation coverage; and
- acceptable template matches, including equivalent maintainable alternatives.

IDs are stable corpus contracts. A binding value is always a content-element ID,
never a positional index. `acceptable_templates[0]` is the preferred match; later
entries are equally acceptable alternatives only when explicitly listed.

## Cases

| Case | Source profile | Auto-layout | Sections | Repeat items |
|---|---|---:|---:|---:|
| `html-bootstrap-agency` | semantic Bootstrap-like HTML | n/a | 5 | 9 |
| `html-elementor-studio` | nested page-builder HTML | n/a | 5 | 9 |
| `html-dnn-services` | DNN pane/module HTML | n/a | 5 | 8 |
| `figma-auto-layout-saas` | Figma node tree | yes | 5 | 8 |
| `figma-freeform-nonprofit` | Figma node tree | no | 5 | 8 |

Total: 25 annotated sections and 42 annotated repeat items.

## Baselines

`baseline-score-report.json` records the pre-v2 legacy capability baseline. It
distinguishes measured values from unavailable metrics so a missing Figma section
adapter cannot accidentally appear as a successful score. Future runners should
write per-case predictions and compute metrics against the annotation documents.
A regression greater than `0.02` from an accepted baseline is the CI failure gate.

The Keys to Success paths in the report are evidence references only. The files
are not copied or treated as portable benchmark inputs.

