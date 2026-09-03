# Isolated migration portal runbook

Use this runbook to provision one blank child portal per client design and run
the guarded agency-project workflow against it. The portal keeps one client's
pages, assets, theme decisions, global blocks, approvals, and QA evidence from
contaminating another client's build.

The examples use PowerShell. Portal creation, project build, publication, and
launch are separate authority boundaries. Stop at every marked review point;
creating a portal does not authorize building, publishing, launching, or
deleting one.

## 1. Choose explicit identities

```powershell
$RootUrl = "http://vanjarocli.local"
$RootProfile = "vanjarocli-local"
$ChildName = "Example Client"
$ChildSlug = "example-client"
$ChildProfile = "example-client"
$Workspace = "artifacts/projects/example-client"
$Operator = "Agency Operator"
```

The root profile must authenticate a DNN Host/SuperUser. Use a new child slug
and profile for every independent migration. Do not point two active projects
at the same disposable portal.

## 2. Authenticate and inspect the root

```powershell
vanjaro auth login --url $RootUrl --profile $RootProfile
vanjaro --profile $RootProfile auth status --json
vanjaro --profile $RootProfile site health --json
vanjaro --profile $RootProfile portal list --json
```

Let `auth login` prompt for credentials; do not put passwords in shell history.
Stop if authentication is expired, health does not identify the intended root,
or the portal list cannot be read with Host authority.

## 3. Preview the exact child-portal plan

The preview reads local configuration only. It performs no HTTP requests and
writes neither the portal nor the CLI profile.

```powershell
$PreviewJson = vanjaro --profile $RootProfile portal create `
  --name $ChildName `
  --slug $ChildSlug `
  --profile-name $ChildProfile `
  --dry-run `
  --json

$Preview = $PreviewJson | ConvertFrom-Json
$Preview
```

Review all of these fields before continuing:

- `status` is `preview`;
- `portal_contacted` and `profile_written` are `false`;
- `required_authority` is `Host/SuperUser`;
- `template` is exactly `Blank Website.template|en-US|/`;
- `alias` and `child_base_url` identify the intended child and preserve the
  root profile's HTTP/HTTPS scheme, port, and parent path;
- `payload.SiteName`, `payload.SiteAlias`, and `target_profile` are correct;
- `profile_exists` is `false` and `ready_for_confirmation` is `true`;
- `plan_fingerprint` is a 64-character SHA-256 value.

If the local profile already exists, prefer a new isolated name. Use
`--replace-profile` in both preview and apply only when intentionally replacing
that local profile. It does not authorize replacing an existing DNN alias.

## 4. Stop for portal-creation approval, then apply exactly that plan

Portal creation is a real external mutation. Continue only after someone has
reviewed the preview and explicitly authorized this portal.

```powershell
$CreateJson = vanjaro --profile $RootProfile portal create `
  --name $ChildName `
  --slug $ChildSlug `
  --profile-name $ChildProfile `
  --confirm-create `
  --plan-fingerprint $($Preview.plan_fingerprint) `
  --json

$CreateExit = $LASTEXITCODE
$Created = $CreateJson | ConvertFrom-Json
$Created
```

Before posting, the command uses read-only DNN checks to prove the exact blank
template exists and the alias is unused. The mutation is rejected when any
reviewed input or target URL changed after preview.

Proceed only when `$CreateExit` is `0`, `status` is `success`, and
`profile_written` is `true`. If the result is `partial_success`, the portal may
already exist. Stop, preserve the JSON, inspect Persona Bar, and do not repeat
the POST blindly. The result includes the portal ID, alias, plan fingerprint,
and credential-free recovery guidance.

## 5. Read the child profile back and pin its identity

```powershell
vanjaro profile list --json
vanjaro --profile $ChildProfile auth status --json
vanjaro --profile $ChildProfile site health --json
```

Confirm that the saved profile URL equals `$Created.child_base_url` and the
health response identifies `$Created.portal_id`. Stop on an HTTP/HTTPS mismatch,
wrong portal ID, expired session, or unexpected alias.

## 6. Initialize one project workspace

Choose the source declarations that match the job. All examples bind the
workspace to the newly created profile, URL, and portal ID.

Live website:

```powershell
vanjaro project init $Workspace `
  --name $ChildName `
  --target-profile $ChildProfile `
  --expected-base-url $($Created.child_base_url) `
  --expected-portal-id $($Created.portal_id) `
  --source live_html=https://source.example/ `
  --json
