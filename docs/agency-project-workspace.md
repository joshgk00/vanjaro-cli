# Agency project workspace v1

The project workspace is the durable boundary between source intake, pure
design reasoning, portal mutation, approvals, and QA. It lets an agency build
resume from the first incomplete stage without mixing client profiles or
scattering artifacts through the repository.

## Initialize a project

When the target does not exist yet, provision and verify it first with the
[isolated migration portal runbook](isolated-migration-portal-runbook.md). The
runbook covers the root Host profile, network-free portal preview,
fingerprint-bound creation, child-profile readback, and the explicit stop before
any portal mutation.

```powershell
vanjaro project init artifacts/projects/example `
  --name "Example Client" `
  --target-profile example-client `
  --expected-portal-id 7 `
  --source live_html=https://example.com/ `
  --source figma=https://figma.com/design/example?node-id=1-2
```

Sources can be repeated and combined. Supported kinds are `live_html`,
`figma`, `image`, and `legacy_sections`; `html`, `live`, and `legacy` are CLI
aliases. Each image source requires a corresponding explicit viewport:

```powershell
vanjaro project init artifacts/projects/image-example `
  --name "Image Example" `
  --target-profile image-example `
  --source image=sources/home-desktop.png `
  --source image=sources/home-mobile.png `
  --image-viewport 1440x900 `
  --image-viewport 390x844 `
  --image-breakpoint image-1=desktop `
  --image-breakpoint image-2=mobile `
  --source-page image-1=home `
  --source-page image-2=home
```

Evidence sidecars may be supplied with `--image-evidence SOURCE_ID=PATH`, or
generated explicitly after initialization:

```powershell
# Local validation only: no credentials, network, or writes.
vanjaro project evidence generate artifacts/projects/image-example `
  --dry-run --json

# Analyze all breakpoints for each page together and write hash-bound sidecars.
vanjaro project evidence generate artifacts/projects/image-example `
  --by "Agency Operator" --json

vanjaro project analyze artifacts/projects/image-example
```

Automatic generation uses a provider-neutral detection contract and currently
ships an OpenAI Responses API provider. It sends all selected breakpoints for a
page together so section IDs and responsive correspondence can remain stable,
then writes one exact-observation sidecar per source. The API key is read from
`OPENAI_API_KEY` only when execution begins and is never persisted. Requests use
structured output, inline local image bytes, and `store: false`.

Existing valid sidecars are skipped. `--overwrite` requires every selected
breakpoint for the page, snapshots previous files under `history/evidence`,
invalidates analysis and downstream approvals, and records provider/model/request
fingerprints in the project audit trail. A provider or filesystem failure before
manifest adoption restores the prior sidecars. Inputs are limited to 20 MiB per
image and 40 MiB per page request. Adoption uses an exclusive project lock and
rechecks both the manifest fingerprint and raster identities after provider work,
so concurrent edits fail without adopting stale evidence.

Initialization refuses a nonempty directory and never overwrites an existing
manifest or artifact.

## Review an agency-pack upgrade

Projects declare their shared agency pack by name and version. Published packs
are resolved from `artifacts/agency-packs` or `VANJARO_AGENCY_PACKS_DIR`; the
registry verifies independent template/modifier payload versions and digests.

```powershell
vanjaro project pack upgrade artifacts/projects/example `
  --to-version 1.0.1 --dry-run --json
```

Apply a compatible, freshly reviewed report with `--apply`, its exact
`--accept-fingerprint`, and `--by`. The local transaction verifies plan/catalog
provenance, snapshots mutable files, locks the target digest, replans, and
invalidates approvals without calling the portal. Use `project pack rollback`
only to recover a prepared/applying interrupted transaction. See
`docs/agency-library-governance.md` for the full contract.

## Layout

```text
project.json     versioned identity, sources, target, stages, decisions,
                 approvals, and audit history
sources/         copied or cached source evidence and inventories
analysis/        Design Documents and extraction reports
plans/           composition, theme, library, and portal mutation plans
build/           composed page/global-block payloads and asset manifests
qa/              structural, responsive, visual, and release evidence
history/         immutable snapshots and recovery evidence
```

