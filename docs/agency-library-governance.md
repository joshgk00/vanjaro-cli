# Agency library governance

Agency packs make the reusable Clicks and Mortars template/modifier library an
explicit project dependency instead of an ambient folder. Pack artifacts are
strict, Semantic Versioned, immutable, and verified by SHA-256 before they can
participate in compatibility planning.

## Registry layout

```text
artifacts/agency-packs/<pack-name>/
  packs/<pack-version>.json
  templates/<template-library-version>.json
  modifiers/<modifier-library-version>.json
```

The outer pack, template library, and modifier library have independent
versions. A pack manifest references exact payload versions and byte hashes.
The registry rejects unknown versions, invalid identities, traversal, missing
files, schema violations, version mismatches, and digest drift.

The repository currently publishes:

- `clicks-and-mortars@1.0.0`: locked snapshot of all 29 validated templates
  and their supported modifiers.
- `clicks-and-mortars@1.0.1`: governance-only patch using the unchanged
  template/modifier payloads and an explicit compatibility rule from 1.0.0.
- `clicks-and-mortars@1.1.0`: capability schema 1.1 with exact physical slot
  ownership and repeat cardinality for all 29 templates. It reuses modifiers
  1.0.0 and declares direct reviewed rules from both 1.0.0 and 1.0.1.

Published 1.0.x files are digest-locked historical records. The generator
checks those bytes but never recreates or rewrites them; it renders only the
current 1.1.0 template payload and pack manifest.

The 1.1.0 release is write-once once present: generation refuses differing
bytes under the same version. Executable-only template digests are separately
audited for all 29 templates, so a future component-tree or style change cannot
be swept into the compatibility allowlist without publishing a new version.
The only reviewed executable corrections in 1.1.0 are meaningful gallery
placeholder copy and mobile `col-12` classes in the icon feature list.

Regenerate or check these mechanical snapshots with:

```powershell
python -m vanjaro_cli.agency_library.generation --write
python -m vanjaro_cli.agency_library.generation
```

The check exits nonzero if a tracked pack artifact no longer matches the
executable template catalog.

## Project upgrade review

Every upgrade begins with a zero-write, project-bound review:

```powershell
vanjaro project pack upgrade artifacts/projects/example `
  --to-version 1.1.0 `
  --dry-run `
  --json
```

The dry-run binds its fingerprint to the project manifest, composition and
library plans, analyzed Design Document, optional overlays, and persisted
planning request. It never changes the project or portal. Apply the exact
reviewed result with:

```powershell
vanjaro project pack upgrade artifacts/projects/example `
  --to-version 1.1.0 `
  --apply `
  --accept-fingerprint <dry-run-fingerprint> `
  --by <reviewer> `
  --json
```

Apply is local-only. It verifies current-plan and target-catalog digests,
snapshots every mutable planning file, locks the selected pack digest, replans
the complete project, supersedes plan/portal/publish approvals, and persists
the accepted report plus a transaction journal. Any caught failure restores
the manifest and plan files byte-for-byte. An interrupted prepared/applying
transaction can be recovered once with:

```powershell
vanjaro project pack rollback artifacts/projects/example `
  --transaction <transaction-id> `
  --by <operator>
```

The report records exact source/target pack digests, used templates/modifiers,
library changes, stable issue codes, remediation, status, and a deterministic
fingerprint. Outcomes are:

- `compatible`: no unreviewed used contract is removed or changed;
- `remediation_required`: a used contract has a declared target replacement
  and affected sections must be replanned;
- `blocked`: usage is unknown, an upgrade rule is missing, a used contract is
  removed/changed without reviewed compatibility, or the capability schema
  changes.

Additive templates/modifiers are compatible only when the target pack declares
an explicit upgrade rule. Changed used contracts must be listed as reviewed or
mapped to a valid replacement. A missing or malformed composition plan fails
closed so an unassessed project cannot appear upgrade-safe.

## M4 evidence

Capability fields are bound to validated physical component slots and repeat
cardinality. The reviewed apply workflow is exercised by two isolated client
workspaces under `artifacts/e2e/`, each with a project-specific accepted report,
committed transaction journal, target digest lock, new plan fingerprint, and
superseded downstream approval evidence.
