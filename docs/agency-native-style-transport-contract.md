# Preserve native styling decisions in generated blocks

## Executed evidence

`artifacts/test_native_style_transport_independent.py` proves that an accepted
TEXT_ALIGN right decision targeting `text-end` disappears during actual library
composition. It is not a scoped-CSS decision, so the scoped-CSS transport fix
does not cover it. Inspection also found that theme, agency-utility and template
modifier targets are not emitted/applied by the project library path.

The installed Basic theme inspection confirms `text-end` is available. The
separate target-utility correction now prevents selecting unavailable image-fit
classes by default. Selecting a supported native mechanism and applying it are
two distinct requirements; both must hold.

## Implementation requirements

- Define structured, validated transport for applicable native decisions. Keep
  source property/value, chosen layer, target and breakpoint together so the
  consumer can validate meaning rather than trust an arbitrary class string.
- Apply supported section-level classes to the owning native component while
  preserving unrelated template classes, component types and editability.
  Resolve contradictory classes in the same utility family deliberately.
- Preserve theme-slot reuse and known agency utility mappings. Do not turn
  token identifiers, CSS variables or modifier expressions into class names
  merely because they are stored in a decision's target field.
- Treat template capability labels as declarations, not implementations. A
  modifier needs a real supported application rule; unresolved modifiers must
  be reported explicitly rather than silently dropped or counted as applied.
- Target media-only properties at the appropriate image/media component using
  existing template ownership metadata. Do not apply object-fit to a section
  div and count that as correct reproduction.
- Keep per-section/project isolation, responsive scope, deterministic hashes,
  reviewed payloads, legacy plans and the now-hardened CSS boundary intact.
- Validate serialized inputs again before composition. Reject unsupported or
  ambiguous action shapes and unsafe targets before portal mutation.
- Do not invent responsive transition thresholds from capture sample widths.
  For responsive native utilities, preserve source-backed conditions or clearly
  report an unresolved policy/evidence gap. Two contradictory unconditional
  classes are not a responsive implementation.

## Acceptance

The immutable root native-alignment regression must pass. Maintained tests
must exercise real planner -> library emitter -> block/page composition with
native alignment, theme background/text classes, existing class conflicts,
multiple independent sections, unsupported modifiers and unsafe serialized
targets. Assert generated DOM classes and actual effective behavior, not only
new report fields. Include page/block hash changes and unchanged repeat builds.

Browser verification must load actual target utility CSS (not hand-written
replacement rules) and compare computed styles on the owning nodes. Retain
separate evidence for remaining unsupported decisions; do not claim all native
or responsive styling is applied from the single alignment case.

## Scheduling

Wait for the custom-block registration worker to become terminal before
granting overlapping planner/block-library/style-transport ownership. Assign
explicit files and tests through verified Ringer. No portal creation, mutation,
publication, source fixture substitutions or threshold weakening is authorized
by this implementation contract.