All paths stored in stage records are workspace-relative. Fingerprint and
artifact helpers reject paths that escape the project root.

## Inspect resumable state

```powershell
vanjaro project status artifacts/projects/example
vanjaro project status artifacts/projects/example --json
```

Status reports completed, failed, and running stages plus the first stage that
can resume. A new workspace completes `intake` and reports `analyze` next.

## Stage execution and resumption

The project engine executes this dependency chain:

```text
intake -> analyze -> plan -> theme -> assets -> library -> pages
       -> global_blocks -> verify -> publish -> launch
```

Every stage records separate input and output fingerprints, attempt count,
timestamps, workspace-relative artifacts, and an audit event. A completed stage
is resumed without running its operation only when:

1. its calculated input fingerprint is unchanged;
2. every declared artifact still exists; and
3. the current artifact fingerprint matches the recorded output fingerprint.

Changed inputs, missing outputs, or modified outputs rerun the stage and reset
downstream stage state. An operation failure is persisted as `failed`; a later
run increments the attempt and resumes from that stage. A process interruption
leaves `running` state, which is also safely retried rather than mistaken for
completion.

Dry runs calculate dependencies, fingerprints, resumption, approvals, exact
target observations, portal actions, and local writes. They may perform
authenticated GETs, but never call the stage operation or write the manifest or
portal.

The supported live draft build is:

```powershell
$Workspace = "artifacts/projects/example"
$Operator = "Agency Operator"
$Ceiling = "verify"
$ReceiptPath = "artifacts/build-reviews/example-next-stage.json"

$ReviewJson = vanjaro project build $Workspace `
  --through $Ceiling `
  --dry-run `
  --by $Operator `
  --json
$Review = $ReviewJson | ConvertFrom-Json

New-Item -ItemType Directory -Force (Split-Path $ReceiptPath) | Out-Null
$ReceiptText = $Review.receipt | ConvertTo-Json -Depth 100
[IO.File]::WriteAllText(
  [IO.Path]::GetFullPath($ReceiptPath),
  $ReceiptText + [Environment]::NewLine,
  [Text.UTF8Encoding]::new($false)
)

# STOP: review the stage, target, observed state, actions, local writes, and
# full receipt fingerprint before explicitly authorizing this one stage.
vanjaro project build $Workspace `
  --through $Ceiling `
  --review-receipt $ReceiptPath `
  --confirm-build $($Review.receipt.fingerprint) `
  --by $Operator `
  --json
