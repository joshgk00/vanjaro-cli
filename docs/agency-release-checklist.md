# Agency release checklist

The release audit is deliberately separate from publish and launch authority.
It cannot deploy the Vanjaro.AI module, mutate a portal, publish a draft, or
create a live receipt. By default it does not execute repository-controlled
tests. Test and dependent control gates remain incomplete until test execution
is explicitly authorized.

## 1. Freeze the candidate

- Record the candidate ID and current CLI/source-tree identity.
- Confirm `pyproject.toml`, `vanjaro_cli.__version__`, the current project
  contract, Design Document, Composition Plan, agency-pack, template
  capability, publish, and launch schemas match
  `release/compatibility-policy.json`.
- Classify every persisted or wire-contract change and add a named migration
  where an older version remains accepted.

## 2. Generate local evidence

Preview the exact governed test operation and source inventory. This command
runs no tests, creates no directories or receipt, and does not edit the
contract:

```powershell
vanjaro release capture-tests release/test-policy.json `
  --repository-root . `
  --output artifacts/releases/test-evidence.json `
  --json
```

After reviewing the repository-controlled command and complete hash inventory,
grant the narrow execution/write authority explicitly:

```powershell
vanjaro release capture-tests release/test-policy.json `
  --repository-root . `
  --output artifacts/releases/test-evidence.json `
  --execute-tests `
  --json
```

Copy the printed `test_evidence` fragment into a separately reviewed release
contract change. The command never edits that contract. `--execute-tests`
inherits local filesystem/process authority and is not a network sandbox,
although its subprocess environment retains only process essentials (including
HOME/USERPROFILE where present) and strips portal, credential, password, key,
token, proxy, Vanjaro, Figma, and OpenAI configuration.

- Run the complete non-integration suite—not a test-file subset—and create a
  `test-evidence-v1` receipt bound to the exact source inventory and collected
  node-ID set required by `release/test-policy.json`. The audit independently
  expands the policy globs, validates the node-ID digest, and refuses control
  evidence that names a test outside that verified set. With explicit
  `--execute-tests` authorization, it reruns the governed command and requires
  the observed counts and node IDs to match the receipt exactly.
- Run exact, unfiltered HTML, Figma, and autonomous-image benchmark corpora.
  Bind each manifest, baseline, report, source, annotation, and reference file
  by SHA-256. The audit reruns every declared case with the current adapters,
  matcher, thresholds, and baseline; the supplied report must match that rerun
  exactly.
- Run at least five isolated performance samples after a warm-up. Record the
  allowlisted environment identity and evaluate both absolute and relative
  budgets with `performance-evidence-v1`.
- Scan only the declared release/project artifacts. The scope must exclude
  `.env`, CLI profiles, credentials, `sources/`, and arbitrary untracked files.
- Regenerate governed JSON artifacts and require canonical bytes and matching
  digests.
- Record passing structured-diagnostic, recovery, contract-migration, and
  import-boundary test IDs in `reliability-control-evidence-v1`. Those IDs must
  exactly match the groups in the tracked test policy.

## 3. Produce representative project evidence

Start each project with a preview-only worksheet plan:

```powershell
vanjaro release scaffold-project-evidence `
  --candidate-id rc-2026.08 `
  --project-id representative-image `
  --source-kind image `
  --workspace artifacts/projects/representative-image `
  --output-dir artifacts/releases/representative-image `
  --json
```

Add `--write` only to create the five `.template.json` worksheets; add
`--overwrite` only when intentionally replacing existing worksheets. These are
not evidence: required observations remain null/empty so strict models reject
them until an operator records real measurements and bindings. Scaffolding
stages all five files and restores the complete prior worksheet set if a write,
backup, or replacement fails. Review any returned cleanup warning before using
the worksheets; it identifies a repository-local recovery directory that was
not removed after commit. Scaffolding does not contact a portal, create an
attestation, infer an operator identity, or update the release contract.

Provide exactly one HTML, Figma, and image project. Each must have:

- a current project schema and immutable agency-pack selection;
- complete verify, publish, and launch stages with current artifact
  fingerprints;
- a fingerprint-valid `publish_ready` maintenance scorecard;
- a candidate-, project-, and source-bound `project-quality-evidence-v1`
  containing integer numerators and denominators rather than asserted ratios;
- eligible editable coverage of at least 0.85;
- native/agency-standard component ratio of at least 0.90;
- body composition without generic fallback of at least 0.90;
- complete desktop, tablet, and mobile evidence;
- `project-effort-evidence-v1` containing individually identified baseline and
  current sessions, with one shared, digest-bound measurement protocol and
  quality policy; the verifier recomputes totals and requires at least a 60%
  reduction.

## 4. Produce authorized live evidence

This is a separate action-time authorization step. On isolated portals, deploy
the reviewed server build and run the exact project publish/launch workflow.
For each source kind, capture a strict `agency-live-evidence-v1` receipt binding:

- portal ID and normalized URL;
- observed DNN, Vanjaro, and Vanjaro.AI versions;
- project, publish, and launch fingerprints;
- public route, navigation, editor, and search smoke checks;
- decoded desktop (1440×900), tablet (768×1024), and mobile (390×844) PNG
  capture bytes, including valid chunk CRCs and pixel streams;
- a named `agency-live-attestation-v1` operator attestation binding the
  candidate, portal, routes, observation time, and capture digests;
- successful cleanup/restoration and a reviewed validity date.

Fake backends, unit tests, screenshots without digests, and prose status notes
are not live evidence. A locally self-authored bundle cannot close a live gate:
an embedding caller must also provide a trusted live verifier. The production
CLI does not yet provide that authority.

## 5. Run the fail-closed audit

```powershell
vanjaro release verify release/agency-release-contract.json `
  --repository-root . `
  --execute-tests `
  --output artifacts/releases/agency-release-audit.json `
  --json
```

`--execute-tests` executes repository-controlled Python with the caller's
local filesystem and process authority. The verifier passes a deliberately
minimal environment that excludes credential, token, password, key, proxy,
Vanjaro, Figma, OpenAI, and portal configuration variables, but this is not a
network sandbox. Review and trust the repository before opting in.

The command exits zero only when every closed gate passes. Missing evidence is
`incomplete`; malformed, stale, unsupported, mismatched, below-threshold, or
tampered evidence is `failed`. The output is canonical JSON without wall-clock,
hostname, username, credential, or absolute-path fields.

The tracked contract intentionally remains incomplete until current authorized
live evidence and the three representative project/time records exist. Do not
change an incomplete gate to passed by waiver or by reducing the declared case
set.
