# Agency style configuration through the project workflow

Status: confirmed incomplete; do not claim direct-call transport tests prove
normal project workflow support.

## Current evidence

Root inspection on 2026-09-22 found that `run_project_planning` calls
`plan_design_document` without agency style configuration and writes its
library artifact through `serialize_library_plan`. That serializer cannot
receive the mapping accepted by `emit_library_plan`. Likewise,
`preview_project_library` and `register_project_library` call the composer
without agency utilities. The direct-call tests pass the mapping manually at
each boundary, which is not how these project stages currently operate.

`artifacts/test_agency_style_serialization_independent.py` reproduces a
concrete silent loss: a plan accepts `order:2 -> order-2`, serialization
returns success, but its library output omits that class. Root result:
1 failed, exit 1. No portal calls or mutations were involved.

Root also reproduced a semantic validation gap in
`artifacts/test_native_class_semantics_independent.py`: 2 failed, exit 1.
`validate_native_class_actions` accepts `source_value=right` with `text-start`,
and accepts `order:2` with `order-1` when both order classes are declared.
Family membership validation catches unknown classes but not an incorrect
class within the family. This is not evidence of script execution; it is an
accuracy/audit mismatch at the serialized-input boundary. Preserve legitimate
alias normalization while validating exact source-value-to-action semantics.

### Exact native action correction verified

Run `vanjaro-agency-translation-retention-20260922T082406Z-p230597`
completed on attempt 1, exit 0: 3 root checks and 53 maintained checks.
Root reviewed the shared validation helper, canonical translator-table reuse,
normalization and new tests, then independently reran the semantic/native root
checks plus the two maintained native-style test files: 41 passed, exit 0.
The report builder and serialized boundary both reject same-family targets that
contradict their source values. No existing tests were changed to absorb this.

This closes the two semantic mismatch regressions, not the agency workflow
integration requirement. Exact theme color-to-slot verification still requires
trusted palette context absent from the validator. Agency configuration through
normal project stages and the serialization-loss regression remain open.
Full combined integration is pending the independently owned responsive worker.

## Required outcome

An operator can select reviewed, versioned agency styling once and have the
same configuration drive planning, previews, composition and registration.
Supported agency styling must actually work in the project CLI. An error-only
fix to serialization is necessary protection but is not completion of this
outcome. Classes without an installed, verified definition are not reusable
styling merely because their names are syntactically valid.

Additional registry inspection: `agency_library/models.py::ModifierContract`
contains only `modifier_id` and `contract_sha256`. The published modifier
payload at `artifacts/agency-packs/clicks-and-mortars/modifiers/1.0.0.json`
lists these identities/hashes; it does not contain executable actions or
property/value-to-class definitions. Do not treat that registry payload as an
existing runnable modifier engine, or overwrite it in place to introduce one.
The next contract must distinguish compatibility identity from executable
behavior and verify both against actual generated output.

## Implementation requirements

1. Locate the existing agency-pack/configuration contract and use one explicit,
   typed, project-scoped source of truth. Do not introduce competing unversioned
   mapping files or process-global mutable defaults. Preserve historical pack
   digests and migrate versioned artifacts explicitly if the contract changes.
2. Include mapping and supported target capabilities in the relevant plan,
   preview and approval fingerprints. A changed mapping, pack or target must
   invalidate old receipts, not silently reuse a reviewed output.
3. Resolve trusted configuration at orchestration edges; keep planner and
   composer pure. Pass the same resolved configuration through serialization,
   preview and registration, including resumed stages and hidden-draft page
   assembly. Never trust an arbitrary serialized class-family declaration as
   its own authorization.
4. Validate the exact property/value-to-class mapping, not merely membership
   in any class family. Remove contradictory defaults only on the owning
   component; preserve unrelated classes and content. Keep clients isolated.
5. Missing or mismatched mapping context must be actionable. A library artifact
   must not return success while silently dropping a previously accepted
   agency decision. Report unsupported modifiers and responsive/media scopes
   separately; do not present these as applied classes.
6. Retain standard platform/theme behavior for projects without custom agency
   mappings. Do not replace built-in components with opaque HTML to pass tests.

## Acceptance and tests

- Root serialization regression passes without silently discarding the class.
- A maintained real CLI/project-stage test configures a known agency mapping,
  plans and serializes it, previews and builds using fake portal responses,
  and asserts the generated owning node has the expected class and content.
- Repeat/resume performs no duplicate writes and produces the same hashes.
- Missing context, incorrect property/value mapping, tampered class family,
  changed configuration and stale approval each fail before a portal write.