```

`--through` accepts `theme`, `assets`, `library`, `pages`, `globals`, or
`verify`, but it is a ceiling rather than permission to execute the entire
range. Each preview and each apply selects exactly one next executable stage
and stops. Repeat the receipt workflow after every successful stage. A receipt
becomes stale when its project, target, approval, inputs, stage state, or live
preconditions change; rerun the dry run instead of editing or reusing it. If
every stage through the ceiling is already current, the command reports that
there is no executable stage.

The current safe page mode is `isolated`: it creates or reconciles a hidden,
project-prefixed draft and does not change navigation or publish it. Theme mode
`preserve` verifies the exact portal while leaving the existing theme untouched.

## Generate the agency editor handoff

After `verify` completes, generate the review package that an agency operator
can give to editors and use for the publish-readiness review:

```powershell
vanjaro project handoff artifacts/projects/example
vanjaro project handoff artifacts/projects/example --json
```

The command is local and non-networked. It does not contact the target portal,
change `project.json`, approve a gate, or publish anything. It validates the
fingerprint-bound verification report plus the current plan, asset, block,
page, and global-block manifests before atomically writing:

- `qa/agency-handoff.md` — editor-facing ownership, inventory, quality checks,
  open items, and the safe update workflow;
- `qa/maintenance-scorecard.json` — a versioned machine-readable score from
  the same evidence, with SHA-256 digests for every input.

The scorecard checks plan validity, content loss, editable coverage, native
component usage, built text retention, action destinations, draft blockers,
and visual fidelity. `publish_ready` means all eight checks passed. A
`review_required` result still produces the handoff successfully so the open
work is explicit, but it is a stop condition rather than permission to
publish. Missing or stale verification evidence fails without writing partial
outputs.

Generation uses the verification stage's recorded completion time and a stable
input fingerprint instead of the wall clock. Repeating the command with
unchanged evidence therefore produces byte-identical Markdown and JSON.

## Report release quality counts from the composition plan

`vanjaro_cli/release/gates.py` gates a project's release candidacy on four
quality measures. Compute them directly from the plan instead of typing them
into a worksheet by hand:

```powershell
vanjaro project quality artifacts/projects/example
vanjaro project quality artifacts/projects/example --json
vanjaro project quality artifacts/projects/example --candidate-id my-candidate --output artifacts/projects/example/qa/quality-counts.json
```

The command is local and non-networked. It reads `plans/composition-plan.json`
and the template catalog the plan was made against -- the same catalog the
`plan` stage resolves -- and reports four `numerator/denominator` counts:

- `eligible_section_editable_coverage` -- of body entries (non-global) that
  have at least one binding, how many have every binding editable.
- `native_agency_component_ratio` -- of every plan entry, how many resolve to
  a template with `native_component_ratio >= 0.90` and a scoped CSS rule count
  within the plan's `policy.css_rule_budget`.
- `body_without_generic_fallback` -- of body entries, how many did not land on
  the generic rich-text fallback template and are not a blocking match.
- `desktop_tablet_mobile_evidence` -- of the actual pages in
  `plans/resolved-design-document.json`, including empty pages, how many have
  valid desktop, tablet, and mobile records in `qa/capture-evidence/`.
  The shared reader checks design and local build fingerprints, target
  identity, screenshot hashes, observation structure, section ownership,
  and canonical viewport widths. Missing or stale evidence earns no credit
  and produces a diagnostic. Without authoritative page IDs, the count is
  0/1 with a warning; page identity is never inferred from section names.

These records establish correspondence to local build artifacts, not the
current live portal. Legacy `qa/fidelity-evidence.json` files do not earn
workspace-wide coverage. The recorder currently has no operator-facing CLI
entry point, so existing projects need new bound recordings before this
metric can pass; a capture command remains outstanding. See the
[responsive evidence contract](agency-responsive-evidence-contract.md).

With `--candidate-id` and `--output`, the command writes a
`project-quality-evidence-v1` document at the given path instead of (or in
addition to) printing the table. That document is exactly what
`vanjaro_cli/release/scaffolding.py`'s `quality-counts.template.json`
worksheet used to require an operator to fill in by hand -- release
worksheets should now be produced from this command's `--output`, not typed
by hand.

## Review and publish managed hidden content

Publication is a separate reviewed transaction. First preview the exact live
objects without writing either the workspace or portal:

```powershell
vanjaro project publish prepare artifacts/projects/example --dry-run --json
```

The dry run performs only authenticated GETs. It validates the current verify
and handoff fingerprints, target profile/base URL/portal ID, live server
identity, project ownership markers, object IDs, versions, content hashes, and
publication flags. Its receipt lists global header/footer actions before page
actions and identifies objects that already equal the intended published state.

Adopt the deterministic review receipt locally after inspecting the preview:

```powershell
vanjaro project publish prepare artifacts/projects/example --json
```

This writes `qa/publish-review.json` and binds it into `project.json`; it still
does not POST or publish. A changed receipt supersedes any pending or approved
publish decision. Request and resolve the publish approval only after adoption:

```powershell
vanjaro project approval request artifacts/projects/example `
  --gate publish --by "Agency Reviewer"

vanjaro project approval resolve artifacts/projects/example `
  approval-0002-publish --decision approve --by "Agency Approver"
```

Apply requires three exact authorities: the adopted receipt fingerprint, the
approval ID for that fingerprint, and an action-time confirmation equal to the
full fingerprint:

```powershell
vanjaro project publish apply artifacts/projects/example `
  --receipt RECEIPT_SHA256 `
  --approval-id approval-0002-publish `
  --confirm-publish RECEIPT_SHA256 `
  --by "Agency Publisher" `
  --json
```

