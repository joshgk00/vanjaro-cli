# Responsive evidence across an agency project

Status: storage, validation, and quality-reader implementation verified locally;
operator capture integration and live validation remain outstanding.

The agency quality report must count actual design pages with current desktop,
tablet, and mobile evidence. Counting screenshots or guessing page IDs from
section names cannot establish that coverage, particularly for image sources.

## Required behavior

1. Derive page membership from the resolved design document. Every page counts
   once in the denominator, including pages with no sections. An unrecognized
   section ID cannot create a page or earn evidence credit.
2. Preserve separate evidence for each page. Recording page B must preserve
   page A. Recapturing only desktop for page A must invalidate A's older tablet
   and mobile evidence rather than combine separate attempts into a full set.
3. Bind new records to the captured design document, current local build
   artifacts, and target identity. A change in these inputs requires recapture.
   This proves correspondence to local build records; it does not independently
   prove that the live portal remains unchanged.
4. Verify screenshot bytes against their recorded hashes. Missing, replaced,
   or changed files cannot count. All referenced paths must remain inside the
   workspace after resolving symlinks.
5. Require unique canonical breakpoints, paired design/build observations,
   and strict capture-stability flags. Invalid evidence contributes no coverage
   and explains which page needs attention.
6. Share the reader between the quality command and draft verification. Reading
   coverage makes no network requests and writes no artifacts.
7. Preserve legacy evidence compatibility explicitly. Legacy unbound records
   cannot earn current workspace coverage. When new per-page evidence exists,
   fidelity verification must inspect every design page and block on missing
   or stale evidence rather than score only the last captured page.

## Executable acceptance

Tests use temporary files and injected capture/measurement implementations:

- Several hashed image section IDs resolve to one actual page.
- Two recorded pages retain independent records and yield 2/2 coverage.
- Empty design pages remain in the denominator.
- Partial recapture removes previously complete coverage for that page only.
- Design, local build, or target changes invalidate the affected records.
- Missing or modified screenshots invalidate coverage.
- Unknown pages, duplicate breakpoints, malformed JSON, nonboolean stability,
  traversal paths, and symlink escapes cannot earn credit.
- Legacy-only evidence yields zero authenticated coverage with a warning.
- Quality and draft verification return the same coverage.
- Reading evidence does not change workspace contents.
- Multi-page fidelity evaluation blocks when any required page is missing or stale.

The initial focused baseline passed 43 tests on 2026-09-21. It establishes
existing behavior only; it does not validate the requirements above. The
implementation manifest is `artifacts/agency-capture-quality-implementation.json`.

## Operator workflow follow-up

Repository inspection also confirms that `record_project_fidelity_evidence`
has no production caller. Its current callers are tests. The evidence store
alone therefore does not complete the operator workflow.

A subsequent CLI integration must expose page selection and exact source/build
references in a preview, validate the project's target and page mapping, invoke
the existing renderer and measurer, and report per-page results. Collecting
evidence must not publish pages implicitly. Image and Figma references need
explicit support for their actual reference artifacts; an HTML-only URL option
must not be advertised as supporting all three input kinds. Tests must exercise
the command through the CLI with injected browser implementations and verify
that its output is consumed by the shared quality and fidelity readers.

This integration is a separate outstanding requirement, not part of the current
storage/counting task or evidence that the overall agency goal is complete.

## In-progress review evidence

On 2026-09-21 the first implementation draft passed the existing 2,648-test
suite (16 skipped), but that run preceded the new capture-evidence tests.
It is not acceptance of this feature. The independent check
`artifacts/check_capture_quality_acceptance.py` exited 1 and reproduced two
contract failures:

- Missing authoritative page mapping can still earn coverage credit.
- Missing local build and target bindings can still earn coverage credit.

Both must be corrected and the independent check must pass before accepting
the implementation. The worker remains active; these findings describe an
intermediate draft, not a completed review.

The subsequent correction passes the independent missing-binding and missing-map
check. A further direct validation probe still fails: passing
`{"breakpoint": []}` to `_validate_capture_entry` raises
`TypeError: unhashable type: 'list'` at its set-membership check. A malformed
breakpoint value must instead produce a rejection diagnostic and zero credit.
Retest this edge after the correction worker finishes; its current live run
must not be edited concurrently.

## Verified local result

Final root verification after both corrections: 2,694 non-integration tests
passed, 16 live integrations deselected. The independent binding/page-map
checker exits 0; the independent malformed-breakpoint regression passes all
six cases. The maintained shape and capture-evidence suite passes 45 tests.
The preceding failures above are resolved; they remain documented to explain
why the initial green suite was not enough for acceptance.

The real `kts-fidelity` workspace's quality command exits 0 and reports 0/1
responsive coverage with a missing per-page-evidence diagnostic. Its other
counts are unchanged: editable 8/8, native 11/11, body without fallback 5/11.
No live portal validation or operator time reduction is claimed by these tests.
