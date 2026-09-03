# Agency development architecture

This document is the contribution boundary for the agency workflow. Its goal is
to keep source acquisition, design reasoning, portal effects, and CLI rendering
independently testable as the tool adds client and source types.

## Dependency direction

```text
commands -> orchestration -> design/project/release contracts -> utilities
                         -> portal services -> HTTP client
source adapters -> Design Document -> planner -> Composition Plan
```

The dependency arrows point inward. In particular:

- `vanjaro_cli.design.sources` owns source-specific acquisition contracts.
  HTML, Figma, and image details must stop at the adapter boundary.
- `vanjaro_cli.design` owns pure grouping, matching, planning, theme, and
  quality models. It must not import command modules or instantiate an HTTP
  client.
- `vanjaro_cli.project` owns persisted workspace state, approvals,
  fingerprints, locks, receipts, and explicit contract migrations.
- `vanjaro_cli.portal` owns Vanjaro/DNN endpoint semantics. A portal mutation
  must expose typed preview/apply/readback behavior to orchestration.
- `vanjaro_cli.orchestration` coordinates I/O at stage edges. It does not own
  Click presentation or source-specific inference.
- `vanjaro_cli.commands` parses arguments and renders results. Business rules
  belong in one of the packages above.
- `vanjaro_cli.reliability` owns canonical artifacts, redacted diagnostics,
  secret scanning, compatibility, and performance contracts.
- `vanjaro_cli.release` consumes current evidence read-only. It never logs in,
  publishes, launches, or substitutes a synthetic result for live evidence.

## Persisted and wire-contract changes

Every persisted or server-facing contract change must be classified before it
is merged:

1. Compatible implementation-only changes keep the current version.
2. Additive or changed persisted structures receive a new contract version.
3. An older accepted structure requires a named source-to-target migration.
4. Migrations are preview-first, deterministic, idempotent, preserve an exact
   backup, and emit a receipt. Loaders never infer a migration from shape.
5. Unsupported, missing, and future versions fail closed with a recovery
   instruction.

The supported set is authoritative in
`release/compatibility-policy.json`. DNN and Vanjaro product versions are
recorded observations; portal safety is enforced by exact Vanjaro.AI capability
and schema negotiation, not by guessing compatibility from a broad version.

## Artifact and diagnostic rules

- New JSON artifacts use `vanjaro_cli.reliability.atomic_write_json`: UTF-8,
  LF, sorted keys, one trailing newline, no duplicate keys, and no non-finite
  numbers.
- Fingerprints bind canonical content or declared raw file bytes. A path alone
  is never evidence.
- Machine errors use `diagnostic-v1`, stable codes, an allowlisted context,
  and structural redaction. Do not serialize exception representations,
  response bodies, headers, credentials, or absolute machine paths.
- Secret scanning is manifest-scoped. Never scan or ingest `.env`, CLI profile
  storage, credential directories, or arbitrary client source trees as a way
  to claim release safety.
- New modules should normally stay below 500 lines. Split by cohesive contract
  or operation, not by arbitrary line count.

## Required tests by change type

| Change | Minimum evidence |
|---|---|
| Pure design logic | Unit tests plus affected offline benchmark cases |
| Adapter contract | Adapter contract, byte-equivalence, and source-kind benchmark |
| Persisted contract | Schema parity, explicit migration, old/current/future rejection |
| Portal operation | Preview, exact request, conflict, final readback, and recovery tests |
| CLI JSON surface | Exact versioned schema, redaction, deterministic bytes, exit status |
| Release control | Passing synthetic contract plus missing/tampered/stale evidence cases |

Worker or review-agent reports are diagnostic input. Completion requires the
executable checks and repository-level verification to pass independently.
