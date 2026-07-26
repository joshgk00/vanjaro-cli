# Agency project workspace v1

The project workspace is the durable boundary between source intake, pure
design reasoning, portal mutation, approvals, and QA. It lets an agency build
resume from the first incomplete stage without mixing client profiles or
scattering artifacts through the repository.

## Initialize a project

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
       -> global_blocks -> verify -> publish
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

Dry runs calculate dependencies, fingerprints, resumption, and approvals but
never call the operation and never write the manifest or portal.

The supported live draft build is:

```powershell
vanjaro project build artifacts/projects/example --through verify --dry-run
vanjaro project build artifacts/projects/example --through verify
```

`--through` accepts `theme`, `assets`, `library`, `pages`, `globals`, or
`verify`. The current safe page mode is `isolated`: it creates or reconciles a
hidden, project-prefixed draft and does not change navigation or publish it.
Theme mode `preserve` verifies the exact portal while leaving the existing
theme untouched.

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
current verification output. When an upstream stage changes, stale approvals
are marked `superseded`; they cannot authorize a different plan.

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
- Manifest writes are atomic and deterministically formatted.

The committed JSON Schema is `schemas/agency-project-v1.schema.json`.