- Two independently configured client workspaces do not influence each other.
- Default projects and legacy supported artifacts retain their tested behavior.
- Actual browser computed styling with the declared stylesheet proves the
  class has its intended effect; class-name presence alone is insufficient.
- Run focused workflow, approval, block-library and native-style tests, then
  the integrated non-live suite after all owners finish. No live registration
  or publication is authorized by this offline implementation contract.

## Scheduling

The active generated-browser proof reads planner/composer production files.
Do not edit that measured path until its current run finishes. Asset rejection
work owns a separate upload path and can proceed independently. Once browser
evidence is harvested, use a verified implementation manifest with explicit
ownership and the root regression first in the check. Preserve the historical
browser evidence and rerun it after integration.

## Serialization prerequisite in progress (2026-09-22)

Root freshly reran the original serialization-loss regression: 1 failed.
The additional `artifacts/test_agency_serialization_context_independent.py`
defines 8 cases across section/element owners: explicit valid context must
survive, while absent, empty or changed mappings must fail explicitly. Current
baseline: all 8 fail because the serializer lacks the context argument.

`artifacts/agency-serialization-context-fix.json` assigns the pure serializer
prerequisite only. It does not close project configuration, registry resolution,
approval fingerprints, preview/register/resume forwarding or stylesheet proof.
Its automated preflight exited before tests because the new maintained test
file did not exist yet; that is not behavioral baseline evidence. The separate
root executions above provide the actual failing behavioral baseline. Final
acceptance must execute both independent checks and maintained tests after
implementation, then inspect the actual patch and returned run status.

Current orchestration edges to connect after the prerequisite:
`project_planning.run_project_planning`,
`project_build.preview_project_library_stage`, and
`project_build.register_project_library_stage`. The existing agency registry
resolves versioned template/modifier identities and digests; executable mapping
definitions are not present. The current project theme stage is explicitly
read-only planning, so it cannot be cited as proof of stylesheet installation.
Any implementation must establish actual styling support rather than assuming
that selecting an agency pack installs its classes.

### Serialization run review and responsive follow-up

Run `vanjaro-agency-translation-retention-20260922T101404Z-p350617`
passed on attempt 1, exit 0, with 103 checks and harvested task-local notes.
Root reviewed the serializer's explicit mapping argument and both section and
element emission guards. Independent review exposed successive false-negative
cases in deciding whether a validated later action superseded an agency choice:
an invalid later claim, then an earlier surviving action. Those cases were
corrected and 25 combined root/maintained cases passed. A full non-live run
during that implementation returned 3,307 passed, 2 skipped, 16 deselected.

The final scope review added a responsive-only echo of an earlier valid action.
It cannot apply as a base native action, yet its later position was incorrectly
used to mask a lost base agency choice. That new regression failed after the
recorded PASS; the run is not sufficient to accept the boundary as complete.
`artifacts/agency-serialization-scope-fix.json` now owns this focused correction.
Its preflight actually executed the behavioral failure (103 passed, 1 failed),
in addition to noting the not-yet-created task notes. No full workflow or
browser-computed styling claim follows from these serialization tests.

### Serialization boundary correction accepted

Run `vanjaro-agency-translation-retention-20260922T102723Z-p365621`
finished on attempt 1 with status PASS and check exit 0 (106 checks). Root
read the harvested notes and reviewed the applicability guard: a scoped
decision cannot be credited as the origin of a surviving unscoped native
action. Maintained tests cover the responsive echo and legitimate later
supersession; the nonmutation test now compares against a pre-call snapshot.
Root independently reran the complete focused acceptance command after the
worker stopped: 106 passed in 1.50 seconds. This accepts explicit-context
serialization and its loss detection, not W1-W4 below. The latest full-suite
result above predates this final scope correction; do not label it a fresh
post-correction integration run.

## Ordered workflow implementation tasks

These are dependent tasks, not independent parallel lanes. Do not dispatch
overlapping planner/build/registry ownership concurrently. Each implementation
manifest must name its exact file ownership and executable checks.

### W1: Versioned executable style contract and resolver

Extend the agency-pack contract through an explicitly versioned payload rather
than modifying historical modifier identities in place. Separate a mapping's
property/value/class semantics from evidence that the class is implemented.
Resolve at the orchestration edge into an immutable typed context carrying
pack identity, canonical content digest, mappings and target support evidence.
Keep existing packs without executable styles compatible. Never infer class
support from a class name, a modifier hash, or the mapping's own declaration.