```

Figma design:

```powershell
vanjaro project init $Workspace `
  --name $ChildName `
  --target-profile $ChildProfile `
  --expected-base-url $($Created.child_base_url) `
  --expected-portal-id $($Created.portal_id) `
  --source figma=https://www.figma.com/design/FILE_KEY/NAME `
  --json
```

Desktop and mobile reference images for the same page:

```powershell
vanjaro project init $Workspace `
  --name $ChildName `
  --target-profile $ChildProfile `
  --expected-base-url $($Created.child_base_url) `
  --expected-portal-id $($Created.portal_id) `
  --source image=sources/home-desktop.png `
  --source image=sources/home-mobile.png `
  --image-viewport 1440x900 `
  --image-viewport 390x844 `
  --image-breakpoint image-1=desktop `
  --image-breakpoint image-2=mobile `
  --source-page image-1=home `
  --source-page image-2=home `
  --json
```

Initialization is local and refuses a nonempty workspace. A project may combine
source kinds by repeating `--source` when the evidence genuinely describes the
same site.

## 7. Verify the target before planning or mutation

```powershell
vanjaro project status $Workspace --json
vanjaro project target check $Workspace --json
```

The target check is read-only. It must prove the configured profile URL, pinned
base URL, pinned portal ID, and live health identity all agree.

## 8. Analyze and plan with previews

For live HTML, use rendered analysis when visual-fidelity evidence is required:

```powershell
vanjaro project analyze $Workspace --render --dry-run --json
vanjaro project analyze $Workspace --render --json
```

For Figma or existing image evidence, omit `--render`. Image projects without a
sidecar can preview and then explicitly generate evidence before analysis:

```powershell
vanjaro project evidence generate $Workspace --dry-run --json
vanjaro project evidence generate $Workspace --by $Operator --json
vanjaro project analyze $Workspace --json
```

Then preview and create the block-composition plan:

```powershell
vanjaro project plan $Workspace --dry-run --json
vanjaro project plan $Workspace --json
```

Review low-confidence mappings, simplifications, custom CSS, content losses,
responsive behavior, native-component coverage, global header/footer ownership,
and the final plan fingerprint. Fix or explicitly override questionable
mappings before requesting mutation authority.

## 9. Approve the plan and build hidden drafts

```powershell
$RequestJson = vanjaro project approval request $Workspace `
  --gate portal_mutation `
  --by $Operator `
  --json
$Request = $RequestJson | ConvertFrom-Json

vanjaro project approval resolve $Workspace $($Request.approval.id) `
  --decision approve `
  --by "Agency Approver" `
  --json

```

Build authority has two layers: the approved `portal_mutation` plan and a
detached action-time receipt for exactly one next executable stage. `--through`
is only a ceiling; neither preview nor apply executes the whole remaining range.
After each apply, create and review a fresh receipt for the next stage.

The following example reviews the theme stage. Use a receipt path outside the
project workspace so the dry-run workspace itself remains byte-identical:

