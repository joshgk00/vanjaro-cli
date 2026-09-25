# Preserve semantic article ownership during wrapper descent

## Confirmed remaining failure

The independent article cases in `artifacts/test_nested_chrome_independent.py`
currently fail with and without a genuine site footer: the article byline has
no content owner. The testimonial cases pass. Do not dilute the article cases
by adding unrelated surrounding sections to avoid the single-wrapper path.

Inspection of `migration/sections.py::_top_level_sections` identifies two
unsafe assumptions to investigate together:

- Single-child descent treats every article as an ordinary layout wrapper,
  before the distinct-nested-sections guard can apply.
- Dominant-container descent assumes any child header/footer is site chrome.
  Articles can legitimately contain their own headers and attribution footers.

## Required behavior

A semantic article with a headline, body and local footer must retain all
visitor text exactly once under the article section, including its selector
provenance. A local footer must not create a global footer. A separate genuine
site footer must remain discoverable and separate.

Preserve descent through ordinary div/form/main layout wrappers, DNN content
panes, and semantic containers that truly wrap distinct visual sections.
Preserve uniform article-card grids as groups. Do not rely on fixture IDs,
specific author names, minimum text lengths or added surrounding content.

## Acceptance

Run the immutable root article/testimonial checks and maintained regressions
for single articles, articles beside short siblings (dominant text share),
local headers/footers, real site footers, wrapped DNN sections and card grids.
Then run the full offline suite and the real-browser boundary probe. Passing
only the testimonial cases does not establish article content retention.

## Ownership and sequencing

This is a follow-up integration lane if the current HTML-boundary worker
cannot satisfy the article cases within its ownership. Wait for that worker
to become terminal before dispatch. Grant explicit ownership of the necessary
migration section parser and a focused maintained test file; do not silently
expand another worker's scope. The independent style-translation lane need
not be stopped. Shared browser validation waits for stable production edits.

No portal mutation, fixture threshold changes, or source-content substitutions
are authorized by this contract.

## Review of the subsequent rescue implementation

The worker subsequently added `_rescue_local_footer_text` in the boundary
adapter. The original four checks now pass, but it decides whether a footer
was captured using a global set of words rather than node ownership. Root
`artifacts/test_footer_rescue_ownership_independent.py` fails: the distinct
footer paragraph is dropped when its words also occur in a longer body
paragraph. Its novelty heuristic cannot establish content retention.

Do not accept the rescue as the final solution or simply remove this failing
case. Preserve semantic article boundaries at extraction, and remove any
redundant heuristic rescue after verifying the original and adversarial cases.
Also cover identical bylines across separate articles, linked attribution,
and dominant articles beside short siblings. DOM structure must determine
ownership, with each source element retained once in its proper section.

## Structural correction under verification

The follow-up worker removed article from unconditional wrapper descent and
restricted the chrome-child expansion rule to ordinary layout wrappers.
It removed `_rescue_local_footer_text` rather than extending its word-based
heuristic. Root independently ran the original/adversarial footer checks plus
the maintained semantic-article and local-footer suites: 27 passed.

Reviewed maintained cases include dominant articles, repeated words, identical
bylines across two owners, linked attribution, local headers, DNN wrappers,
genuinely distinct nested sections and uniform article grids. The run remains
active at this review point; full integration and fresh browser validation are
still pending. This is focused parser evidence, not full migration completion.

The structural worker subsequently reached authoritative PASS on attempt 1
in run `vanjaro-agency-translation-retention-20260922T065328Z-p142550`:
5 independent cases and 361 maintained tests passed, exit 0. Root reviewed the
harvested notes, production diff and maintained regression file. The worker's
additional filtered offline sweep reported 2976 passed, 2 skipped and 107
deselected; that is not the complete final integration suite and ran while a
separate style-output lane was active. Browser validation remains outstanding.