The transaction publishes exact-version global blocks first and page content
second. It preflights the whole action set before the first POST, journals each
attempt under `history/publish/RECEIPT_SHA256/transaction.json`, reads every
object back before completion, and reconciles an unknown POST outcome without
duplicating a successful publish. Re-entering a completed apply is GET-only and
reports `resumed` only when every live object still matches the receipt.

This foundation intentionally publishes **hidden managed content only**. It
does not rename `[Agency Draft]` pages, add them to navigation, select a home
page, replace an existing live route, or change site settings. Those launch
mutations need a separately reviewed promotion transaction because they have
different collision and rollback risks.

## Plan, review, and apply site launch

Launch is a separate authority boundary after hidden-content publication. It
renames project-owned draft pages into editor-facing names, lets DNN derive the
final routes, applies reviewed navigation visibility, and can select the portal
home page. First create the deterministic launch plan:

```powershell
vanjaro project launch plan artifacts/projects/example `
  --home-page home `
  --visible home `
  --name "home=Home" `
  --title "home=Home" `
  --json
```

Use `--preserve-home` instead of `--home-page PAGE_KEY` when the current portal
home page must remain unchanged. Every page whose source navigation state was
`unknown` needs an explicit `--visible PAGE_KEY` or `--hidden PAGE_KEY` decision.
`--name PAGE_KEY=VALUE` changes DNN's `TabName`, which is what controls the
generated route; launch does not pretend that a separate arbitrary slug can be
applied safely. The plan records semantic sibling order. DNN's raw, potentially
sparse `TabOrder` values are preserved, while the relative order of managed
siblings must match the reviewed plan.

Request the server-authoritative read-only preview without adopting it:

```powershell
vanjaro project launch prepare artifacts/projects/example --dry-run --json
```

Unlike publish preparation, this operation uses the dedicated read-only
`AILaunch/Preview` POST because the complete intended page set is too large and
structured for a query string. It performs no portal mutation. The preview
first proves that every managed page is still the exact project-owned revision
published by the preceding publish receipt. The server then checks the complete
portal page and alias namespace, protected pages, hierarchy, managed sibling
order, intended routes, navigation visibility, and current home page.

After reviewing the before/after tree and warnings, adopt the same receipt:

```powershell
vanjaro project launch prepare artifacts/projects/example --json

vanjaro project approval request artifacts/projects/example `
  --gate launch --by "Agency Launch Reviewer"

vanjaro project approval resolve artifacts/projects/example `
  approval-0003-launch --decision approve --by "Agency Launch Approver"
```

Apply requires the full adopted fingerprint twice, its exact approved launch
gate, the launching operator, and a separate acknowledgement of the new home
page ID when the home page changes:

```powershell
vanjaro project launch apply artifacts/projects/example `
  --receipt RECEIPT_SHA256 `
  --approval-id approval-0003-launch `
  --confirm-launch RECEIPT_SHA256 `
  --confirm-home 101 `
  --by "Agency Launch Operator" `
  --json