```powershell
$Ceiling = "theme"
$ReceiptPath = "artifacts/build-reviews/$ChildSlug-$Ceiling.json"
$ReviewJson = vanjaro project build $Workspace `
  --through $Ceiling `
  --dry-run `
  --by $Operator `
  --json
$ReviewExit = $LASTEXITCODE
$Review = $ReviewJson | ConvertFrom-Json

if ($ReviewExit -ne 0 -or $Review.status -ne "preview") {
  throw "Build preview failed; no stage is authorized."
}

New-Item -ItemType Directory -Force (Split-Path $ReceiptPath) | Out-Null
$ReceiptText = $Review.receipt | ConvertTo-Json -Depth 100
[IO.File]::WriteAllText(
  [IO.Path]::GetFullPath($ReceiptPath),
  $ReceiptText + [Environment]::NewLine,
  [Text.UTF8Encoding]::new($false)
)
$Review.receipt

# STOP: review the exact project/target, stage, observed portal, portal_actions,
# local_writes, approval, and full fingerprint. Continue only after explicit
# authorization for this receipt.
$ApplyJson = vanjaro project build $Workspace `
  --through $Ceiling `
  --review-receipt $ReceiptPath `
  --confirm-build $($Review.receipt.fingerprint) `
  --by $Operator `
  --json
$ApplyExit = $LASTEXITCODE
$Applied = $ApplyJson | ConvertFrom-Json
$Applied

if ($ApplyExit -ne 0 -or $Applied.status -ne "ok") {
  throw "Reviewed build stage failed; preserve the output and stop."
}
```

Repeat the same preview/save/review/apply sequence with `$Ceiling` set, in
order, to `assets`, `library`, `pages`, `globals`, and `verify`. The command
will reconcile already-current earlier stages using GET/read-only probes and
will still apply only the one next executable stage. Never edit a detached
receipt. If any workspace file, approval, target, live object, or stage state
changes, discard it and preview again. When every stage through the selected
ceiling is current, the command stops with `no executable build stage`.

After `verify` completes:

```powershell
vanjaro project handoff $Workspace --json
```

This stage may create or update project-owned assets, library blocks, hidden
draft pages, and draft global wrappers. It does not authorize publication or
launch. Require a valid verification artifact and inspect the handoff scorecard;
`publish_ready` means its required checks passed, not that anything is live.

## 10. Publish and launch only under their own approvals

Use the detailed receipt workflow in
[`agency-project-workspace.md`](agency-project-workspace.md): preview and adopt
`project publish prepare`, approve its exact receipt, and repeat that receipt in
`project publish apply`. Publication keeps managed pages hidden. Launch then
requires a separately reviewed `project launch plan`, preview/adoption, approval,
and receipt-confirmed `project launch apply`.

After launch, manually verify public routes, navigation, responsive layouts,
editor behavior, forms/actions, search, and the selected home page. Preserve all
publish and launch receipts and transaction journals.

## 11. Release evidence and current stop conditions

Preview and write the representative project worksheets:

```powershell
vanjaro release scaffold-project-evidence `
  --candidate-id CANDIDATE_ID `
  --project-id $ChildSlug `
  --source-kind live_html `
  --workspace $Workspace `
  --output-dir "artifacts/releases/$ChildSlug" `
  --json

vanjaro release scaffold-project-evidence `
  --candidate-id CANDIDATE_ID `
  --project-id $ChildSlug `
  --source-kind live_html `
  --workspace $Workspace `
  --output-dir "artifacts/releases/$ChildSlug" `
  --write `
  --json
```

Use `figma` or `image` for the other source kinds. These worksheets are
intentionally incomplete until real measurements and reviewed evidence are
entered. The production CLI still lacks a trusted live verifier, so locally
authored evidence cannot independently close the live release gate.

The CLI also has no receipt-bound child-portal delete/restore command. Portal
cleanup is therefore a supervised manual stop: verify restoration or deletion
in DNN first, preserve the evidence, and only then remove the local child
profile. `vanjaro profile delete` removes local configuration only; it does not
delete the portal.

## Failure rules

- Never retry `portal create` after `partial_success` or an ambiguous outcome
  until the exact alias has been inspected.
- Never use `--replace-profile` to work around an existing portal alias.
- Never continue when `project target check` disagrees with the pinned identity.
- Never reuse an approval after the owning fingerprint changes.
- Never treat hidden-draft verification as publication or publication as
  launch.
- Never treat profile deletion as portal cleanup.