Acceptance: exact-version resolution, payload digest verification, path escape
rejection, malformed or contradictory mapping rejection, deterministic context
serialization, and two clients resolving independently. Historical pack hashes
must remain unchanged. Unsupported target implementations must produce an
actionable review/blocking result before a portal write. Tests use temporary
registries; no production pack upgrade is authorized by test execution.

Primary integration locations: `agency_library/models.py`,
`agency_library/registry.py`, a focused orchestration resolver, and the relevant
versioned schemas. Maintain the existing registry's integrity checks.

### W2: Carry one resolved context through the project stages

Resolve configuration for `project_planning.run_project_planning`; pass it into
the pure planner and serializer. Resolve and verify the same identity for
`project_build.preview_project_library_stage` and
`project_build.register_project_library_stage`, then forward it through the
portal library API to composition. Do not add a process-global mapping cache.
Ensure asset rewriting and later page assembly retain the resulting actions.

Acceptance: a maintained CLI/stage test starts with a versioned test pack and
source evidence, runs the normal planning and fake-portal build path, and
asserts the exact owning component's class, content and destination. Test both
section and bound-element actions; unrelated siblings must remain unchanged.
Preview performs no POST or workspace writes. Repeated/resumed execution must
not duplicate portal writes. Default projects continue to work without opting
into custom styles. Direct helper tests alone do not satisfy this task.

### W3: Approval, target and resume invalidation

Bind resolved executable configuration and target support evidence into stage
inputs and build-review receipts, not only the pack name/version. The current
`StageEngine._input_fingerprint` and build-review manifest projection already
include `manifest.agency_pack`; they do not independently prove the external
payload still matches it. Revalidate immutable payloads before reuse or action.
Include pack upgrade/replan behavior in the integration review.

Acceptance: change mapping content, pack digest, stylesheet support evidence,
target portal or template after review, and assert rejection before a mutation.
An unchanged project resumes deterministically. Tampered external registry
bytes must not pass because a completed stage or old receipt still exists.
Keep credentials and filesystem-specific incidental values out of artifacts.

### W4: Rendered styling proof and operator handoff

Prove configured classes with actual computed styles against their declared
implementation, including a template-default collision and responsive widths.
Record target/source hashes, exact owner selection and unsupported cases.
Exercise the same emitted artifacts from W2, not a hand-authored substitute.
The existing theme-plan stage is read-only and is not installation evidence.

Acceptance: real browser measurements confirm the intended styles on section
and element owners with unaffected siblings, and a missing/changed stylesheet
fails the verification. Report any required installation as an explicit step
with its own authority; never silently mutate a theme to make the proof pass.
Run the integrated non-live suite after all owners finish. Representative
agency project fidelity and hands-on time measurements remain the larger
goal's acceptance requirements, even when W1-W4 pass.

### W2 delivery-path evidence to preserve

Root inspected the existing registration and page-composition paths. Custom
block registration deliberately sends empty `Html` and `Css`: a nonempty
`Css` value selects Vanjaro's global-block storage branch. Do not attach the
new agency stylesheet to that field. Existing editor/page styles travel in
`StyleJSON`, and page composition rewrites ID selectors while leaving class
selectors unchanged. If agency definitions are delivered through this path,
test their actual rule/class relationship and isolation across pack versions;
do not assume page namespacing isolates arbitrary utility classes.

The low-level theme CLI also exposes portal-wide custom CSS, but that is not
part of the current read-only project theme plan. Wiring it in would require
explicit reviewed writes, preservation of unrelated portal CSS and read-back
verification. W2 should choose and document one supported delivery path,
include its actual styles in previews/receipts, and retain W4 browser proof.
No live endpoint was called during this inspection.

### W1 initial run reviewed, not yet accepted

Run `vanjaro-agency-translation-retention-20260922T103504Z-p373384`
passed on attempt 1: 6 root checks, then 80 maintained checks with 1 skipped.
Root reviewed the harvested notes, registry resolution, immutable context and
legacy serializer. Initial root failures for legacy `model_dump_json`,
fractional order and invalid display values were corrected during the run.

Final review found the required schema file absent and the payload validator
mistaking the available platform-utility table for a complete CSS value domain.
New positive cases demonstrated rejection of valid inline-flex, object-fit
fill, static positioning, wrap-reverse and column-count auto. Expanded root
result: 6 failed, 7 passed. `artifacts/agency-style-pack-validation-fix.json`
owns the correction and requires the schema as a harvested deliverable.

The first worker also created `agency_library/style_payload.py` outside its
declared write list. This is an ownership violation, not evidence of safe
isolation; preserve the file and review it rather than silently deleting work.
The follow-up explicitly owns that module. W1 remains incomplete until the
expanded checks and code review pass. W2-W4 are still pending.