```

Omit `--confirm-home` when the reviewed receipt preserves the current home page.
The Vanjaro.AI endpoint rereads the complete namespace inside a serializable
transaction and uses exact compare-and-set predicates for every page's metadata
token, name, title, path, visibility, parent, order, and culture plus the current
home page. It updates all reviewed pages and the optional home selection as one
database batch, rebuilds DNN paths, clears caches, and returns authoritative
readback. A collision or any third state fails before mutation.

Every attempt is journaled under
`history/launch/RECEIPT_SHA256/transaction.json`. If the client loses the apply
response after the database commits, retrying the exact receipt adopts the
intended live state without another POST. Re-entering a completed launch is
GET-only and also checks the exact post-launch metadata tokens recorded in the
journal. Because the server mutation is one transaction, recovery accepts only
the complete reviewed before-state or complete intended after-state. Any mixed
state is an integrity failure: the client sends no continuation POST and requires
supervised diagnosis. There is no automatic rollback, and temporary agency-draft
routes are not retained as redirects. A different rollback or redirect policy
requires its own reviewed plan.

Exact atomic launch updates the DNN tables directly and rebuilds paths/caches;
it intentionally does not call `TabController.UpdateTab`. As a result, launch
does not create DNN redirect history, raise tab-update extension events, or
synchronously reindex search/content items. Production acceptance must include
public-route, navigation, editor, and search smoke checks. An installation whose
extensions require tab-update events is not compatible until an explicit,
idempotent post-commit reconciliation contract is implemented and reviewed.

Publish and launch share one cross-process authority lock. Lock creation and
stale-owner recovery are serialized by an OS advisory gate so recovery cannot
remove a replacement owner at the check/replace boundary. A proven-dead lock
can also be inspected and cleared through:

```powershell
vanjaro project launch recover-lock artifacts/projects/example `
  --token OWNER_TOKEN `
  --confirm-clear OWNER_TOKEN `
  --json
```

The Vanjaro.AI server module must support the optional `version` field on both
page and global-block publish requests and enforce it in the database update.
An older module that publishes the latest revision without the conditional
version predicate is not compatible with this workflow.

If a process dies while holding the local publication lock, preserve and
inspect the receipt and transaction journal. The error includes a random owner
token. Clear only a proven-dead owner using the same token twice:

```powershell
vanjaro project publish recover-lock artifacts/projects/example `
  --token OWNER_TOKEN `
  --confirm-clear OWNER_TOKEN `
  --json
```

Recovery checks the recorded host, PID, and process-start identity. It refuses
an active or ambiguous owner and never contacts the portal. After recovery,
retry the exact approved receipt so the journal can reconcile live state.

## Approval gates

Request an approval after the owning artifact exists:

```powershell
vanjaro project approval request artifacts/projects/example `
  --gate portal_mutation `
  --by "Agency Operator"
```

Resolve the returned approval ID explicitly:

```powershell
vanjaro project approval resolve artifacts/projects/example `
  approval-0001-portal-mutation `
  --decision approve `
  --by "Agency Operator"
```

Theme, library, page, and global-block stages require an approved fingerprint
for the current plan output. Publish requires a separate approval for the
currently adopted publish-review receipt, which itself binds the current
verification, handoff, target, ownership, versions, hashes, and live identity.
When an upstream stage or receipt changes, stale approvals are marked
`superseded`; they cannot authorize a different plan or publication set.

## Safety contract

- The target CLI profile is mandatory and remains separate from the process's
  active profile.
- An optional expected portal ID supports a second identity check before later
  mutation stages.
- The agency-pack name and version are explicit in every manifest.
- Image evidence always records its viewport.
- Generated image evidence is bound to the exact raster SHA-256, page,
  breakpoint, viewport, and pixel dimensions; provider output cannot choose
  those ownership values.
- Secret-bearing metadata keys, authorization values, and secret URL query
  parameters are rejected by validation.
- Approved gates bind to a SHA-256 fingerprint, so changing a plan invalidates
  the authority to mutate or publish.
- Plan fingerprints include the executable template-catalog content. A
  template edit automatically supersedes the old approval, and the library
  stage rejects a template whose content no longer matches the approved plan.
- Changed managed custom/global blocks create deterministic immutable
  revisions. Existing revisions are retained and never overwritten or deleted
  by a draft build; page wrappers point only to the reconciled revision.
- Page updates use expected versions, snapshot the prior draft, and fail on a
  concurrently edited version instead of overwriting it.
- Publication uses exact-version conditional server updates, whole-set
  preflight/final readback, a durable recovery journal, and a shared
  cross-process authority lock for prepare, publish approvals, and apply.
- Launch uses a separate plan, receipt, approval, full confirmation, optional
  home-page confirmation, complete namespace collision preflight, one atomic
  server batch, exact final readback, and forward-recovery journal.
- Manifest writes are atomic and deterministically formatted.

The committed JSON Schema is `schemas/agency-project-v1.schema.json`.
