# Template Capability Closed-Loop Goal

**Status:** Active
**Started:** 2026-08-09
**Product owner:** Clicks and Mortars
**Related foundations:** `visual-fidelity-goal.md`, `agency-library-governance.md`,
`template-capability-catalog.md`

## Goal

Make a template's inability to hold real content a *measured, ranked* property
of the library, and close every gap it reports through governed pack releases
until no benchmark site loses visitor content to a missing field.

An agent must be able to ask the library one question — "across every site we
measure, which declared template field is missing, and how much content does
its absence drop?" — get an ordered answer computed from current evidence, take
the top entry, prove the section is not simply misclassified, widen the
template in a governed release, and show the loss count fall without moving any
other site's numbers.

The goal is complete when that report is empty across the corpus and the three
real sites, and staying empty is enforced by a test rather than by a habit.

## Problem statement

Six template capability gaps have been found so far: VF-225, VF-226, VF-227,
VF-234, VF-235 and VF-236. Every one of them was found the same way — by a
human or an agent reading a per-section loss list on a single site and noticing
a pattern by eye. Nothing in the pipeline attributes a loss to the template
field that would have held it, nothing aggregates those attributions across
sites, and nothing ranks them. So gaps are discovered one site at a time, in
whatever order the loop happens to visit sites, and a gap that costs three
sections on a site nobody is currently looking at is invisible.

The library shows what that produces. Sixteen non-navigation templates declare
a repeat group. Four of them can hold the short line of copy that introduces
the repeated items; twelve cannot — and the split runs *through* families
rather than between them:

| template | repeat kind | `section_title` | `section_body` |
|---|---|---|---|
| `Cards/blog-post-cards-3up` | article | yes | — |
| `Cards/blog-post-cards-4up` | article | yes | **yes** |
| `Cards/class-photo-cards-4up` | card | yes | — |
| `Cards/feature-cards-3up` | card | yes | — |
| `Cards/feature-cards-4up` | card | yes | — |
| `Cards/gallery-3up` | gallery_item | yes | **yes** |
| `Cards/gallery-6up` | gallery_item | yes | **yes** |
| `Cards/pricing-cards-3up` | pricing_plan | — | — |
| `Cards/team-member-grid-4up` | person | yes | **yes** |
| `Cards/testimonial-cards-3up` | testimonial | — | — |
| `Content/faq-accordion` | faq_item | yes | — |
| `Content/logo-bar` | logo | yes | — |
| `Content/ribbon-marquee` | marquee_item | — | — |
| `Content/stats-band-3up` | stat | — | — |
| `Content/stats-grid-4up` | stat | yes | — |
| `Lists/icon-feature-list` | feature | — | — |

`blog-post-cards-3up` and `-4up` are the same design at two widths and differ in
what they can hold. `gallery-3up` can introduce its items and `feature-cards-3up`
cannot. Nothing in the design justifies either difference; they are authoring
accidents, and they are only visible because this table was built by hand for
this document. The same is true one level down: `Content/split-media` and
`split-media-reverse` own a single `body` slot, so a two-column split with three
paragraphs keeps one and drops two — the identical shortfall `Content/bio-about`
had until pack 1.6.0 widened it to three.

Two existing pieces of evidence look like they should already catch this and do
not:

| Existing check | What it covers | Why it misses these |
|---|---|---|
| `design/vocabulary_audit.py` (VF-208) | Roles and item fields adapters emit vs fields templates declare, globally | A role is reachable if *any* template accepts it. `section_body` is declared by four templates, so it is reachable — while the twelve that lack it silently drop it. |
| `orchestration/project_planning._content_losses` | Per-section list of source fields the chosen template cannot hold | Reports section ids and field names for one project. No template attribution, no aggregation, no ranking, no corpus view. |

The measurement is one join away from evidence that already exists. Without it,
this goal's work would be six more discoveries by eye.

## Product requirements

### TC-1 — Gaps are measured, not noticed

- A single command reports, across every benchmark site and every real site,
  each `(template, missing field)` pair that dropped visitor content, with the
  count of sections and the count of dropped fields attributable to it.
- The report is computed from current plan evidence on every run. It is never
  hand-maintained and never cached past a source or code change.
- The ranking is by measured content dropped, not by severity label, and not by
  which site is currently being worked on.

### TC-2 — A missing field must be proven missing

- Before a template is widened, the iteration must show the section is
  classified correctly. A section that matches the wrong template does not need
  a wider template; it needs the classification fixed, and widening would hide
  the real defect.
- The recurring failure this guards against is naming a tag or a class where a
  kind of thing was meant. Seventeen instances are recorded in
  `visual-fidelity-goal.md`; assume the eighteenth is in the next task.
- A gap that turns out to be a misclassification is closed as such, with the
  wrong premise recorded, and does not become a pack release.

### TC-3 — One capability change per governed release

- Every widening goes through agency-pack governance: version bumped, executable
  digests re-audited, prior release digests moved to immutable history,
  generated schema and documentation regenerated in the same commit.
- A release contains one capability change unless two are provably independent,
  because a release carrying two changes measures neither. Pack 1.6.0 carried
  two and one of them (`bio-about`) turned out to help nothing.
- The audited field ledger in `tests/test_template_catalog.py` is updated
  deliberately, never adjusted to make a test pass.

### TC-4 — Anti-overfit, unchanged from the parent goal

- No widening is accepted if it raises one site and lowers the corpus mean.
- Every iteration reports all three real sites — `edca-pilot`, `kts-fidelity`,
  `artifacts/projects/northstar-recheck` — with coverage, blocking count, loss
  count, rendered counts and per-dimension evidence counts.
- `northstar-recheck` stays a control: it is never the target of a fix, and a
  change that moves it is a change worth explaining.
- The ten corpus metrics are reported every iteration and are expected not to
  move.

### TC-5 — The library cannot regress into asymmetry

- A test asserts that templates sharing a repeat kind declare the same section
  level fields, so the `blog-post-cards-3up` / `-4up` split cannot recur.
- Where two templates in a family deliberately differ, the difference is
  declared and justified in the test rather than tolerated by its absence.

### TC-6 — Bounded autonomy

The parent goal's prohibitions apply here unchanged and are not negotiable:

- Never edit a benchmark annotation, fixture, or threshold to move a metric.
- Never weaken a threshold or a gate.
- Never fabricate visitor content or action URLs.
- Never migrate a form as HTML or as a lookalike block. A form gets a dashed
  placeholder listing its detected fields; Josh rebuilds it with his forms
  plugin.
- Publishing is authorized for the pilot portal (8) only. The six benchmark
  portals are not authorized.
- `project approval resolve`, `portal_mutation` and publish are human gates.
- Never re-analyse `artifacts/projects/pilot-measure` — it invalidates the
  `portal_mutation` approval already granted.
- `.env` is read-blocked. Re-authenticate with
  `vanjaro auth login --url http://vanjarocli.local/pilot --profile pilot --json`.
- Halt and report rather than proceeding past a halt condition.

## What one iteration does

1. Read this goal and its backlog. Take the top unblocked task.
2. **Verify its premise by measurement before writing any code.** Seven
   consecutive tasks in the parent goal rested on premises that turned out to be
   wrong, and each real fix was smaller and different from the filed one.
3. Run `analyze --refresh --render` before `plan --refresh` for each real site.
   Stage fingerprints cover source and policy, not code, so a code-only change
   reproduces a cached artifact and reports no movement. Confirm
   `execution.action == "execute"`.
4. Implement with tests. A model change regenerates the committed plan schema in
   the same commit.
5. Run `pytest -m "not integration"` and the offline benchmark. Commit only on
   green.
6. Report all three real sites and the corpus, before and after.
7. Append to the progress log below, then update the memory handoff at
   `C:\Users\Josh\.claude\projects\C--Code-vanjaro-cli\memory\project_pipeline_status_handoff.md`
   and its `MEMORY.md` index line.

If nothing unblocked is worth an iteration, say so plainly and stop rather than
inventing work.

## Delivery milestones

### TM1 — Capability gap report

The join that does not exist yet: plan warnings, attributed to the template that
produced them, aggregated across sites, ranked by content dropped. Until this
lands, every task below is a task found by eye.

### TM2 — Close the two known gaps

`Content/split-media` and `split-media-reverse` widened to hold several
paragraphs; the twelve repeat templates that cannot introduce their items given
`section_body`. Each in its own governed release, each measured.

### TM3 — Work the ranked queue to empty

Take the report's top entry until the report is empty on the corpus and the
three real sites.

### TM4 — Lock it

The family-symmetry test of TC-5, plus a regression test that the gap report
stays empty, so the next accidental asymmetry fails a check instead of costing a
site three sections.

## Backlog

### TC-127 — A testimonial quote is emitted twice

**Dependencies:** none. **Filed with a measurement, not fixed — it is the last
double-emission the corrected instrument can see.**

`rendered-home`'s `#dnn_ContentPane` holds **six** `<blockquote>` elements and no
`<figure>`, and the document carries **twelve** `testimonial_quote` elements —
each quote twice, both copies in the same repeat group. The testimonials branch
takes `root.find_all("figure") or root.find_all("blockquote")` as its repeat
items and emits one quote per item, so six items cannot account for twelve
elements. Something reads the group twice, and that is what to measure first.

Worth 6 of the 6 double-emitted elements remaining across the ten projects.

### TC-126 — `extract_sections` emits a normalized paragraph twice

**Dependencies:** none, and it **blocks TC-125**. **Pre-existing — found by
measuring TC-125's effect, and reproduced without TC-125's change.**

```python
extract_sections("<section id='dnn_content'><div id='dnn_TopPane' class='Pane'>"
                 "<h2>Serious</h2><div class='detail-date'>21 Sep</div></div></section>", …)
# -> {'headings': ['Serious'], 'paragraphs': ['21 Sep', '21 Sep']}
```

`_extract_content` called directly on the same pane returns **one** paragraph, so
the second copy is added by `extract_sections` — the split/merge path around
lines 1846 and 1900 runs the extractor over an element and over something that
contains it. A plain leaf div reproduces it, so this predates any recent change.

**Measured cost across the ten projects: 61 surplus copies today**, of 461
elements. Every one inflates retention, which is the number this loop steers by.

### TC-125 — A text block carrying inline markup is not read as a paragraph

**Dependencies:** **TC-126 must land first.** **Measured, implemented, and
REVERTED — the gain was half duplication.**

`normalize_text_blocks` rewrites a text-bearing div into a `<p>`, and disqualifies
any div with an element child:

```python
if element.find(True) is not None:
    continue
```

"Has a child" is standing in for "is a wrapper", and a paragraph routinely
carries inline markup. A blog post's date badge is
`<div class="detail-date">21 <span class="month">Sep</span></div>`, and it reaches
no element on any page that writes one. Instance 31.

The rule should be that a div qualifies when everything inside it is phrasing —
`html_ownership._PHRASING_TAGS` already names exactly that set, and the two want
sharing rather than a second spelling.

**Why it is not shipped.** Measured: **70 divs across the ten sources newly
qualify**, retention rises 461 → 486, no project drops, post-security's thin
section resolves and the capability queue grows 24 → 30. But surplus copies rise
**61 → 74**: thirteen of the twenty-five new elements are duplicates emitted by
TC-126, not content the page gained. A retention rise that is half duplication is
exactly the false gain the arbiter exists to catch, so it waits for TC-126.

### TC-124 — An item-field overflow is reported by nothing

**Dependencies:** none. **Filed with a measurement, not fixed.**

A section field that needs more slots than its template owns produces the
warning `X needs N slots, template owns M`, and the capability report reads it —
that is how TC-102 widened `split-media` from one body slot to three. **The same
overflow one level down produces nothing at all.**

Measured on `kts-fidelity` after cards began keeping every paragraph they carry:
`item.body` declares `slots_per_owner: 1`, its cards now offer two and three
paragraphs each, and the plan holds **no warning, no loss entry and no issue**
about it. `content_losses` lists only the two pre-existing entries
(`decorative_media`, `eyebrow`). The overflow is visible solely as a coverage
fall — 0.9565 → 0.8148 — with nothing naming the cause.

This is the same shape as the finding TC-121 answer 1 turned up (a blocked
section is invisible to the gap queue): the capability report can only rank what
some part of the pipeline names. Content that arrives and binds to nothing must
be named, or widening the right template stays a matter of noticing.

### TC-123 — A card keeps its picture, its title and its date, and drops the rest

**Dependencies:** none. **Filed with a measurement, not fixed — it is a different
mechanism from the container defect and deserves its own iteration.**

`cmw-blog`'s `#dnn_ContentPane` is the largest single loss the within-boundary
alarm reports: **42 of 70 runs kept, 28 lost**, and the container rule did not
touch it. Each `article.list-post` in the blog listing offers more than the card
grid takes:

| kept | dropped |
|---|---|
| `card_media` (the post image) | the excerpt paragraph, `div.list-description > p` |
| `card_title` (the post title) | the author and tag links, `div.list-info > a` (`CMW Team`, `Website Design`, `Business Website`, `Website Security`, `Tips`…) |
| `card_body` — **the date**, `Nov 13, 2017` | `Share`, and `Read More >` |

Two questions, and the second is the interesting one. The narrow question is
which fields a card emits. The wider one is that `card_body` received the
**date** while the excerpt — the card's actual body copy — was dropped, so the
grid reads as nine dated cards with no prose. `dated_card_kind` was added in
evidence 1/7 to recognise a blog listing *by* its dates; this is that signal
being taken as the body.

### TC-122 — Content lost inside a claimed boundary is invisible again

**Dependencies:** none. **Filed with a measurement, not fixed.**

TC-120's alarm is boundary-level: it reports a boundary that reached no section.
Once a boundary IS claimed, whatever the section fails to extract from it is
invisible once more. contact-page proves it — its contact panel now arrives, and
**5 of the panel's 12 distinct text runs are still missing** while the panel is
no longer reported at all:

| missing run | where it lives |
|---|---|
| `Clicks & Mortar Websites` | inside `<address>` |
| `PO Box 773` | inside `<address>` |
| `Troy, MI 48099` | inside `<address>` |
| `info(at)clicksandmortarwebsites(dot)com` | `<li>` text after a `<strong>` label |
| `@clicksmortarweb` | `<li>` text after a `<strong>` label |

Two mechanisms, both narrow: `<address>` is not read by `_extract_content` at
all, and a list item yields its `<strong>` label while the value beside it is
dropped — which is also why the section classified as `stats` with
`Phone :`/`Email :`/`Twitter :` as its stat *values*.

The alarm to build first is the same shape as TC-118's: compare a claimed
boundary's text runs against what its section kept. That is a per-section
retention denominator, and it is the piece TC-120 deliberately did not build.

### TC-121 — A reported boundary is still a dropped boundary

**Dependencies:** TC-120 supplies the inventory. **Filed with a measurement, not
fixed — the alarm is one task and the repair is another, the same way TC-118 came
before the five repairs it made possible.**

TC-120 reports eighteen boundaries across nine projects whose content reaches no
section. Reporting them does not keep them. The inventory, by kind:

| kind | count | example |
|---|---|---|
| banner image above the content | 5 | `#dnn_BannerPane`, 1 image, on cmw-blog, contact-page, wwo, post-security, rendered-home |
| footer social/copyright strip | 5 | `#dnn_FooterBottomPaneC`, 3 images; `#1f670a38`, "All rights reserved" |
| footer tagline | 3 | `#dnn_FooterBottomPaneB`, 19 words, three sources |
| **real page content** | 3 | contact-page `#dnn_Full_Screen_PaneB` — two headings, an address, a phone list and a call button |
| a form | 1 | contact-page `#dnn_ContentPane`, "CONTACT FORM" |
| decorative pane | 1 | oasis-probe `#dnn_Full_Screen_PaneH`, 1 image |

Four different answers are needed and they are not the same task. The contact
panel should become a section. The footer strips are chrome that `_trailing_footer`
declines to take, because it deliberately returns **one** footer — two make
`split_global_sections` report conflicting variants and block. The form gets a
dashed placeholder listing its detected fields; it must never be migrated as
HTML. The banner image is the one to measure first: `_is_banner_image_section`
already promotes a leading image-only pane to a section background, and it is not
firing here.

Expect retention to RISE, and expect coverage to fall as content arrives that no
template can hold — the TC-115 shape, not the TC-113 trap.

### TC-101 — The capability gap report (supersedes nothing; blocks the ranking)

**Dependencies:** none

Attribute each `source field '<name>' is not editable by template` warning to
the entry's `template_id`, aggregate across every project under
`artifacts/projects/` and the benchmark corpus, and rank by dropped-field count.
Surface it as a command with `--json`, in the same shape as the existing audit
commands.

**Acceptance criteria**

- The report names `(template, field)` pairs, not section ids alone.
- Running it today reproduces, without being told, the two gaps already known:
  `split-media*` body capacity and card-template `section_body`.
- Deterministic: same inputs, byte-identical output.
- No change to the ten corpus metrics; all three real sites reported.

**TC-101 done (iteration 61).** `vanjaro project capability-gaps` and
`design/capability_gaps.py`. It reproduced both known gaps without being told,
found two the backlog had not recorded, and held back eleven losses that are not
capability gaps. Benchmark-corpus coverage is *not* included: the offline
benchmark scores extraction and matching from a fixture manifest and never
builds a composition plan, so covering it means running the planner inside the
benchmark — a change to what the benchmark computes, filed as TC-106 rather than
smuggled in here.

### TC-102 — A two-column split with several paragraphs owns one body slot

**Dependencies:** TC-101 should rank it first; do not wait if it does not

Supersedes **VF-235**. `edca.section.2` is a picture beside three paragraphs.
Since iteration 40 it reads `split_media`, so it matches
`Content/split-media-reverse`, and both split templates own a single body slot.
Widening `bio-about` in 1.6.0 did not help it, because the section is not
classified as a biography.

**Verify first (TC-2):** confirm `split_media` is the right classification for a
picture beside three paragraphs before widening anything.

**Acceptance criteria**

- A two-column split with several paragraphs binds without overflow.
- One governed release, digests re-audited, prior versions immutable.
- `edca-pilot` blocking count falls; corpus unchanged; all three sites reported.

**TC-102 done — agency pack 1.8.0 (iteration 64).** `Content/split-media` and
`split-media-reverse` own three body slots, matching `bio-about`, which is the
identical layout. `edca-pilot` coverage 0.25 → 0.6667, blocking 1 → 0, and its
plan is **valid for the first time**. Corpus unchanged.

### TC-103 — Twelve repeat templates cannot introduce their own items

**Dependencies:** none

Supersedes **VF-236**, and is wider than it was filed. Three of
`kts-fidelity`'s five remaining losses are a section-level `body` on a card
grid. `blog-post-cards-4up`, `gallery-3up`, `gallery-6up` and
`team-member-grid-4up` declare `section_body`; twelve sibling templates do not,
including `blog-post-cards-3up`, which is the same design at a different width.

**Verify first (TC-2):** a section-level body is content the *section* owns, not
an item's body that landed in the wrong place. Confirm the ownership before
declaring a field for it.

**Acceptance criteria**

- `kts-fidelity` content losses fall by the three `section_body` entries.
- Governed release; ledger and generated artefacts updated in the same commit.
- Corpus unchanged; all three real sites reported.

**Premise wrong for two of the three sections (iteration 62), and TC-2 is why
it was caught.** `keys-to-success.section.7` is a grid of instructors and
`.section.8` a grid of blog posts. Their source markup is
`team-member-grid-4up` and `blog-post-cards-4up` — templates that *already*
declare `section_body`, in the exact slot the copy sits in. Both sections were
routed to `feature-cards-4up`, which does not, because the extractor reduces
every card-shaped repeat group to kind `card` and role `feature_cards`. Neither
correct template appears even in the top-three alternatives. Widening
`feature-cards-4up` would have bound the copy and buried the routing defect, and
the report would have gone quiet while a team grid kept being built as generic
feature cards. Filed as TC-107.

What remains of TC-103 is `section.5` alone, whose source *is* a
`class-photo-cards-4up` section — and even there the content is an eyebrow above
the headline, not a body under it. It is one section, so it now ranks below work
with more evidence. Do not widen a card template for it until TC-107 has settled
what the section actually is.

### TC-107 — A card-shaped grid is not the same kind of thing as a card grid

**Dependencies:** none; blocks the rest of TC-103

The extractor emits repeat kind `card` and section role `feature_cards` for any
grid of image-plus-title-plus-text, so a grid of people, a grid of blog posts
and a grid of features are indistinguishable to the matcher. The library
already has `team-member-grid-4up` (kind `person`) and `blog-post-cards-4up`
(kind `article`); nothing can ever route to them from an HTML source.

This is the recurring failure in a new dress: a *shape* is not a kind of thing,
just as a tag is not. Measured cost today is two of `kts-fidelity`'s five
losses, plus two sections built from the wrong template with no loss recorded at
all — the shape fits, so nothing complains.

**Acceptance criteria**

- A grid of people routes to a person template and a grid of posts to an article
  template, on evidence from the items rather than from the source's markup ids.
- `semantic_role_accuracy` and `template_top1_accuracy` do not fall.
- No benchmark annotation, fixture or threshold edited.

**TC-107 done (iteration 63).** A card grid now takes its kind from the heading
the section gives itself, in the same words the Figma adapter already reads off
a frame name — the HTML side simply had no equivalent. `keys-to-success`
sections 7 and 8 route to `team-member-grid-4up` (0.9589, high) and
`blog-post-cards-4up` (0.9509, high) instead of `feature-cards-4up` at medium.
kts coverage 0.8971 → 0.9412 and losses 5 → 2; corpus unchanged.

### TC-104 — Five repeat templates cannot hold a section heading

**Dependencies:** TC-103 (same shape, same release mechanics — do it after, so
each is measured on its own)

`pricing-cards-3up`, `testimonial-cards-3up`, `ribbon-marquee`,
`stats-band-3up` and `icon-feature-list` declare no `section_title`, while every
other repeat template does. Pack 1.6.0 fixed exactly this for
`feature-cards-3up` and `-4up` and recovered a heading on two sites, including
one that was never the target.

**Verify first (TC-2):** confirm each of the five actually receives sections
carrying a heading. A template nothing routes to does not need a wider field; it
needs deleting or a routing fix, and that is a different task.

**One of the five done — agency pack 1.7.0 (iteration 62).**
`Cards/testimonial-cards-3up` declares `section_title`; its three authors moved
from `heading_1..3` to `heading_2..4`. It was the only one of the five with
measured evidence: Northstar's testimonial section carries the heading "Trusted
by focused teams" and was dropping it. Northstar content losses 1 → 0, coverage
0.7727 → 0.8182, and corpus `high_confidence_precision` rose 0.9333 → 0.9444.

`pricing-cards-3up`, `ribbon-marquee`, `stats-band-3up` and `icon-feature-list`
are still unverified — no section on any site has demanded a heading from them.
Widening them now would repeat 1.6.0's mistake, where the unmeasured half of the
release helped nothing.

**A second done — agency pack 1.10.0 (2026-08-10).** TC-106 put the benchmark
corpus into the queue and `stats-band-3up` came out at rank 1 with **two**
sections, on two different cases, both matching a template their own annotation
names as acceptable. `Content/stats-band-3up` now declares `section_title`; its
three values moved from `heading_1..3` to `heading_2..4`. Corpus
`high_confidence_precision` rose 0.9444 → 0.9474. Three templates remain
unverified, and the discipline that held this one for four iterations is what
produced its evidence.

### TC-106 — The benchmark corpus is outside the gap report

**Dependencies:** none, but it changes what the benchmark computes

TC-101 reports gaps from composition plans, and only project workspaces have
plans. The offline benchmark scores extraction and matching against a fixture
manifest of predicted template ids; it never runs the planner, so no benchmark
case can report a capability gap. Corpus-wide ranking therefore covers four
projects, not five benchmark cases as well.

Closing this means running the planner over benchmark design documents, which
adds to what the benchmark measures. Treat it as a scoring-regime question — a
prior regime change moved a site from 79.4 to 59.4 with no quality change — not
as an extension of the report.

**TC-106 done (2026-08-10), and it needed no regime change at all.** The premise
was wrong: closing this does not require the planner. A match already knows
which requirements its chosen template cannot meet, and the planner copies
exactly those strings into an entry's warnings, so the report reads matches for
corpus cases and plans for projects and both speak one vocabulary. The benchmark
computes what it always did — its aggregate is byte-identical — because nothing
was added to it. The corpus was dark for thirty-odd iterations and had **seven
gaps in it**, including the measured evidence TC-104 was waiting for.

### TC-108 — One editorial part, two field names, and neither reaches the other

**Dependencies:** none

Two templates declare `eyebrow` (`bio-about`, `video-feature`) and five declare
`subtitle` (`class-photo-cards-4up`, both splits, both CTAs). `eyebrow` aliases
only to `eyebrow` and `subtitle` only to `subtitle`, so a section carrying one
can never reach a template offering the other.

The distinction is real — an eyebrow opens above the headline, a subtitle
follows it — but nothing in the library says which of the two a given slot
renders, and the extractor only ever emits `subtitle` for a deck and `eyebrow`
for a kicker. On `keys-to-success` that leaves the kicker unbindable by the
template the page was built from.

Two things to establish before changing anything. Whether each declaring
template's slot actually sits above or below its heading — `class-photo-cards-4up`
ships "Our Classes" as the sample copy of its **`section_title`** slot and the
descriptive line as its `subtitle`, which is the opposite of what the names
suggest. And whether the alias table or the template declarations are the thing
to correct.

**TC-108 done — agency pack 1.9.0 (iteration 67), and the filing was half
wrong.** Reading all seven component trees settled it: six templates place the
second heading below the first and five of those correctly call it `subtitle`;
`video-feature` places its `eyebrow` first and is correct. **Exactly one
template was misnamed** — `bio-about` declared an `eyebrow` in the slot *below*
its title, with "Jane Smith, Founder & CEO" as its own sample copy. That is a
subtitle. It is now called one.

The alias table needed nothing, and `class-photo-cards-4up` is correctly named:
"Our Classes" over "Explore our most popular classes" is an ordinary title and
subtitle. It only looked inverted because the `keys-to-success` page used those
two slots for a kicker and a headline.

### TC-113 — A `gallery` section builds no repeat group, and the obvious fix loses content

**Dependencies:** none. **Filed rather than fixed — the naive fix is worse.**

`oasis-probe.section.4` is a gallery: an eyebrow, a heading, and seven linked
photographs. It matches `Content/video-feature` at **0.4827, low**, warning that
"media needs 7 slots, template owns 1".

The cause is an omission in `html_ownership._CARD_GRID_REPEAT_KIND`, which lists
`project_gallery` but not `gallery`. Without an entry the section builds no
repeat group, so every gallery template scores as though the section repeated
nothing and a one-picture video feature wins. The corpus's `project_gallery`
section does build a group and reaches `gallery-3up` at 0.9164, which is what
this section should be doing.

**Adding `"gallery": "card"` to the map is not the fix.** Measured: the section
then routes correctly to `Cards/gallery-3up` at 0.8643 high, and coverage rises
0.087 → 0.167 — while the design document loses the eyebrow, the heading and
five of the seven pictures. `repeating_subtrees` finds two like-signature
subtrees in this markup, the enrichment branch keeps only those, and everything
else is never emitted. **No loss warning is raised, because the content is not
dropped at binding — it is never extracted.** Coverage went up while content
went missing, which is the one direction the loop's usual alarm cannot see.

The real fix has to make the pictures items *without* discarding what is not one
of them. That is a change to how a card grid's leftovers are handled, not a map
entry, and it deserves its own iteration with the retention check in front of it.

**TC-113 done, and it was never about leftovers.** Re-measuring the naive change
gave the same collapse — retention 31 → 21, the section down to two items — and
showed why: `repeating_subtrees` was picking two `div.White` layout bands, one
holding a single picture and the other holding all six cards. Everything else
counted as inside a repeat item and was never emitted. The candidates were all
there one level down: six `div.col-sm-4`, one picture each. The rule ranked by
depth first, so the shallowest thing that happened to repeat won. **It now ranks
by how many times a signature repeats, with depth only breaking a tie**, which
keeps the original rule that a card is the card rather than the box inside it.
No map entry was needed at all. Retention **393 → 412** with no project losing an
element.

### TC-114 — One pull-quote makes a whole page testimonials, and the careful rule is overridden

**Dependencies:** none. **Filed rather than fixed — the fix needs TC-115 first.**

`oasis-lighting` is one page holding a heading, six photographs, three
paragraphs, four links and a single pull-quote. It is classified `testimonials`
and matched to `Cards/testimonial-cards-3up`, losing the photographs, the copy
and every link — three dropped fields on one section.

`static_role` returns `testimonials` for *any* element containing a
`<blockquote>`, with no count and no test for competing content. The legacy
`_classify_section` has always been careful here — "A blockquote only signals a
testimonial section when quotes are the point: several of them, or a lone quote
with no competing gallery/cards" — and calls this page a gallery. **The careful
rule is overridden by the careless one**, because a static role outranks the
other classifier whenever it returns anything but `rich_text`. That is the same
shape as the `<article>` finding in evidence 1/7, and this is its second
instance.

The corpus is safe from the correction: its two blockquote sections carry two
and three quotes.

**Applying it costs content anyway, which is why it is filed.** With the rule
corrected the section stops being testimonials — and retention falls from 25
elements to 23, because the pull-quote is an `<h3>` inside the blockquote and
nothing else picks it up. See TC-115.

**TC-114 done, once TC-115 had cleared the way and one more hole was closed.**
With headings preserved the pull-quote survives, but retention still fell by one:
the attribution `<cite>Walt Whitman</cite>` was read by the testimonials branch
alone, so it left the document the moment the section stopped being testimonials.
A `<cite>` or `<figcaption>` that no repeated item owns is now kept wherever it
appears. Retention holds at **416 with no project losing an element**.
`oasis-lighting` reclassifies from `testimonials` to `hero` — the pre-existing
rule for a first content boundary carrying an `<h1>`, not something this change
introduced. Whether it should be a gallery is TC-113's question. A document-level loss is worse than a
binding-level one: a dropped field is visible in the report and fixable by
widening a template, while content that never reaches the design document cannot
be recovered downstream at all.

### TC-115 — A non-repeat section keeps two headings and silently drops the rest

**Dependencies:** none. **Blocks TC-114.**

Enrichment emits a section's most prominent heading as `section_title` and, at
most, one smaller heading above it as `eyebrow`. Every other heading in a
non-repeating section is never emitted. On `oasis-lighting` that is the page's
pull-quote, written as an `<h3>` inside a `<blockquote>`.

This is invisible to every check the loop runs. It is not a dropped field, so no
plan warning names it; it is not a coverage change, because the element never
reaches the document to be counted; and no project reports retention.

Fixing TC-114 without this would trade a misclassification for a silent loss.

**TC-115 done.** Every heading a section owns is now emitted; the ones that are
neither the title nor the eyebrow carry the role `subheading`. Retention across
the ten projects rose **398 → 416** with no project losing an element. The two
alias tables disagreed as well — binding has always accepted a `subheading` for
a `subtitle` field while matching did not know the word — so
`section_capability_aliases` now agrees with `binding_field_aliases`, and some of
the recovered headings bind rather than merely arriving.

### TC-116 — A link with no text is counted as a call to action

**Dependencies:** none. **Filed rather than fixed — extraction, and the loop has
reverted two of those already.**

`wwo.section.5` reports five `primary_action` elements. Two are real — an email
link and a telephone number. **Three are social icons whose anchors carry no
text at all**, Facebook, Twitter and Google+.

`html_ownership` emits `primary_action` for every `<a href>` it finds, with no
test that the anchor says anything. Both measurement scripts already know
better: they were brought into agreement in iteration 55 on exactly this point,
requiring an action to carry a label, because "an action with no label is not the
call" and a thumbnail wrapped in a link must not supply the accent colour. The
extractor was never given the same rule.

The consequence is visible here: a section reads as carrying five calls to
action where it has two, and its match is scored against that.

Fixing it removes elements from the design document, which is the direction the
loop has twice reverted. The removed elements carry no visitor-facing text — but
they do carry hrefs, and whether a social profile URL is content worth keeping is
the question to settle first.

**TC-116 done, and the textless anchors turned out to be three different things.**
Measured across the projects: some carry an accessible name in `aria-label` or
`title`; some wrap a picture, which is their label; and a few — `mm-close`,
`mm-next`, `mm-prev` — have no text, no name and no picture at all. So an action
now takes its accessible name when it has no text, a picture wrapped in a link
records its destination on the picture rather than arriving twice, and an anchor
with nothing to read anywhere is not emitted. **Blank actions fell from twelve to
zero and 27 pictures gained a destination they never had.**

### TC-118 — A project reports no retention, so silent content loss is invisible

**Dependencies:** none. **Blocks nothing formally, but every extraction repair
needs it first.**

`visitor_content_retention` exists only in `design/metrics.py`, for the benchmark
corpus, which has annotations to compare against. A project's
`analysis-report.json` carries sections, assets, pages, confidence and warnings —
and no count of content at all.

Coverage answers a different question. It is the share of *arriving* content that
reached a template field, so a section can lose five pictures and two headings
during extraction and see its coverage **rise**, because the ratio is taken over
what is left. That happened three times while repairing this pipeline, and each
time it was caught only by counting elements by hand.

**TC-118 done.** `analysis-report.json` now carries `content_elements` and
`content_elements_by_section`. Every element is counted, including those with no
text value — a picture is exactly that, and pictures are what went missing.

Baseline across the ten projects, **398 elements**:

| project | sections | retained |
|---|---|---|
| `cmw-blog` | 2 | 50 |
| `contact-page` | 2 | 13 |
| `oasis-probe` | 5 | 32 |
| `oasis-lighting` | 2 | 25 |
| `wwo` | 5 | 34 |
| `post-security` | 2 | 25 |
| `rendered-home` | 7 | 79 |
| `edca-pilot` | 4 | 23 |
| `kts-fidelity` | 11 | 90 |
| `northstar-recheck` | 5 | 27 |

### TC-119 — A paragraph that is only a link arrives twice

**Dependencies:** none. **Pre-existing, found while measuring TC-113.**

`rendered-home.section.5` reports twelve elements reading "Read More" where the
source has six anchors — six as `primary_action` and six as `body`. A paragraph
whose whole content is a link is emitted as body copy, and the link inside it as
a call to action.

Confirmed pre-existing: the section holds 34 elements and 12 "Read More" both
before and after TC-113's change, so it is not that fix's doing.

The paragraph is the link. Which of the two should survive is the question —
probably the action, since it carries the destination — and the count is the
measure of the fix.

### TC-117 — The report ranks gaps from matches the matcher does not believe

**Dependencies:** none. **Filed with a measurement, not fixed.**

Of the seventeen entries in the ranked queue, **seven come from sections whose
match the matcher scored `low` confidence**. The pipeline already says it does
not believe those pairings, and the report ranks the resulting losses as missing
fields regardless.

The corpus has an answer key and a loss on a wrongly matched section is held back
as a routing defect. A project workspace has none, so the same loss reads as a
capability gap — which is how `rendered-home`'s two testimonial sections, matched
to `cta-split` at 0.3794 and 0.4941, produced entries asking for a CTA that holds
thirteen actions, six pictures and fifteen paragraphs.

Confidence is the signal a project *does* have, and the report ignores it.

**Not a simple hold-back.** A low-confidence match can still be the right
template with a real gap behind it, so suppressing on confidence alone would hide
genuine work. The question is whether such an entry should be ranked lower,
marked, or held — and that needs measuring against a queue, which is its own
iteration.

**TC-117 done: held per SECTION, not per gap.** Measured against the queue as it
stood after five repairs, six of twenty-two entries rested on a low-confidence
match and *no* gap rested on a high-confidence one. Four of the six were a single
misroute asking a call-to-action for fifteen body slots, seven actions and six
pictures. But the top entry, `rich-text`/`primary_action`, spanned four sections
across three sources with only one unbelieved — suppressing the entry would have
hidden the credible instances. Holding the section instead keeps it, at three.
Queue **22 → 17 gaps, 28 → 20 dropped fields**; retention unchanged at 412, as a
report-side change must leave it.

### TC-112 — Add measured sources until the held items have a second section

**Dependencies:** none. **This is what unblocks TC-104, TC-109, TC-110 and TC-111.**

Everything left in the queue is held for the same reason: one section of
evidence, and the rule is not to widen a template for one page's editorial
choice. That is not a blockage to argue past — it is a shortage of measured
sources, and the fix is more of them.

Seven captured pages already sit in `artifacts/migration/` from sites benchmarked
before: `cmw-blog`, `contact`, `oasis-lighting`, `oasis-probe`, `post-security`,
`rendered-home`, `wwo`. (`edca-home.html` is byte-identical to the source
`edca-pilot` already uses, so it adds nothing.) They are real pages, so they are
honest evidence — unlike a fixture authored to want the shape being tested for,
which would be rigging the answer.

**One source per iteration.** Add it as a project, analyse and plan it, then
re-run the ranked report and record which held items gained a section. When one
reaches two sections on two sources it stops being one page's quirk and becomes
a shape the library should meet, and that iteration closes it in a governed
release under the ordinary rules.

**Acceptance criteria**

- Each iteration adds exactly one source and reports what the queue did.
- A held item promoted to two sections is released; one that stays at one is
  left alone and said so.
- No benchmark annotation, fixture or threshold edited to make an item promote.
- The ten corpus metrics and all three real sites reported every iteration.

### TC-110 — Four corpus sections carry a list their template cannot hold

**Dependencies:** none. **Held on evidence, not blocked.**

`harbor.about` carries two bullets ("Documented handoffs", "Plain-language
reporting") and matches `split-media`. `riverkind.cta` carries two event types
("Weekday crews", "Weekend crews") and matches `cta-banner`. Both templates are
named by the sections' own annotations as acceptable, and **neither declares a
repeat group at all** — so the list has nowhere to go.

The report used to rank these as four separate missing fields —
`item.benefit`, `item.text`, `item.event_type`, `item.label` — which invites
adding `item.event_type` to a banner that repeats nothing. They are now held
back, because a per-item field on a non-repeating template has no item to
attach to.

The real question is whether a split or a CTA should be able to carry a short
list, and it is one question rather than four fields. Two sections, two
families. Re-open when a third source wants the same shape, or when someone
decides the families should repeat.

### TC-111 — A logo's name and a process step's title have nowhere to go

**Dependencies:** none. **Held on evidence, not blocked.**

The two `item.*` gaps that survive are on templates that *do* repeat, so the
field really is missing rather than misplaced:

- `Content/logo-bar` repeats `logo` and declares only `item.media`;
  `figma-auto-layout-saas` gives each logo a label.
- `Content/stats-band-3up` repeats `stat` and declares `item.value` and
  `item.label`; `html-elementor-studio`'s process steps give each item a number
  and a title, and the title has no field.

The second is correctly routed, and measurably so: `icon-feature-list` is also
acceptable for that section and would lose *two* fields where the stats band
loses one, so the matcher chose the template that keeps more — a choice pack
1.10.0 improved by giving the band a section title.

One section each. Same discipline as TC-109.

### TC-109 — No card template can hold a kicker, and one section wants one

**Dependencies:** none. **Held on evidence, not blocked.**

`keys-to-success.section.5` opens with "Our Classes" above "MOST POPULAR
CLASSES". No card template declares `eyebrow`, so the kicker is dropped. It is
the last entry in the ranked report and the only content any tracked project
still loses to a missing field.

**Deliberately not closed at one section.** Adding `eyebrow` to
`feature-cards-4up` alone would break the family symmetry TC-105 now asserts;
adding it to all eight card templates is a large capability change for a single
data point, which is what pack 1.6.0's unmeasured half already cost. Routing
does not rescue it either: the template this page was built from,
`class-photo-cards-4up`, has no eyebrow field, and its second heading is a
subtitle. The page put a kicker where its template expects a headline.

Re-open when a second section on any site wants a kicker above a card grid.
That makes it a shape the library meets rather than one page's editorial choice.

### TC-105 — Family symmetry becomes a test

**Dependencies:** TC-103, TC-104

Assert that templates sharing a repeat kind declare the same section-level
fields, with deliberate exceptions declared in the test. This is what turns the
work above from six fixes into a property.

**TC-105 done (iteration 65).** Two tests, because "the same repeat kind" turned
out to be two properties of different strength.
`test_one_design_at_two_widths_holds_the_same_things` compares templates whose
ids differ only by their count suffix — the sharp property, and the one the
problem statement leads with. It has exactly one exception:
`blog-post-cards-3up` lacks the `section_body` and `action` that `-4up` has.
`test_templates_repeating_the_same_kind_offer_the_same_section_fields` is the
broad one, with four declared exceptions. Both were proved to fail by removing a
declared exception and watching the assertion fire.

The four unmeasured asymmetries stay listed rather than closed. A test whose
exceptions are honest is worth more than a release nobody measured.

## Completion rule

Passing tests or shipping one pack release does not complete this goal. It
remains active until TM1–TM4 are implemented, the gap report is empty across the
corpus and all three real sites, and the symmetry test makes the next accidental
asymmetry a failing check rather than a discovery.

## Progress log

### 2026-08-12 — the duplication metric was wrong, and the real number is ten

Took TC-126. Measuring it first corrected the instrument that produced it, and
the correction matters more than the repair.

**"Surplus copies" was not a defect metric.** I introduced it last iteration as
"elements whose value duplicates another element's", counted 61 in the baseline,
and killed a change for raising it to 74. Reading what those 61 actually are:
kts-fidelity's blog grid holds four cards with **identical placeholder copy**
("Blog titles comes over here" ×4, "Music" ×4), and rendered-home's six blog
cards each carry a "Read More". **A page is allowed to say the same thing twice.**
The metric could not tell repetition from double-emission, which is the only
thing worth counting.

**The right test is whether the document holds more copies of a value than the
source subtree contains occurrences of it.** By that measure the baseline has
**10 double-emitted elements, not 61** — and the change I reverted last
iteration would have to be re-measured against this before anything is concluded
about it.

**Of the 10, four were mine.** A footer contact list writes
`<li><a href="mailto:…">info@…</a></li>`, and the list emission I added two
iterations ago (a list survives whatever the section is) never inherited
TC-119's rule, so the address and the telephone arrived as a `benefit` *and* as
the `primary_action` that carries the destination. The same rule, one level down.

**Retention 461 → 457, and the fall is the point.** All four are named:
`[email protected]` and `(248) 690-6559` on wwo, `info@clicksandmortarwebsites.com`
and `(248) 690-6559` on rendered-home — each still present as a `primary_action`
carrying its `mailto:` or `tel:` href. **Double-emission 10 → 6.** Capability
queue 24 → 23, losses fall on both projects.

**TC-126 as filed is not the mechanism, and TC-125's revert needs revisiting.**
The filing said `extract_sections` emits a normalized paragraph twice, and it
does — `_extract_post_meta` prepends a meta line built from `div.detail-date`,
carrying a comment that says paragraph extraction "never sees" it, which stopped
being true when `normalize_text_blocks` began rewriting that div. But that
duplicate reaches the **raw content only**: post-security's section is claimed,
enrichment rebuilds from the subtree, and the meta line never reaches the
document. It is a real staleness to fix, not a blocker for TC-125 — and the
reason TC-125 was reverted was a metric that counted four identical cards as a
fault.

**Filed TC-127** for the remaining 6: `rendered-home`'s testimonials section
holds six `<blockquote>`s and emits twelve `testimonial_quote` elements, both
copies in the same group.

**Three mutations, three distinct failures** — link-only items emitted again,
every item holding a link skipped, repeat-owned items emitted again.

**Evidence.** Suite 2,262 → 2,264 passing, 16 deselected. Corpus identical on all
ten metrics.

| site | elements | Δ | dropped | thin | double | coverage | blocking | valid |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 61 | 0 | 2 | 1 | 0 | 0.0 | 2 | false |
| `contact-page` | 20 | 0 | 3 | 0 | 0 | 0.5455 | 1 | false |
| `oasis-probe` | 32 | 0 | 0 | 0 | 0 | 0.087 | 4 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0 | 0 | 0.0 | 1 | false |
| `wwo` | 40 | **−2** | 1 | 0 | 0 | 0.0968 | 4 | false |
| `post-security` | 27 | 0 | 2 | 1 | 0 | 0.0 | 2 | false |
| `rendered-home` | 97 | **−2** | 1 | 0 | 6 | 0.0909 | 6 | false |
| `edca-pilot` | 24 | 0 | 0 | 0 | 0 | 0.6923 | 0 | true |
| `kts-fidelity` | 107 | 0 | 0 | 0 | 0 | 0.4691 | 3 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0 | 0 | 0.8182 | 0 | true |

### 2026-08-12 — a repair measured, built, and reverted: half the gain was duplication

Took post-security's two runs. The mechanism was clean, the fix was small, it
raised retention on six projects — and it does not ship, because measuring what
the rise was *made of* showed half of it was duplicate elements.

**The defect is real.** `normalize_text_blocks` rewrites a text-bearing div into
a `<p>` and disqualifies any div with an element child. "Has a child" stands in
for "is a wrapper", and a paragraph routinely carries inline markup: post-security
writes its date badge as
`<div class="detail-date">21 <span class="month">Sep</span></div>`, so the badge
reached no element. Instance 31 of the oldest recurring mistake, and the fix is
one the codebase already has a name for — `_PHRASING_TAGS` in `html_ownership`
means exactly "sits inside a line of text".

**Implemented and measured.** 70 divs across the ten sources newly qualify.
Retention **461 → 486, no project down**; post-security's thin section resolves;
the capability queue grows **24 → 30**, with `Content/rich-text`/`body` reaching
two projects as `insufficient_capacity`. Corpus identical on all ten metrics. By
every number this loop normally reads, it passed.

**Then I counted what arrived.** Surplus copies of a value across the ten
projects: **61 → 74**. Thirteen of the twenty-five new elements are the *same
text twice*, and reproducing it without my change proved why:

```python
extract_sections("… <div id='dnn_TopPane' class='Pane'><h2>Serious</h2>"
                 "<div class='detail-date'>21 Sep</div></div> …")
# -> paragraphs: ['21 Sep', '21 Sep']
```

`_extract_content` on the same pane returns **one** paragraph. `extract_sections`
adds the second — a pre-existing double-count that a plain leaf div triggers just
as well. My change did not create it; it routed seventy more divs through it.

**So the change is reverted and both halves are filed** — TC-126 for the
double-count, TC-125 for the phrasing rule, with TC-126 blocking it. Shipping
TC-125 first would have raised the number the whole loop steers by using content
that is not there.

**What this says about the instrument.** Retention has been the arbiter for
fourteen iterations and it has been right every time — but it counts elements,
not distinct content, and nothing has ever checked the difference. **61 surplus
copies exist today, in the baseline**, and no alarm mentions them. The
within-boundary alarm cannot see it either: it asks whether a source run reached
*any* element, so a run that reached two looks perfect.

**Kept from the iteration:** the four TC-122 fixtures now use a table cell rather
than a `<div class='meta'>`. They expired for the second time — the phrasing fix
made their "lost" content arrive — and a table cell is dropped whether or not
TC-125 ever lands, so they will not expire again for this reason.

**Baseline confirmed restored:** retention 461 on every project, edca-pilot
`valid` again, kts blocking back to 3, queue back to 24. Suite 2,262 passing,
corpus identical.

### 2026-08-12 — two findings I had filed twice were false, and a card title at h5

Took "a blocked section is invisible to the gap queue". **It is not, and neither
is the finding standing beside it.** Both had been carried in the queue for four
iterations on an inference I never measured.

**A blocked section has a plan entry, a template and warnings, and the queue
reads all of it.** kts-fidelity's `section.5` blocks *and* carries
`field 'item.body' has 2 values but owns 1 physical slots` four times over — and
that section is one of the two cited by the queue's current rank 1. The entries a
blocking section produces are not skipped anywhere. What actually has no entry on
kts is `section.1` and `section.12`: the navigation and the footer, which are
global blocks rather than blocked sections.

**And nothing was missing from the library either.** The seven photo-band
sections do not block because no template holds a lone background band.
`Heroes/photo-band` matches them at **content field compatibility 1.000**. They
block on this:

```
required field 'background_media' has 1 value(s) whose asset was never acquired,
so nothing loadable can be bound
```

The banner is a `file:///Portals/0/adam/Content/…` reference in a saved capture
that resolves to nothing. **That is a fixture limitation, not a capability gap** —
and the queue entry it was going to justify would have been a governed pack
release for a template that already does the job. Both findings are struck.

The original observation was true and the conclusion drawn from it was not:
"seven sections block and the queue shows none of them" is a fact about *which*
sections, not about blocking. Reading one warning would have settled it four
iterations ago.

**With the measurement done, took the next item: rendered-home's three runs.**
`#dnn_TopOutPane` writes its feature cards with `<h5>`, and the card branch reads
`item.find(["h2", "h3", "h4"])`. The section-level search has covered h1 through
h6 since h5/h6 extraction was fixed for sections; the card branch was never
widened with it, so three card titles reached nothing.

**Retention 458 → 461, no project down.** rendered-home **+3**, its thin section
gone, blocking 7 → 6 and coverage 0.0460 → 0.0889 as the titles now bind.
**Thin sections 3 → 2, runs lost 22 → 19.** Capability queue holds at 24.

**Scope creep I caught and reverted.** I widened `process_steps`' heading search
in the same edit. No fixture covers it, no project exercises it, and it was not
the task — the mutation sweep found it by passing, and it is back as it was.

**Three mutations, two distinct failures and one equivalent mutant.** Narrowing
the card heading back to h2–h4 fails; adding `h1` to the list passes, and is
equivalent on all available evidence — no card in any fixture or project carries
an `<h1>`, and a page-level h1 never sits inside a card. Said rather than
papered over with a contrived fixture, as with TC-123's `match`/`search`.

**Evidence.** Suite 2,261 → 2,262 passing, 16 deselected. Corpus identical on all
ten metrics.

| site | elements | Δ | dropped | thin | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 61 | 0 | 2 | 1 | 0.0 | 2 | 1 | false |
| `contact-page` | 20 | 0 | 3 | 0 | 0.5455 | 1 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 0 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0 | 0.0 | 1 | 1 | false |
| `wwo` | 42 | 0 | 1 | 0 | 0.0909 | 4 | 5 | false |
| `post-security` | 27 | 0 | 2 | 1 | 0.0 | 2 | 2 | false |
| `rendered-home` | 99 | **+3** | 1 | **0** | 0.0889 | 6 | 11 | false |
| `edca-pilot` | 24 | 0 | 0 | 0 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 107 | 0 | 0 | 0 | 0.4691 | 3 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0 | 0.8182 | 0 | 0 | true |

**Remaining:** post-security's 2 (a date badge split into `21` and `Sep` across a
`div.detail-date` and a `<span class="month">` — a different mechanism from
TC-123's, which reads a whole date from one line), cmw-blog's 17, TC-121 answers
2 and 3, and the form placeholder.

### 2026-08-12 — TC-124: the overflow was already reportable, and I had orphaned it

**The filing was wrong about the mechanism.** It said an item-field overflow "is
reported by nothing". The planner has reported it all along:

```python
if len(candidates) > contract.slots_per_owner:
    issues.append(f"{section.id}/{item.id}: field '{semantic_field}' has "
                  f"{len(candidates)} values but owns {contract.slots_per_owner} physical slots")
```

It never fired because `candidates = _item_elements(item, elements, field)` reads
the elements the **item's field names**, and last iteration I emitted the extra
card paragraphs with a `group_id` but left them out of `fields`. They reached the
document and were invisible to the plan — orphans inside their own group.

**And the home already existed, again.** `RepeatGroupItem.fields` is typed
`dict[str, str | list[str]]` and `_item_elements` already does
`ids = [identifiers] if isinstance(identifiers, str) else identifiers`. Nothing
needed inventing — the field just had to name every paragraph it was given. Third
iteration running where the fix was to use a contract that was already there.

**The queue gained exactly the entry this loop produced the evidence for.**
22 → 24 gaps, and **rank 1 is now `Cards/feature-cards-4up` / `item.body`**:
`kind: insufficient_capacity`, `owned_slots: 1`, `demanded_slots: 2`, across
**two projects and two sections** (kts-fidelity and rendered-home) — which is the
two-source bar a governed release needs. `Cards/blog-post-cards-4up` / `item.body`
joins it.

**Retention unchanged at 458 on every project**, which is correct: this names
content that already arrived. Dropped boundaries hold at 9 and thin sections at
3.

**The cost is real and is the established regime.** An overflow blocks its
section, so kts-fidelity goes 1 → 3 blocking (coverage 0.8148 → 0.4691) and
rendered-home 6 → 7 (0.1954 → 0.0460). That is exactly what a *section*-level
overflow has always done — edca-pilot blocked on `split-media` until pack 1.8.0
widened it from one body slot to three, and then went valid. The difference now
is that the queue says which template to widen instead of the loss being a
coverage number nobody can attribute.

**A mutation that unit tests could not catch, and the corpus could.** Making the
field *always* a list passed all 323 unit tests. The corpus compares
`actual_reference == corresponding.id` against a single id string, so every
annotated card's binding broke: `group_field_association_accuracy` **79/79 →
70/79** and the benchmark failed its threshold. The right fixture for a
serialisation contract the annotations encode is the corpus, not a unit test —
and a mutation sweep that only runs `pytest` will call that rule unproven.

**Six further mutations, six distinct failures** — extras left out of the field,
the field never set, the bound paragraph no longer first, the date joining the
body field, the gallery using the body field name, and the gallery emitting
`card_body` instead of `eyebrow`. The last two needed a new fixture: the field
name is now chosen outside the guard that emits the paragraph, so `project_gallery`
keeping `type`/`eyebrow` had to be pinned.

**Still unaddressed and now clearly the same shape:** a **blocked** section
produces no gap entry, because the report reads matched entries. Every section
this change blocks is one the queue can no longer see for any *other* field it
loses. The two findings want one answer.

| site | elements | Δ | dropped | thin | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 61 | 0 | 2 | 1 | 0.0 | 2 | 1 | false |
| `contact-page` | 20 | 0 | 3 | 0 | 0.5455 | 1 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 0 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0 | 0.0 | 1 | 1 | false |
| `wwo` | 42 | 0 | 1 | 0 | 0.0909 | 4 | 5 | false |
| `post-security` | 27 | 0 | 2 | 1 | 0.0 | 2 | 2 | false |
| `rendered-home` | 96 | 0 | 1 | 1 | 0.0460 | 7 | 12 | false |
| `edca-pilot` | 24 | 0 | 0 | 0 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 107 | 0 | 0 | 0 | 0.4691 | 3 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0 | 0.8182 | 0 | 0 | true |

**Evidence.** Suite 2,260 → 2,261 passing, 16 deselected. Corpus identical on all
ten metrics.

### 2026-08-12 — a card is allowed more than one paragraph

Took kts-fidelity's two thin sections. They looked like two small, separate
losses — one run each — and measuring showed **one mechanism**.

- `#tpl-cpc-s1`, a class card: two paragraphs, `Age 0-5 yrs` and
  `Canta y Baila Conmigo is a unique program…`. The description was dropped.
- `#tpl-bpc4-s1`, a blog card: three paragraphs, `Music`, a `Lorem ipsum` body
  and `By Richard Clarkson | April 2, 2024`. The byline was dropped.

The card branch reads `body = next(paragraph for paragraph in paragraphs if
paragraph is not published)` — **exactly one**. Everything after the first is
discarded. The blog card's byline is not a bare date, so TC-123's rule does not
catch it; and neither is a duplicate of anything, so the alarm was right to
report both.

`item.body` owns one slot per card, so the first non-date paragraph keeps the
binding and the rest arrive as content grouped with the card that carried them.
Group membership matters and is asserted: it is what says which repeated thing a
value came from, and the corpus scores the pipeline on getting it right.

**Retention 440 → 458, no project down.** kts-fidelity **+12** and rendered-home
**+6** — the same mechanism on both. **Thin sections 5 → 3, runs lost 24 → 22,
and kts-fidelity now reports none at all.**

**The cost, and it is worth stating precisely.** kts's coverage falls 0.9565 →
0.8148, because cards now offer two and three paragraphs into a one-slot field.
That is the TC-115 shape and expected — but the plan holds **no warning, no loss
entry and no issue** about it. A *section*-field overflow says `X needs N slots,
template owns M`; the same overflow one level down says nothing, so the only
trace is the coverage number itself. Filed as **TC-124**: it is the same finding
as "a blocked section is invisible to the gap queue", and it means the capability
queue cannot rank the one gap this change just produced evidence for.

**Five mutations, five distinct failures** — extras not emitted, the bound body
emitted twice, the date emitted twice, extras taking the body binding, extras
losing their group. The last needed an assertion added: nothing had pinned that
an extra paragraph belongs to its card rather than to the section.

**Evidence.** Suite 2,258 → 2,260 passing, 16 deselected. Corpus identical on all
ten metrics, `group_field_association_accuracy` included at 79/79 — which is the
metric a wrong group would move.

| site | elements | Δ | dropped | thin | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 61 | 0 | 2 | 1 | 0.0 | 2 | 1 | false |
| `contact-page` | 20 | 0 | 3 | 0 | 0.5455 | 1 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 0 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0 | 0.0 | 1 | 1 | false |
| `wwo` | 42 | 0 | 1 | 0 | 0.0909 | 4 | 5 | false |
| `post-security` | 27 | 0 | 2 | 1 | 0.0 | 2 | 2 | false |
| `rendered-home` | 96 | **+6** | 1 | 1 | 0.1954 | 6 | 12 | false |
| `edca-pilot` | 24 | 0 | 0 | 0 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 107 | **+12** | 0 | **0** | 0.8148 | 1 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0 | 0.8182 | 0 | 0 | true |

**Remaining:** cmw-blog's 17 (author and category links, held on the one-slot
question; `Read More >`, which TC-119 deliberately removed), post-security's 2,
rendered-home's 3, TC-121 answers 2 and 3, and the form placeholder.

### 2026-08-12 — an address and a list, whatever the section turns out to be

Took contact-page's five remaining runs. **The filing was half wrong, and the
half that was right was in the wrong layer** — which is the third time in this
goal a filed diagnosis has needed re-measuring before it could be designed
around.

**What the filing got wrong.** It said a list item "yields its `<strong>` label
but drops the value beside it". The raw extractor reads the whole thing:
`'Phone : (248) 690-6559'`. The value is lost later, by `_stat_parts`, because
the section is enriched as a **stats band** — and the reason it is a stats band
is this, in `static_role`:

```python
if "stats" in hints or len(element.select("li strong")) >= 2:
```

**Two `<li><strong>` make a stats band.** A contact block writes
`<li><strong>Phone :</strong> (248) 690-6559</li>`, which has exactly that shape.
Instance 30, and `is_stat_value` — which already knows that a stat is a short
token carrying no letters — says `Phone :` is not one. The rule now asks it.

**What the filing got right, in the wrong place.** `<address>` genuinely is not
read. I fixed it in `_extract_content` first, measured, and found it changed
nothing: **enrichment rebuilds a claimed section's content from its subtree**, so
the raw extractor's paragraphs never reach a claimed section at all. It needed
fixing in `html_ownership` — and in `_extract_content` too, because the container
rule now deliberately leaves sections unclaimed and those keep raw content.

**And a third cause the measurement exposed, which nearly cost me the whole
change.** Correcting the classification made contact-page **worse** — 19 → 16 —
while coverage *rose* 0.5 → 0.71. Exactly TC-113's trap, caught by the same rule.
Testing every candidate role against the panel's markup showed why: **only the
`stats` and `split_feature` branches ever read an `<li>` at all.** The contact
list had survived solely because the section was misread, and correcting the
misreading took the list with it. A list is content whatever the section is, so
one is now emitted whenever no repeat group claims it.

**Retention 429 → 440, no project down.** contact-page +1 and its thin section is
gone: the panel now holds the joined address and all three list items **with
their values**. wwo +2 and rendered-home +8 from lists those sections had been
dropping for the same reason. **Thin sections 6 → 5, runs lost 29 → 24.**

**Nine mutations, nine distinct failures** — address unread by the enricher,
loose list items not emitted, claimed list items emitted twice, the stats rule
back to the bare shape, the class hint no longer believed, one stat item enough,
address dropped from extraction, and `_find_all_with_self` ignoring its list.

**Four fixtures had to be rewritten, and that is the lesson.** TC-122's tests
used `<address>` as their example of lost content. Fixing the loss invalidated
them — they began asserting that something arrives is missing. They now use a
bare text node beside an element child, which is still genuinely dropped. **A
fixture built from a defect expires when the defect is fixed**, and four failing
tests were the correct signal, not a regression.

**Evidence.** Suite 2,250 → 2,258 passing, 16 deselected. Corpus identical on all
ten metrics. All ten projects re-analysed with `--refresh --render`
(`execution.action == "execute"`) and re-planned with `--refresh`.

| site | elements | Δ | dropped | thin | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 61 | 0 | 2 | 1 | 0.0 | 2 | 1 | false |
| `contact-page` | 20 | +1 | 3 | **0** | 0.5455 | 1 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 0 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0 | 0.0 | 1 | 1 | false |
| `wwo` | 42 | +2 | 1 | 0 | 0.0909 | 4 | 5 | false |
| `post-security` | 27 | 0 | 2 | 1 | 0.0 | 2 | 2 | false |
| `rendered-home` | 90 | +8 | 1 | 1 | 0.2099 | 6 | 12 | false |
| `edca-pilot` | 24 | 0 | 0 | 0 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 95 | 0 | 0 | 2 | 0.9565 | 1 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0 | 0.8182 | 0 | 0 | true |

**Remaining:** kts-fidelity's two thin sections (11/12 and 6/7), cmw-blog's 17
(the author and category links, held because `item.tag` owns one slot per item,
and `Read More >`, which TC-119 deliberately removed), post-security's 2,
rendered-home's 3, TC-121 answers 2 and 3, and the form placeholder.

### 2026-08-12 — TC-123: a card's date is its date, not its body copy

**The mechanism, measured first.** A card grid read its item's body as
`item.find("p")` — the first paragraph in the card. `normalize_text_blocks`
rewrites a text-bearing leaf div into a `<p>`, and a cmw-blog card leads with
`<div class="list-date">Nov 13, 2017</div>`. So the date badge *was* the first
paragraph, and every one of the nine cards arrived carrying its date as body copy
while the excerpt in `div.list-description` was never read. Instance 29 of the
recurring mistake, in its oldest form: **the first paragraph is not the body.**

**The template already had the home.** `Cards/blog-post-cards-3up` declares
`item.media`, `item.tag`, `item.title`, `item.body` and `item.action`, and
`_ITEM_CAPABILITY_ALIASES` already routes a `tag` role to `item.tag`. Nothing
needed widening — the date has a slot, and the extractor simply was not filling
it. So: the date is emitted as the card's `tag`, and the body is taken from the
first paragraph that is *not* that date.

`is_publication_date` is now shared with `dated_card_kind`, which already had to
make the same judgement for a different purpose — recognising a blog listing *by*
its dates. Two spellings of "is this a date" would drift, the same reason
`is_builder_pane` was shared last iteration.

**Retention 419 → 429, +10 on cmw-blog and no project down.** Nine cards gained
their excerpt; the tenth element is the grid's own paragraph. **Thin sections
hold at 6 but cmw-blog's loss falls 28 → 17, and the total across all projects
falls 40 → 29.**

**What is deliberately still dropped, and why.** The remaining 17 runs on
cmw-blog are the author link (`CMW Team`), the category links (`Website Design`,
`Business Website`, `Tips`…), `Share`, and `Read More >`. Two separate reasons,
both measured rather than assumed:

- `item.tag` declares `slots_per_owner: 1` and a card carries up to four
  categories, so emitting them would overflow the slot the date now fills. Which
  of a date and a category list belongs in one tag slot is a real question and
  not this task's.
- `Read More >` is a **duplicate destination**. The card's picture, its title and
  that button are three anchors to one URL, and TC-116 already records the href
  on the picture. Emitting it would put back exactly what TC-119 removed.

**Five mutations, five distinct failures** — body taken as the first paragraph
again, the date never emitted, date detection removed, every paragraph read as a
date, the date predicate always false. A sixth (`match` → `search`) **passed and
correctly so**: every alternative in `_DATED_CARD` is anchored `^…$`, so the two
cannot differ. That is an equivalent mutant, not an untested rule, and building a
fixture for it would have meant inventing a difference that does not exist.

**Evidence.** Suite 2,247 → 2,250 passing, 16 deselected. Corpus identical on all
ten metrics. All ten projects re-analysed with `--refresh --render`
(`execution.action == "execute"`) and re-planned with `--refresh`.

| site | elements | Δ | dropped | thin | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 61 | **+10** | 2 | 1 | 0.0 | 2 | 1 | false |
| `contact-page` | 19 | 0 | 3 | 1 | 0.5 | 2 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 0 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0 | 0.0 | 1 | 1 | false |
| `wwo` | 40 | 0 | 1 | 0 | 0.0968 | 4 | 4 | false |
| `post-security` | 27 | 0 | 2 | 1 | 0.0 | 2 | 2 | false |
| `rendered-home` | 82 | 0 | 1 | 1 | 0.2329 | 6 | 10 | false |
| `edca-pilot` | 24 | 0 | 0 | 0 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 95 | 0 | 0 | 2 | 0.9565 | 1 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0 | 0.8182 | 0 | 0 | true |

**Remaining:** contact-page's five runs (`<address>` unread, and a list item
yielding its `<strong>` label without the value beside it), kts-fidelity's two
thin sections, TC-121 answers 2 and 3 (the footer strips and taglines), and the
form placeholder.

### 2026-08-11 — a boundary holding two sections is neither section's DOM

Took the biggest measured loss, which TC-122 had just made visible: wwo's
`#dnn_BottomPane` keeping 5 runs of 20, and cmw-blog's `#dnn_ContentPane`
keeping 42 of 70.

**The mechanism, measured rather than assumed.** wwo's pane is a pricing table —
two cards, each a heading, a price and a feature list. The **raw extractor reads
both correctly**: two sections carrying `Website Only – $99.95/month` with five
features and `Branding Package – $249.95/month` with eleven. The loss is entirely
downstream. There is one pane candidate and two sections, so the first card
claimed the pane that holds *both* and the second, with nothing left that
matched, claimed **`#dnn_FooterBottomPaneB`** — the footer. Enrichment then
rebuilds a claimed section's content from its subtree, so card one came back as a
flattening of both cards (two headings, one paragraph, no prices, no features)
and card two came back holding the footer's tagline, email and telephone.

Proved by experiment before designing: strip `_static_html` from those two
sections and they arrive intact — 6 and 12 elements, prices in the title, every
feature present.

**The rule.** A candidate whose text contains the words of two or more sections
is a container, not either section's DOM, and is withheld from claiming
altogether. This is the same contribution test `_without_wrappers` applies to
nested candidates and `_claims_the_chrome` applies to headers — the third member
of a family, not a new idea. Sections with no words are excluded from the count,
because an empty set is a subset of every boundary on the page and two image-only
panes would otherwise turn the whole document into containers.

**Retention 417 → 419.** wwo **+7** and its thin section is gone: the pricing
table arrives whole. `rendered-home` **−5, named and justified**: its
`#dnn_BottomPane` stopped being a flat `testimonials` list and became a proper
six-card blog grid (`card_media`/`card_title`/`card_body` per post), which
**gained** the real section heading `RECENT POSTS` — a run TC-122 had reported as
missing — and **dropped six `primary_action` "Read More" elements**. Every
destination survives: all six `/blog/post/…` URLs are carried as `href` on the
matching `card_media`, exactly the rule TC-116 established and TC-119 relied on.
Six duplicates out, one real heading in.

**Thin sections 9 → 6; runs lost 64 → 40.** Dropped boundaries unchanged at 9.
Coverage fell on wwo (0.1667 → 0.0968) as a whole pricing table arrived that no
template can hold, and rose on rendered-home (0.1538 → 0.2329) as a flat list
became a bindable card grid. Both directions in one change, and retention decided
it.

**Six mutations, six distinct failures** — container rule removed, one section
making a container, three sections required, wordless sections counted, subset
loosened to any overlap, containers withheld from claiming but not from the pool.

**Evidence.** Suite 2,244 → 2,247 passing, 16 deselected. Corpus identical on all
ten metrics. All ten projects re-analysed with `--refresh --render`
(`execution.action == "execute"`) and re-planned with `--refresh`.

| site | elements | Δ | dropped | thin | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 51 | 0 | 2 | 1 | 0.0 | 2 | 1 | false |
| `contact-page` | 19 | 0 | 3 | 1 | 0.5 | 2 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 0 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0 | 0.0 | 1 | 1 | false |
| `wwo` | 40 | **+7** | 1 | 0 | 0.0968 | 4 | 4 | false |
| `post-security` | 27 | 0 | 2 | 1 | 0.0 | 2 | 2 | false |
| `rendered-home` | 82 | **−5** | 1 | 1 | 0.2329 | 6 | 10 | false |
| `edca-pilot` | 24 | 0 | 0 | 0 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 95 | 0 | 0 | 2 | 0.9565 | 1 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0 | 0.8182 | 0 | 0 | true |

**Filed TC-123 for the loss this did not touch.** cmw-blog's 28 runs are a
different mechanism: each `article.list-post` keeps its picture, its title and
its **date** while dropping the excerpt paragraph, the author and tag links,
`Share` and `Read More >`. `card_body` received the date and the card's actual
prose was discarded — `dated_card_kind`, added to recognise a blog listing *by*
its dates, being taken as the body.

### 2026-08-11 — TC-122: the alarm follows the loss one level down

Took TC-122 over the remaining TC-121 answers. Answers 2 and 3 are chrome
policy; this is the instrument that makes their cost visible, and answer 4 had
just demonstrated that repairing a boundary moves the blindness rather than
removing it. Same order TC-118 established.

**The premise, measured before anything was built: within-boundary retention is
204/267 (0.764) across the nine local sources.** Sixty-three text runs are lost
inside boundaries that *were* claimed — seven times the nine boundaries the
TC-120 alarm reports. The biggest single case was invisible to every check:
wwo's `#dnn_BottomPane` keeps **5 of 20**, losing an entire pricing table
(`OUR PRICES`, `$`, `99.95`, `/month`, `Unlimited Web Pages`, `1 Add-On`,
`30 mins of Content Updates each month`…).

**The hold-back that would have destroyed the alarm.** A form is migrated as a
placeholder by policy, so form text is absent by design and must not read as
loss. The obvious test — "is this run inside a `<form>`?" — is **wrong on every
DNN page**: ASP.NET wraps the entire body in one `<form runat="server">`, so it
is true of `OUR PRICES` and `PORTFOLIO` as much as of a submit button. Measured
before implementing: **61 of the 63 losses would have been suppressed**. The rule
is ownership by a control *tag* (`label`, `button`, `option`, `select`,
`textarea`, `legend`), which holds back exactly the two runs that deserve it —
edca-pilot's `Security` label and `Send Now` button. Instance 28 of "an ancestor
tag is not a kind of thing".

**A second hold-back the first draft got wrong.** Chrome reported a loss on
contact-page: the header "kept 8 of 10", missing `Login`. A header is *rebuilt*
from its links by `_chrome_section`, not extracted from its markup, so a DNN
login control is absent by design. Held back by role, the same way
`unclaimed_boundaries` holds back chrome.

**A crash I caused and had to fix before the sweep would finish.** kts-fidelity
failed the analyze stage outright: `Malformed id selector at position 0:
#1f670a38`. `css_selector_for` emits `#<id>` verbatim and a real Vanjaro page
carries section ids beginning with a digit, which is not a valid CSS identifier —
`select_one` *raises* rather than returning nothing, and `SelectorSyntaxError`
was not among the exceptions caught. An id lookup needs no CSS grammar, so it no
longer uses one. **Worth its own note: the rendered observation script pairs by
`querySelector`, which cannot read that id either, so rendered pairing for those
sections has never worked.**

**What it now reports: nine sections across six projects, 64 runs lost, 125 of
189 kept on the sections that report.**

| project | section | kept | lost |
|---|---|---|---|
| `cmw-blog` | `#dnn_ContentPane` | 42/70 | **28** |
| `wwo` | `#dnn_BottomPane` | 5/20 | **15** |
| `rendered-home` | `#dnn_Full_Screen_PaneD` | 16/24 | 8 |
| `contact-page` | `#dnn_Full_Screen_PaneB` | 7/12 | 5 |
| `rendered-home` | `#dnn_TopOutPane` | 4/7 | 3 |
| `post-security` | `#dnn_ContentPane` | 17/19 | 2 |
| `rendered-home` | `#dnn_BottomPane` | 17/18 | 1 |
| `kts-fidelity` | `#tpl-cpc-s1` | 11/12 | 1 |
| `kts-fidelity` | `#tpl-bpc4-s1` | 6/7 | 1 |

**Ten mutations, ten distinct failures** — alarm unwired, reporting when nothing
is missing, form controls counted, a form ancestor holding back the page, chrome
reported, every section held back as chrome, runs not de-duplicated, arrival
checked by equality instead of containment, the skip hook ignored, comments
counted as offered text. Three needed fixtures built to isolate them: a repeated
line (a marquee is one loss, not twelve), copy split by an inline `<strong>`
(equality would report every emphasised sentence on the page as missing), and a
header carrying text chrome genuinely drops — the first chrome fixture asserted
"nothing reported" on a header that lost nothing, so it could not tell the rule
from its absence.

**Evidence.** Suite 2,236 → 2,244 passing, 16 deselected. Corpus identical on all
ten metrics (`visitor_content_retention` 127/127, `semantic_role_accuracy`
25/25). **Retention unchanged at 417 on every project**, coverage, blocking,
losses, dropped boundaries (9) and `valid` all unchanged — correct for a report
that adds a reader and touches no extraction.

| site | elements | dropped | thin sections | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 51 | 2 | 1 | 0.0 | 2 | 1 | false |
| `contact-page` | 19 | 3 | 1 | 0.5 | 2 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 0.0 | 1 | 1 | false |
| `wwo` | 33 | 1 | 1 | 0.1667 | 3 | 5 | false |
| `post-security` | 27 | 2 | 1 | 0.0 | 2 | 2 | false |
| `rendered-home` | 87 | 1 | 3 | 0.1538 | 6 | 7 | false |
| `edca-pilot` | 24 | 0 | 0 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 95 | 0 | 2 | 0.9565 | 1 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 0.8182 | 0 | 0 | true |

**Remaining:** TC-121 answers 2 and 3 (the footer strips and taglines — one
question in two shapes), the form placeholder, and the two findings this loop
turned up that belong to the capability goal rather than to extraction: a blocked
section is invisible to the gap queue, and nothing in the library holds a lone
background band.

### 2026-08-11 — TC-121 answer 4 of 4: a pane is a section even with no heading

Took the most valuable item left rather than the next one down: contact-page's
contact panel, three real elements by TC-120's count and the only entry in the
inventory that is unambiguously page content.

**Where it actually died.** `_top_level_sections` expands a dominant content
container only when two of its children look like sections, and
`_section_like_child_count` defined that as *a sectioning tag or a heading
somewhere inside*. `section#dnn_content` holds three children — the TopPane
wrapper, the contact panel, and the form wrapper — and **only one of them carries
an `<h#>` at all**, so the count was 1, the wrapper never expanded, and the whole
page arrived as one raw section holding all 66 words. That section then claimed
`#dnn_TopPane`, enrichment rebuilt its content from that pane alone, and the rest
was extracted and thrown away. `_is_multi_module_pane` fails for the same reason:
it requires every child to own a heading.

**A heading is not what makes something a section** — instance 27 of this goal's
oldest recurring mistake. What is actually true of those children is that they
are, or contain, a **builder-declared pane**: the editor put modules there
deliberately, and `static_boundary_candidates` has always treated that shape as
authoritative. So `is_builder_pane` now says it once, in `migration/sections.py`,
and both readings of a page import it — the third copy of a page's boundary rules
is exactly how the readings drift.

**Retention 412 → 417, no project down**, all five on contact-page (14 → 19). The
panel arrives as `#dnn_Full_Screen_PaneB` with its joined title, three labels and
the call button. Dropped boundaries **10 → 9**; contact-page 4 → 3, and the
boundary that stopped being reported is `#dnn_Full_Screen_PaneB` itself.

**A mistake I made and caught by measuring.** The first version wrote the
predicate with `casefold()`, which is broader than the browser's
`[id^='dnn_'][class*='Pane']` — a CSS attribute match is **case-sensitive**. The
two readings selected different panes and paired against each other's
boundaries: **oasis-lighting lost 6 elements and oasis-probe 4**, and the dropped
boundary count rose 10 → 17 rather than falling. The drift-guard test passed
throughout, because every class in its fixture was spelled `Pane`. Fixed to match
the selector exactly, and the fixture now carries a lowercase `pane` that fails
the loose reading.

**Seven mutations, seven distinct failures** — pane rule removed from the count,
only direct panes counted, case-insensitive match, id prefix ignored, every
element with an id treated as a pane, heading rule removed, candidates no longer
using the shared predicate.

**Filed TC-122, and it matters more than this repair.** The panel arrives and
**5 of its 12 text runs are still missing** — the whole `<address>` block and the
values beside the `Phone :`/`Email :`/`Twitter :` labels — while the boundary is
no longer reported at all. TC-120's alarm is boundary-level, so content lost
*inside* a claimed boundary is invisible again, and the section classified as
`stats` with the labels as its stat values. Repairing a boundary moves the
blindness one level down.

**Evidence.** Suite 2,233 → 2,236 passing, 16 deselected. Corpus identical on all
ten metrics. All ten projects re-analysed with `--refresh --render`
(`execution.action == "execute"`) and re-planned with `--refresh`.

| site | elements | Δ | dropped | provenance | styles | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 51 | 0 | 2 | 51 rendered | 93 | 0.0 | 2 | 1 | false |
| `contact-page` | 19 | +5 | 3 | 19 rendered | 124 | 0.5 | 2 | 2 | false |
| `oasis-probe` | 32 | 0 | 0 | 32 rendered | 186 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 22 rendered | 62 | 0.0 | 1 | 1 | false |
| `wwo` | 33 | 0 | 1 | 30 rendered, 3 static | 155 | 0.1667 | 3 | 5 | false |
| `post-security` | 27 | 0 | 2 | 27 rendered | 93 | 0.0 | 2 | 2 | false |
| `rendered-home` | 87 | 0 | 1 | 84 rendered, 3 static | 218 | 0.1538 | 6 | 7 | false |
| `edca-pilot` | 24 | 0 | 0 | 24 rendered | 155 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 95 | 0 | 0 | 95 rendered | 384 | 0.9565 | 1 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 27 rendered | 155 | 0.8182 | 0 | 0 | true |

**Remaining in TC-121:** the footer strips (answer 2), the footer taglines
(answer 3), and the form placeholder. Answers 2 and 3 are the same question in
two shapes — what a page does with the chrome `_trailing_footer` declines to
take — and are worth doing together rather than one per iteration.

### 2026-08-11 — TC-121 answer 1 of 4: the banner image, and the header was stealing it

**The filed diagnosis was wrong about the cause, for the second time in this
goal.** `_is_banner_image_section` fires perfectly: on contact-page it promotes
`#dnn_BannerPane` to a hero section carrying `background_image` and nothing else.
The loss is one step later. `_claim_candidates` scores boundaries by **word**
overlap, a promoted banner has **no words**, so every candidate scored zero and
the pairing fell to the `-index` tie-break — which is the header. Its role is
chrome, so `prepare_static_sections` replaced the whole hero section with
`_chrome_section(header, "navigation")`. **The banner image was discarded and the
header took a slot it never earned**, which is precisely the failure the
function's own comment warns about ("how a header came to wear the footer's
DOM"). Measured: **nine zero-score claims across the nine local sources, seven of
them this exact case.**

**Three rules, each measured into existence:**

1. **Pictures score after words.** A section can be entirely imagery, so the
   comparison had to include assets — but as resolved *paths*, never tokenized
   into words, which is exactly what `_raw_section_words` excludes asset keys to
   prevent. Words still decide first; pictures only break the tie the old rule
   was losing.
2. **Sharing nothing claims nothing.** A section keeping its own extracted
   content beats a section wearing a stranger's DOM, because enrichment rebuilds
   content from the claimed subtree.
3. **A section may claim the chrome only when it says nothing the chrome does not
   already say.** This one was not planned — it was forced. Rules 1 and 2 alone
   cost **wwo two elements**, and naming them found the reason: the wordless hero
   had been grabbing the header *by accident*, shielding a later section that
   shares the site's phone number with the nav. Freed of that accident, wwo's
   footer block claimed the header and was replaced by chrome, losing its
   tagline, "[email protected]" and "(248) 690-6559" — and putting the nav at
   the END of the page. The contribution test is the same one `_without_wrappers`
   already applies one function above.

**RETENTION 404 → 412, no project down**, +1 on eight projects (cmw-blog,
contact-page, oasis-probe, wwo, post-security, rendered-home, edca-pilot,
kts-fidelity). **Dropped boundaries 18 → 10.**

**The cost, stated plainly: blocking rose on seven projects, and `contact-page`
and `kts-fidelity` go from `valid: true` to false.** The new sections are real —
contact-page's is a `photo_band` holding the banner image — and nothing in the
library can hold a lone background band, the same gap the Quality HC benchmark
recorded. This is the TC-115 shape: coverage fell on five projects and rose on
two because content that could never bind is now arriving instead of vanishing.
Retention is the arbiter and it rose with no drops.

**A finding worth more than the repair: a blocked section is invisible to the
capability queue.** The gap report reads *matched* entries, so a section that
blocks produces no entry at all — the queue still shows 17 gaps and not one of
them is the background band that now blocks seven sections. Silent drops became
blocking sections, and both are invisible to the report that is supposed to rank
library gaps. Filed as part of TC-121's remaining work.

**A measurement error I made and caught.** The pairing diff run against the
*fetched* HTML showed no change on kts-fidelity, so I first concluded kts's move
was run-to-run variance. It reproduced three times, and with the change stashed
kts measured 94/0 blocking. Analysis with `--render` extracts from the **rendered
DOM**, not the fetched HTML — the probe was reading a different input than the
pipeline. Compare what each side is sampling before concluding anything.

**Twelve mutations, twelve distinct failures** — media scoring removed, media
outranking words, zero score still claiming, chrome guard removed, chrome guard
loosened to any overlap, chrome never claimable, chrome emptiness test dropped,
background ignored, media compared as an exact string, media suffix matched
without a path boundary, videos ignored on the raw side, videos ignored on the
DOM side. Three needed fixtures built to isolate them from a neighbour that
covered the same case, including a header and a banner sharing one logo — the
only way the emptiness test in `_claims_the_chrome` can be reached.

**Evidence.** Suite 2,223 → 2,233 passing, 16 deselected. Corpus identical on all
ten metrics. All ten projects re-analysed with `--refresh --render`
(`execution.action == "execute"`) and re-planned with `--refresh`.

| site | elements | Δ | dropped | provenance | styles | coverage | blocking | losses | valid |
|---|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 51 | +1 | 2 | 51 rendered | 93 | 0.0 | 2 | 1 | false |
| `contact-page` | 14 | +1 | 4 | 14 rendered | 93 | 0.6 | 1 | 1 | false |
| `oasis-probe` | 32 | +1 | 0 | 32 rendered | 186 | 0.087 | 4 | 1 | false |
| `oasis-lighting` | 22 | 0 | 0 | 22 rendered | 62 | 0.0 | 1 | 1 | false |
| `wwo` | 33 | +1 | 1 | 30 rendered, 3 static | 155 | 0.1667 | 3 | 5 | false |
| `post-security` | 27 | +1 | 2 | 27 rendered | 93 | 0.0 | 2 | 2 | false |
| `rendered-home` | 87 | +1 | 1 | 84 rendered, 3 static | 218 | 0.1538 | 6 | 7 | false |
| `edca-pilot` | 24 | +1 | 0 | 24 rendered | 155 | 0.6923 | 0 | 1 | true |
| `kts-fidelity` | 95 | +1 | 0 | 95 rendered | 384 | 0.9565 | 1 | 2 | false |
| `northstar-recheck` | 27 | 0 | 0 | 27 rendered | 155 | 0.8182 | 0 | 0 | true |

**Remaining in TC-121:** the footer strips (5), the footer taglines (3), the
contact panel (3 real elements on contact-page), and the form placeholder. Note
that kts's copyright line `#1f670a38` now arrives as a one-element `biography`
section that blocks — the footer-strip answer got more urgent, not less, because
the loss is now loud instead of silent.

### 2026-08-11 — TC-120: a page boundary nothing claimed, and nothing said so

The repair loop closed with the queue held on evidence, so this iteration took
the instrument that loop kept building by hand rather than an item that needs
sources only Josh can authorise.

**The premise was checked before anything was designed.** The corpus computes
`visitor_content_retention` against annotations — an answer key a project does
not have. TC-118 gave a project an element count, which catches a section that
shrinks but not content that was never a section at all. So: count what the
source holds and compare. The first probe said contact-page loses 126 of 138
text runs, which was wrong in an instructive way — `find_all(string=True)`
returns HTML comments, and a DNN page carries dozens of `CDF(Css|…)` cache
directives. Excluding comments and matching by containment rather than equality
(inline tags fragment a paragraph) left a much smaller, much more interesting
list.

**What it found on contact-page:** `Login` sits under `.header-bottom` and is
correctly excluded as chrome, but two `<h2>`s, an `<address>`, a phone list and
a call button live in `div.col-sm-6.bg_right` inside the page body — genuine
content, absent from a document that reports 13 elements, coverage 0.75 and
`valid: true`.

**The mechanism, measured rather than guessed.** The page has exactly one
`<section>` (`#dnn_content`) wrapping every pane. `static_boundary_candidates`
finds seven boundaries including the contact panel; `_top_level_sections` — a
third boundary opinion, inside the legacy extractor — returns `#dnn_content` as
ONE section holding all 66 words. `prepare_static_sections` then walks the raw
sections and uses the candidates only to annotate them, so the page emits as
many sections as the legacy extractor found. The single raw section claims one
pane, `_static_html` is set to that pane's subtree, and enrichment rebuilds the
section's content from it. **The other panes' words were extracted and then
thrown away** — worse than never extracted, and invisible to every check.

**Eighteen boundaries across nine of the ten projects**, including two on
`kts-fidelity`, which scores 0.9559 and looked clean. Filed as TC-121 with the
inventory; this iteration reports rather than repairs, the same order TC-118
established.

**The alarm was made to check what arrived, because the first version lied.**
kts-fidelity's `#tpl-marq-s1` is a marquee repeating "MUSIC IS MAGIC!" twelve
times, and that phrase reaches the document through a real section — so
"the content is absent" was false for it. Going unclaimed is not by itself a
loss. The warning now compares each boundary's distinct text runs and image URLs
against what its own page ended up carrying, and reports only what is genuinely
missing. kts-fidelity fell 2 → 1; the survivor is "All rights reserved".
An alarm that cries wolf is how the last queue filled with noise.

**Two things were removed for being unprovable rather than kept for being
plausible.** Section backgrounds and decorative layers were read as arrival
routes; measured across the nine local projects, **no image inside a dropped
boundary arrived by either route** and no constructed case exercised them, so
they went. Likewise the element-value media route: all **73** image elements
across the ten projects carry an `asset_id`, so reading the value as well was a
second route to the same answer that neither test could isolate.

**Fourteen mutations, fourteen distinct failures** — suppression removed, text
always arrived, media never arrived, media compared unresolved, asset ids not
recorded, comments counted, scripts counted, duplicate runs counted, single-page
unwired, multi-page unwired, pages pooled, chrome filter removed, every
candidate reported, nothing reported. Four needed a fixture built specifically to
isolate them, and one fixture had to be rewritten after it turned out a
comment-only pane never becomes a candidate at all, so it never reached the rule
it claimed to test.

**Per page, not pooled.** A crawl repeats its layout, so checking a dropped block
against every page's content would let a page that kept it silence the page that
lost it.

**Evidence.** Suite 2,213 → 2,223 passing, 16 deselected. Corpus identical on all
ten metrics. All ten projects re-analysed with `--refresh --render`
(`execution.action == "execute"`) and re-planned with `--refresh`: retention 404
unchanged on every project, coverage unchanged, blocking unchanged, losses
unchanged — correct for a report that adds a reader and touches no extraction.

| site | elements | dropped boundaries | provenance | styles | coverage | blocking | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 50 | 3 | 50 rendered | 62 | 0.0 | 1 | 1 |
| `contact-page` | 13 | 5 | 13 rendered | 62 | 0.75 | 0 | 1 |
| `oasis-probe` | 31 | 1 | 31 rendered | 155 | 0.0909 | 3 | 1 |
| `oasis-lighting` | 22 | 0 | 22 rendered | 62 | 0.0 | 1 | 1 |
| `wwo` | 32 | 2 | 29 rendered, 3 static | 124 | 0.1739 | 2 | 5 |
| `post-security` | 26 | 3 | 26 rendered | 62 | 0.0 | 1 | 2 |
| `rendered-home` | 86 | 2 | 83 rendered, 3 static | 187 | 0.1558 | 5 | 7 |
| `edca-pilot` | 23 | 1 | 23 rendered | 124 | 0.6667 | 0 | 1 |
| `kts-fidelity` | 94 | 1 | 94 rendered | 352 | 0.9559 | 0 | 2 |
| `northstar-recheck` | 27 | 0 | 27 rendered | 155 | 0.8182 | 0 | 0 |

**Three boundary opinions now exist in this pipeline** —
`static_boundary_candidates`, `_top_level_sections` inside the legacy extractor,
and the rendered observation script. The loop has already been bitten twice by
two of them disagreeing silently. This is the first check that reports a
disagreement instead of letting the quieter one win.

### 2026-08-10 — CLOSING SUMMARY of the extraction repair loop

Six tasks, six commits, and the queue is now held on evidence rather than on
work. What each one changed:

| # | task | commit | what it changed |
|---|---|---|---|
| 1 | TC-118 | `31fb3a7` | The analysis report counts retained content, per project and per section. Nothing else in the loop could have been judged without it. |
| 2 | TC-115 | `51749db` | A non-repeating section kept its first two headings and dropped the rest; every remaining heading now arrives as `subheading`. |
| 3 | TC-114 | `87324d7` | One pull-quote made a whole page testimonials. A section needs two quotes, or a quote and no image, before its role changes. |
| 4 | TC-116 | `e471d61` | An anchor with no text was counted as a call to action, and a linked picture arrived as two things. An action must say something; a picture owns its own link. |
| 5 | TC-113 | `1f9829d` | `repeating_subtrees` preferred the deepest candidate group; it now ranks by member count and uses depth only to break ties. |
| 6 | TC-119 | `42a0edb` | A paragraph whose whole text is a link arrived twice. Only the action carries the destination, so the paragraph defers to it. |

**The retention arc: 398 → 416 → 393 → 412 → 404.** Every move was measured
across all ten projects before it was kept, and every fall was named element by
element. TC-115 added 18 headings that had been silently discarded. TC-116 took
23 away — 23 phantom actions built from anchors that said nothing, each one
named. TC-113 restored 19 by finding the group that actually repeats. TC-119
took 8 away, each a duplicate of an action that carries a URL the paragraph
never did.

**Coverage is not the arbiter, and this loop is the proof.** It fell during
TC-115 because good content arrived that no template could hold. It rose during
TC-116 because content that was never real stopped arriving. It rose in TC-113's
first, wrong attempt while five real pictures and two headings vanished. Three
different directions, three different meanings — retention decided all three.

**Defects filed rather than fixed, and why.** TC-113 was filed after its obvious
fix raised coverage and lost content. TC-114 was filed because it could not be
fixed until TC-115 stopped the headings from being dropped. TC-116 was filed
because the loop had a task in flight. TC-119 was filed the moment it was found,
because it belonged to a different mechanism than the task that surfaced it.
TC-117 was filed with a measurement and then resolved by holding back, not by
suppressing. In every case the filing carried the measurement that justified it,
and in TC-113's case the filed diagnosis turned out to be wrong — the cause was
the ranking, not the missing map entry the filing named.

**Four mutations passed that should not have**, each because two guards covered
one fixture: TC-118's valued-element count, TC-116's picture rule, TC-113's
nesting filter, and TC-117's confidence tier. TC-119 added a fifth of a different
kind — the single-link arity check had no case that distinguished it in either
direction, so the rule was restated to say what it means rather than pinned with
a contrived fixture.

**The queue now.** Nothing is blocked; four items are held on evidence and need a
second measured section before they can be worked: TC-109 (a card kicker),
TC-110 (a list on a non-repeating template), TC-111 (`logo-bar`/`item.label` and
`stats-band`/`item.title`), and TC-104's three unverified templates. TC-112
records the verdict that the eight captured pages cannot supply that second
section — it has to come from new measured sources. TC-105 remains dependent on
TC-103 and TC-104.

**Final state.** Suite 2,213 passing, 16 deselected. Corpus identical on all ten
metrics — `visitor_content_retention` 127/127, `semantic_role_accuracy` 25/25,
`high_confidence_precision` 18/19, no threshold or regression failures. All ten
projects re-analysed with `--refresh --render` (`execution.action == "execute"`)
and re-planned with `--refresh`.

### 2026-08-10 — repair 6: a link speaks for the paragraph that holds nothing else

**TC-119.** `rendered-home.section.5` reported twelve elements reading "Read
More" where the source has six anchors. The source says why:
`<p><a class="home06-btn02" href="/blog/post/...">Read More</a></p>` — the
paragraph sweep emits the paragraph as `body`, and the action loop emits the
anchor it contains.

The action survives, because it carries the destination the paragraph never had.
`_is_only_a_link` claims a paragraph whose whole text comes from a link, and
those paragraphs are filtered out of body copy before anything else reads them.

**Retention 412 → 404, all of it `rendered-home` (94 → 86), and all eight named**
— six "Read More" pointing at six different `/blog/post/…` URLs, one "SEE MORE"
pointing at `/what-we-do/portfolio`, one "VIEW BLOG" pointing at `/blog`. Each
survives as a `primary_action` carrying that href. The section's "Read More"
count is now exactly six, one per source anchor. Coverage rose 0.1412 → 0.1558
and losses held at 7: fewer elements arrive, and the ones that do bind better.

**The rule says what it means.** The first version required exactly one link, and
no mutation could distinguish that from "the first link" — a paragraph whose text
comes entirely from its first link behaves identically either way. Rather than
pin an arbitrary branch with a fixture built to justify it, the check now reads:
the paragraph's whole text comes from a link. Five mutations break a test —
removing the filter, claiming any paragraph that holds a link, dropping the
has-text guard, claiming linkless paragraphs, and loosening equality to
containment.

**The has-text guard is not decoration.** An unlabelled anchor is not emitted as
an action (TC-116), so a paragraph holding one has nothing to defer to; matching
it on emptiness alone would drop the element with nothing taking its place. That
guard needed its own fixture — the first three tests all passed with it removed.

**Evidence.** Suite 2,213 passing. Corpus identical on every metric. Nine
projects byte-identical in retention; `rendered-home` accounted for entirely.

| site | elements | Δ | provenance | styles | coverage | blocking | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 50 | 0 | 50 rendered | 62 | 0.0 | 1 | 1 |
| `contact-page` | 13 | 0 | 13 rendered | 62 | 0.75 | 0 | 1 |
| `oasis-probe` | 31 | 0 | 31 rendered | 155 | 0.0909 | 3 | 1 |
| `oasis-lighting` | 22 | 0 | 22 rendered | 62 | 0.0 | 1 | 1 |
| `wwo` | 32 | 0 | 29 rendered, 3 static | 124 | 0.1739 | 2 | 5 |
| `post-security` | 26 | 0 | 26 rendered | 62 | 0.0 | 1 | 2 |
| `rendered-home` | 86 | −8 | 83 rendered, 3 static | 187 | 0.1558 | 5 | 7 |
| `edca-pilot` | 23 | 0 | 23 rendered | 124 | 0.6667 | 0 | 1 |
| `kts-fidelity` | 94 | 0 | 94 rendered | 352 | 0.9559 | 0 | 2 |
| `northstar-recheck` | 27 | 0 | 27 rendered | 155 | 0.8182 | 0 | 0 |

### 2026-08-10 — repair 5: the gallery was never a leftovers problem

TC-113, and the diagnosis the evidence loop filed was wrong about the cause.

Re-measuring the naive change first — as the brief demanded, because TC-115 and
TC-116 had both moved the ground — reproduced the same collapse: retention 31 →
21, the gallery section down from fourteen elements to four. So the filing's
warning held. But looking at *why* showed it was never about how a card grid
treats its leftovers.

**`repeating_subtrees` was picking two `div.White` layout bands** — one holding a
single picture, the other holding all six cards. Everything outside those two
counted as inside a repeat item, so the eyebrow, the headings and five pictures
were never emitted. The real cards were one level down and perfectly uniform:

| signature | members | pictures each |
|---|---|---|
| `div.White` | 2 | **1 and 6** |
| `div.mb-20.row` | 2 | 3 and 3 |
| `div.col-sm-4` | **6** | 1 each |

The rule ranked candidates by depth first, so the shallowest thing that happened
to repeat won. It now **ranks by how many times a signature repeats, with depth
only breaking a tie** — which preserves the rule it was written for, that a card
is the card and not the rounded box inside it. **No entry in
`_CARD_GRID_REPEAT_KIND` was needed at all**, and the section's role never
changed; it simply gained the group it always had.

**Retention 393 → 412, no project down.** `oasis-probe`'s gallery holds the same
fourteen elements, now as six cards with pictures and titles instead of loose
media and stray headings, and its section heading is "Our Services" rather than
one card's name. `rendered-home` gained nineteen, all in one section whose card
grid was being read as three loose bodies.

**A duplicate that was not mine.** `rendered-home.section.5` reports twelve
"Read More" where the source has six anchors. Measuring the section before and
after the change gave 34 elements and 12 either way, so it is pre-existing: a
paragraph whose whole content is a link is emitted as body copy *and* the link as
an action. Filed as TC-119 rather than folded in.

Three mutations, and the third needed a fixture of its own — reverting the
ranking and dropping the depth tiebreak each failed as intended, but removing the
nesting filter passed, because no fixture had a signature nesting inside itself.
That is the third time this loop a mutation has survived because two guards
covered one case.

**Evidence.** Suite 2,204 → 2,207 passing, 16 deselected. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures.

| site | sections | provenance | style obs | retained | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 50 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 13 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 31 | 0.0909 | 3 | false | 1 |
| `oasis-lighting` | 2 | 2 rendered | 62 | 22 | 0.0 | 1 | false | 1 |
| `wwo` | 5 | 4 rendered, 1 static | 124 | 32 | 0.1739 | 2 | false | 5 |
| `post-security` | 2 | 2 rendered | 62 | 26 | 0.0 | 1 | false | 2 |
| `rendered-home` | 7 | 6 rendered, 1 static | 187 | 75 → **94** | 0.1212 → 0.1412 | 5 | false | 3 → 7 |
| `edca-pilot` | 4 | 4 rendered | 124 | 23 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 94 | 0.9559 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 27 | 0.8182 | 0 | true | 0 |

New retention baseline **412**. All four extraction defects the evidence loop
found are closed; the report-side TC-117 remains, plus the new TC-119.

### 2026-08-10 — repair 4: the only retention drop this loop should accept

TC-116. `html_ownership` emitted a `primary_action` for every `<a href>` with no
test that the anchor said anything, while both measurement scripts have required
a label since iteration 55 — "an action with no label is not the call".

**The textless anchors turned out to be three different things**, and measuring
that before removing anything is what made the fix honest:

| kind | count across three projects | what it is |
|---|---|---|
| carries `aria-label` or `title` | 6, 12, 6 | a social icon that says what it is |
| wraps a picture | 9, 12, 9 (every picture had an `alt`) | the picture is the label |
| nothing at all | 2, 5, 2 | `mm-close`, `mm-next`, `mm-prev` — menu chrome |

So an action now takes its accessible name when it has no text; a picture wrapped
in a link records its destination **on the picture** rather than arriving twice;
and an anchor with nothing to read anywhere is not emitted.

**Retention fell 416 → 393, and this is the one drop this loop should accept.**
The rule is to revert unless every dropped element can be named and justified,
and all 23 are: **27 pictures gained a destination they never had**, and the
remainder are menu controls with an href like `#mm-1`. Nothing left the document
that a reader could see — the anchors' accessible names survive as the pictures'
`alt` text, which every one of them already carried. **Blank actions across all
ten projects fell from twelve to zero.**

Coverage *rose* on four projects — `kts-fidelity` 0.942 → 0.9559,
`wwo` 0.1538 → 0.1739, `rendered-home` 0.1067 → 0.1212, `oasis-probe` 0.0714 →
0.0909 — because phantom actions that could never bind are gone. That is coverage
rising for the right reason, which is worth distinguishing from TC-113's trap
where it rose because content vanished.

**Five mutations, and one exposed a hole in my own test.** Removing the
picture rule passed at first, because the label guard caught the same fixture —
the rule only matters when the anchor *also* has an accessible name, which is
the real case on a logo link. The test now uses one, and the mutation fails.

**Evidence.** Suite 2,200 → 2,204 passing, 16 deselected. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures.

| site | sections | provenance | style obs | retained | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 50 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 13 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 31 | 0.0909 | 3 | false | 1 |
| `oasis-lighting` | 2 | 2 rendered | 62 | 22 | 0.0 | 1 | false | 1 |
| `wwo` | 5 | 4 rendered, 1 static | 124 | 32 | 0.1739 | 2 | false | 5 |
| `post-security` | 2 | 2 rendered | 62 | 26 | 0.0 | 1 | false | 2 |
| `rendered-home` | 7 | 6 rendered, 1 static | 187 | 75 | 0.1212 | 5 | false | 3 |
| `edca-pilot` | 4 | 4 rendered | 124 | 23 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 94 | 0.9559 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 27 | 0.8182 | 0 | true | 0 |

New retention baseline: **393**. Three of the four extraction defects are closed;
TC-113 and the report-side TC-117 remain.

### 2026-08-10 — repair 3: the careless rule stops overriding the careful one

TC-114. `static_role` returned `testimonials` for any element containing a
`<blockquote>` — no count, no test for competing content — and it outranks
`_classify_section`, which has always required quotes to be the point and
correctly called `oasis-lighting` a gallery. One pull-quote among six
photographs made the whole page a quote grid.

**The retention alarm earned its keep on the first try.** With the rule
corrected, retention fell 416 → **415**. One element. The rule of this loop is
to revert on any drop unless each lost element can be named and justified, so I
named it: **"Walt Whitman"**, the attribution in a `<cite>` inside the
blockquote. Only the testimonials branch ever read a `<cite>`, so the moment the
section stopped being testimonials the name left the document. The quote itself
survived, because repair 2 keeps every heading.

An attribution is visitor content, and justifying its loss would have been the
reflex this rule exists to prevent. A `<cite>` or `<figcaption>` that no repeated
item owns is now kept wherever it appears. **Retention back to 416, no project
down.**

`oasis-lighting` reclassifies from `testimonials` to `hero`, which is the
pre-existing rule for a first content boundary carrying an `<h1>` rather than
anything this change introduced. Its coverage falls to 0 and it blocks — on
`file:///` images the capture cannot resolve, which the report already holds back
as acquisition defects. Whether the page should be a gallery is TC-113's
question, and the answer is no longer being pre-empted by a stray quote.

Six mutations, six distinct failures: reverting to any-blockquote, removing the
count guard, removing the no-competing-content guard, ignoring an explicit
`testimonial` class, removing the attribution emit, and letting a repeated item's
own attribution through — that last one would have doubled every name on a real
testimonials page.

**Evidence.** Suite 2,194 → 2,200 passing, 16 deselected. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures.

| site | sections | provenance | style obs | retained | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 50 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 13 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 37 | 0.0714 | 3 | false | 1 |
| `oasis-lighting` | 2 | 2 rendered | 62 | 26 | 0.1765 → **0.0** | 0 → **1** | true → **false** | 4 → **1** |
| `wwo` | 5 | 4 rendered, 1 static | 124 | 35 | 0.1538 | 2 | false | 5 |
| `post-security` | 2 | 2 rendered | 62 | 26 | 0.0 | 1 | false | 2 |
| `rendered-home` | 7 | 6 rendered, 1 static | 187 | 84 | 0.1067 | 5 | false | 3 |
| `edca-pilot` | 4 | 4 rendered | 124 | 23 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 95 | 0.942 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 27 | 0.8182 | 0 | true | 0 |

Two of the four extraction defects the evidence loop found are now closed.

### 2026-08-10 — repair 2: eighteen headings that were never reaching the document

TC-115. A section emitted its most prominent heading and at most one eyebrow;
every other heading it owned was dropped before the design document existed.

**My first measurement of the damage was wrong, and I nearly acted on it.**
Counting headings per boundary candidate gave 29 dropped — but most of those are
card titles inside repeat items, which are correctly emitted as `card_title`
further down. Comparing what the source offers against what the document
contains gives the honest figure: **25 headings present in the source and absent
from the document**, concentrated in `rendered-home` (14), `oasis-probe` (6) and
`oasis-lighting` (3). The two clean fixture sites lose none.

They are ordinary things: `Branding Package`, `Tags`, `Gallery`, and the
pull-quote written as an `<h3>` that TC-114 needs. Every heading a section owns
is now emitted, with the role `subheading` for those that are neither the title
nor the eyebrow.

**Retention 398 → 416, and no project lost an element.** That is the number that
matters, and it is the first time this loop has had it. `oasis-probe` +5,
`rendered-home` +5, `kts-fidelity` +5, and one each on `oasis-lighting`, `wwo`
and `post-security`.

**Coverage fell on four projects, and that is the correct direction.** Coverage
is the share of *arriving* content that binds, so eighteen new elements that no
template holds lower the ratio while strictly improving what a build could keep.
This is the exact inverse of the trap in TC-113, where coverage rose 0.087 →
0.167 as five pictures and two headings vanished. **Retention is the arbiter;
coverage alone cannot tell the two apart.** Losses rose from 16 to 20 across the
projects, and a loss the report names is worth more than one nothing can see.

**The alias tables disagreed with each other.** `binding_field_aliases` has
always accepted a `subheading` for a `subtitle` field; `section_capability_
aliases` did not know the word, so a section carrying one scored as though no
template could hold it. They now agree, which is what took `rendered-home` from
four losses back to three and `kts-fidelity` from three to two.

Four mutations were tried against the new rule — removing it, dropping the title
guard, dropping the eyebrow guard, and letting repeat-item headings through —
and each failed the test written for it, the last of those being the one that
would have doubled every card title in the document.

**Evidence.** Suite 2,189 → 2,194 passing, 16 deselected. Benchmark aggregate
identical on all ten metrics including `visitor_content_retention` and
`semantic_role_accuracy`, no threshold or regression failures.

| site | sections | provenance | style obs | retained | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 50 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 13 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 32 → **37** | 0.087 → 0.0714 | 3 | false | 0 → 1 |
| `oasis-lighting` | 2 | 2 rendered | 62 | 25 → **26** | 0.1875 → 0.1765 | 0 | true | 3 → 4 |
| `wwo` | 5 | 4 rendered, 1 static | 124 | 34 → **35** | 0.16 → 0.1538 | 2 | false | 4 → 5 |
| `post-security` | 2 | 2 rendered | 62 | 25 → **26** | 0.0 | 1 | false | 1 → 2 |
| `rendered-home` | 7 | 6 rendered, 1 static | 187 | 79 → **84** | 0.1143 → 0.1067 | 5 | false | 3 |
| `edca-pilot` | 4 | 4 rendered | 124 | 23 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 90 → **95** | 0.9412 → 0.942 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 27 | 0.8182 | 0 | true | 0 |

TC-114 is unblocked: the pull-quote it would have cost now has somewhere to go.

### 2026-08-10 — repair 1: the alarm the last three reverts were missing

First iteration of the extraction repair loop, and it builds the instrument
rather than fixing anything. TC-118.

Three repairs in the evidence loop silently dropped content, and each was caught
only because I counted elements by hand. **In one of them coverage rose while
five pictures and two headings vanished** — the ratio is taken over what
survives, so losing content can improve it. Nothing in a project reported what
extraction actually produced. `visitor_content_retention` exists, but only for
the benchmark corpus, which has annotations to compare against; a project has no
answer key and needs a plainer question — did this section arrive with fewer
pieces than last time?

`analysis-report.json` now carries `content_elements` and
`content_elements_by_section`. The baseline across ten projects is **398
elements**, recorded in TC-118 above, and every remaining task in this loop is
measured against it.

**Every element counts, including those with no text value**, and that turned out
to matter. Three mutations were tried against the tests: removing the report
field and omitting empty sections both failed as intended, but counting only
elements with a value **passed** — nothing pinned it. A picture is an element
with no text, and pictures are precisely what went missing before, so the alarm
would have been blind to the case it exists for. A third test now pins it.

**Evidence.** Suite 2,186 → 2,189 passing, 16 deselected. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures. All ten
projects re-analysed `--refresh --render` and re-planned `--refresh`; coverage,
blocking, validity and losses unchanged everywhere, which is expected for a
change that only adds a measurement.

| site | sections | provenance | style obs | retained | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 50 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 13 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 32 | 0.087 | 3 | false | 0 |
| `oasis-lighting` | 2 | 2 rendered | 62 | 25 | 0.1875 | 0 | true | 3 |
| `wwo` | 5 | 4 rendered, 1 static | 124 | 34 | 0.16 | 2 | false | 4 |
| `post-security` | 2 | 2 rendered | 62 | 25 | 0.0 | 1 | false | 1 |
| `rendered-home` | 7 | 6 rendered, 1 static | 187 | 79 | 0.1143 | 5 | false | 3 |
| `edca-pilot` | 4 | 4 rendered | 124 | 23 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 90 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 27 | 0.8182 | 0 | true | 0 |

Next is TC-115, which unblocks TC-114.

### 2026-08-10 — evidence 7/7: `rendered-home`, and the closing verdict on TC-112

Last source. **Nothing promoted.** The queue grew from 12 gaps to **17**, and
almost every new entry came from a match the matcher did not believe.

`rendered-home` is seven sections and five of them block. Two testimonial
sections matched `CTAs/cta-split` at **0.3794 and 0.4941**, which produced
entries asking for a CTA that holds thirteen actions, six pictures and fifteen
paragraphs. A feature-card section matched `ribbon-marquee` at 0.4432. Its
`section.7` is the **same footer block as `wwo.section.5`** — the same site
captured on two pages — so rank 1's "four sections across three sources" is one
genuine call to action and three pieces of chrome.

**Measured rather than counted by hand: seven of the seventeen entries rest on a
`low` confidence match.** The pipeline already says it does not believe those
pairings. Filed as TC-117.

### The verdict on TC-112

**Seven real sources were the wrong instrument, and running them was the right
way to find that out.**

*Promoted, one:* `Content/rich-text`/`media`, shipped as **agency pack 1.11.0**
on two genuine sections from two sources — a stacked image with text had no
template in the library at all.

*Declined, one:* `Content/rich-text`/`primary_action`, which finished with the
highest count in the queue — four sections across three sources — and one
genuine instance. Reading beats counting, every time.

*Still held at one section:* `feature-cards-4up`/`eyebrow` (TC-109),
`logo-bar`/`item.label` and `stats-band-3up`/`item.title` (TC-111),
`blog-post-cards-3up`/`primary_action`, `rich-text`/`subtitle`,
`rich-text`/`body` capacity, `cta-banner`/`action` capacity. TC-104's three
unverified templates never appeared at all.

*Noise:* seven of seventeen entries come from low-confidence matches, and five
more trace to two specific misroutes. **The queue is now majority noise.**

*What the loop actually found* — four extraction defects and one report defect,
none of which more sources will fix:

- **TC-113** — a `gallery` section builds no repeat group, and the one-line fix
  raises coverage while silently dropping five pictures and two headings.
- **TC-114** — `static_role` calls any section holding one `<blockquote>` a
  testimonials section, overriding the careful rule that already exists.
- **TC-115** — a non-repeating section emits its title and one eyebrow and
  silently drops every other heading, which is why TC-114 cannot be fixed alone.
- **TC-116** — every `<a href>` becomes a `primary_action`, so page chrome and
  citations inside prose read as calls to action.
- **TC-117** — the report ranks gaps from matches the matcher scored `low`,
  because only the corpus carries an answer key.

**The library was not what was limiting fidelity.** Six of seven sources
promoted nothing because the sections that would have promoted them were
misclassified before they reached a template. Adding pages measures extraction,
and extraction is where the work is.

**Evidence.** Suite 2,186 passing, 16 deselected. Benchmark aggregate identical
on all ten metrics across all seven iterations, no threshold or regression
failures at any point.

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 0.087 | 3 | false | 0 |
| `oasis-lighting` | 2 | 2 rendered | 62 | 0.1875 | 0 | true | 3 |
| `wwo` | 5 | 4 rendered, 1 static | 124 | 0.16 | 2 | false | 4 |
| `post-security` | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `rendered-home` (new) | 7 | 6 rendered, 1 static | 187 | 0.1143 | 5 | false | 3 |
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

TC-112 is complete: all seven sources added, sixteen sources and sixty-three
sections now measured. The loop stops here.

### 2026-08-10 — evidence 6/7: `post-security`, the loop's first promotion, and its second refusal

Sixth source of TC-112, and the first to promote something. **Agency pack
1.11.0** ships one capability change; a second candidate with a larger count was
declined.

**Promoted: `Content/rich-text`/`media`.** `oasis-probe.section.2` is a heading,
a photograph and a paragraph in a single column; `post-security.section.2` is a
blog post with a featured image above eight paragraphs. Two genuine sections on
two sources, both wanting the same thing, and the library had nothing for it:
`rich-text` declared `media_positions: ["none"]` with no image component at all,
while `split-media` and `bio-about` are two-column and `photo-band` carries no
copy. **A stacked image with text had no template.** `rich-text` now declares an
optional `media` slot between its heading and its copy, and `media_positions`
widened to `["none", "top"]` so a text-only block still matches as it did.
`oasis-probe` content losses 1 → 0, and the entry left the queue.

**Declined: `Content/rich-text`/`primary_action`, now showing three sections
across two sources.** The count is the most compelling in the queue and it is
still wrong. Reading them: `wwo.section.4` is a real call to action — "Get
Started!" to `/contact-us`. `wwo.section.5` is page chrome. And
`post-security.section.2`'s six are four tag links to `/blog`, a **citation
inside a paragraph**, and a "Back to blog home" button. One genuine instance
across three sections.

The citation is TC-116 showing its cost: the extractor lifts every `<a href>`
out as a `primary_action`, so a link inside prose becomes a separate call to
action and its text is counted twice. A queue entry can accumulate sections
without accumulating evidence, and the only defence is reading them.

**Corpus exposure was checked before the release, not after.** Exactly one
benchmark section lists `rich-text` as a candidate at all, third at 0.6942
against a hero at 0.9344. The aggregate is identical on all ten metrics
afterwards.

**Evidence.** Suite 2,186 passing, 16 deselected. Benchmark aggregate identical,
no threshold or regression failures.

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 0.087 | 3 | false | 1 → **0** |
| `oasis-lighting` | 2 | 2 rendered | 62 | 0.1875 | 0 | true | 3 |
| `wwo` | 5 | 4 rendered, 1 static | 124 | 0.16 | 2 | false | 4 |
| `post-security` (new) | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

`post-security` still blocks: its eight paragraphs overflow `rich-text`'s four
body slots, and its featured image is a `file:///portals/...` path the capture
cannot resolve. The overflow is a new single-section entry.

Queue: **12 gaps, 14 dropped fields.** One source remains.

### 2026-08-10 — evidence 5/7: `wwo`, an apparent promotion that was one page's habit

Fifth source of TC-112. **Nothing promoted**, though the ranked report said
otherwise at first glance.

`wwo` put `Content/rich-text`/`primary_action` at rank 1 with **two sections**,
which is the bar for a release. Reading them settles it the other way:

- `section.4` is a real content block — "Website Only", a paragraph, and a
  "Get Started!" button pointing at `/contact-us`. A genuine rich-text section
  with a call to action.
- `section.5` is page chrome — body copy, an obfuscated email link, a telephone
  number, and three social links. It sits in a DNN content pane rather than the
  page's `<footer>` element, so nothing recognises it as chrome.

Two sections on one page, one of which is not the shape it claims. That is
precisely the "one page's editorial choice" the two-source rule exists to catch,
so the entry stays at one genuine section and nothing ships.

**It did expose something exact.** Three of `section.5`'s five "calls to action"
are social icons whose anchors carry **no text at all**. Both measurement scripts
have required an action to carry a label since iteration 55 — "an action with no
label is not the call" — and the extractor was never given the same rule. So a
section reads as carrying five calls to action where it has two, and is scored
against that. Filed as TC-116, not fixed: the fix removes elements from the
design document, which is the direction this loop has already reverted twice, and
whether a social profile URL is content worth keeping needs settling first.

The TC-110 hold-back earned its keep here — `cta-split` took a nine-item list
from `section.3` and the report correctly declined to rank `item.benefit` and
`item.text` as missing fields on a template that repeats nothing.

`wwo` is also the first source with a section measured **statically** rather than
rendered: four of five carry rendered provenance, one does not.

**Evidence.** Suite 2,186 passing, 16 deselected, unchanged. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures.

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 0.087 | 3 | false | 1 |
| `oasis-lighting` | 2 | 2 rendered | 62 | 0.1875 | 0 | true | 3 |
| `wwo` (new) | 5 | 4 rendered, 1 static | 124 | 0.16 | 2 | false | 4 |
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

Queue: **11 gaps to 12**, 13 dropped fields. Rank 1 has two sections and one of
them does not count. Two sources remain.

### 2026-08-10 — evidence 4/7: `oasis-lighting`, a second override, and a queue filling with noise

Fourth source of TC-112. **Nothing promoted, and the fix was reverted for the
second iteration running** — this time on a check the loop would not have caught.

`oasis-lighting` is one page carrying a heading, six photographs, three
paragraphs, four links and a single pull-quote. It is classified `testimonials`
and matched to `testimonial-cards-3up`, losing the photographs, the copy and
every link. `static_role` returns `testimonials` for *any* element containing a
`<blockquote>`; the legacy `_classify_section` requires quotes to be the point —
several of them, or a lone quote with nothing competing — and calls this page a
gallery. **The careful rule is overridden by the careless one**, exactly as
`<article>` was in evidence 1/7. That override now has two instances.

The corpus was checked before touching anything: its two blockquote sections
carry two and three quotes, so the correction leaves them alone.

**Applying it cost content anyway.** Retention fell 25 elements → 23: the
pull-quote is an `<h3>` inside the blockquote, and enrichment emits a
non-repeating section's most prominent heading plus at most one eyebrow, so
every other heading is silently dropped. Filed as TC-115, which blocks TC-114.

**A document-level loss is worse than a binding-level one**, which is why this
was reverted rather than shipped. A dropped field is named in the report and can
be closed by widening a template. Content that never reaches the design document
is invisible to every check the loop runs — no plan warning names it, coverage
cannot see it because the element was never counted, and no project reports
retention.

**Five of the eleven queue entries are now fallout from two misroutes.**
Entries 3–5 are TC-114's, entries 10–11 are TC-113's. The report cannot tell,
because only the benchmark corpus carries `acceptable_templates`. On the corpus
a loss from a wrongly matched section is held back as a routing defect; on a
project workspace the same loss reads as a missing field. The queue is filling
with noise, and the fix is not more sources.

**Evidence.** Suite 2,186 passing, 16 deselected, unchanged. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures.

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 0.75 | 0 | true | 1 |
| `oasis-probe` | 5 | 5 rendered | 155 | 0.087 | 3 | false | 1 |
| `oasis-lighting` (new) | 2 | 2 rendered | 62 | 0.1875 | 0 | true | 3 |
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

Queue: **8 gaps and 8 dropped fields to 11 and 11**, every one still a single
section, and five of them noise. Three sources remain.

### 2026-08-10 — evidence 3/7: `oasis-probe`, and a fix that raised coverage while losing content

Third source of TC-112. **Nothing promoted.** The source found a real defect,
and the obvious fix for it turned out to be worse than the defect — so it is
filed as TC-113 and nothing shipped.

`oasis-probe` gives five sections and plans invalid: three block, all on
`file:///Portals/...` images that this saved capture cannot resolve, which the
report already holds back as acquisition defects. Section 4 is the interesting
one — a gallery with an eyebrow, a heading and seven linked photographs, matched
to `Content/video-feature` at **0.4827, low**, warning "media needs 7 slots,
template owns 1".

The cause is a one-line omission: `_CARD_GRID_REPEAT_KIND` lists
`project_gallery` and not `gallery`, so the section builds no repeat group and
every gallery template scores as though it repeated nothing.

**Adding the missing entry fixed the routing and lost the content.** Measured
with the change in place: the section reaches `Cards/gallery-3up` at 0.8643
high, and coverage rises 0.087 → 0.167 — while the design document drops from
an eyebrow, a heading and seven pictures to two card items and nothing else.
`repeating_subtrees` finds two like-signature subtrees here, the enrichment
branch keeps only those, and the rest is never emitted. **No warning is raised,
because the content is not dropped at binding — it is never extracted.**

That is the direction this loop's usual alarm cannot see. The standing
instruction is to treat a coverage *drop* as the signal; here coverage went
**up** on a section that had just lost five pictures and both its headings. The
check that would have caught it is retention, and no project reports it.

Reverted, and confirmed the section is whole again: seven media, six actions, an
eyebrow and a title. The real fix has to make the pictures items without
discarding what is not one, which is a change to how a card grid treats its
leftovers rather than a map entry.

**Three of the eight queue entries now come from that one misrouted section** —
`video-feature`/`media` (owns 1, needs 7), `video-feature`/`action` (owns 1,
needs 6), and indirectly the low match itself. The report cannot tell, because
only the benchmark corpus carries `acceptable_templates`; a project workspace
has no answer key, so a misroute there reads as a capability gap.

**Evidence.** Suite 2,186 passing, 16 deselected, unchanged. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures.

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `contact-page` | 2 | 2 rendered | 62 | 0.75 | 0 | true | 1 |
| `oasis-probe` (new) | 5 | 5 rendered | 155 | 0.087 | 3 | false | 1 |
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

Queue: **5 gaps and 5 dropped fields to 8 and 8**, every one still a single
section. Four sources remain.

### 2026-08-10 — evidence 2/7: `contact-page`, and a check that was right to say no

Second source of TC-112. **Nothing promoted, and no code changed** — which is
what most iterations of this loop should look like.

`contact.html` gives two sections: the site navigation, and a `rich_text` band
holding "Contact Us", a deck, and two paragraphs. It plans valid at 0.75
coverage with one loss, `Content/rich-text`/`subtitle` — the deck. `rich-text`
declares `title` and four `body` slots and no subtitle, so the loss is real and
the queue grows to five entries, all still one section each.

**A contact page classified as rich text looks wrong, and it is not.** The
capture has a `<form>` with eleven inputs, so the obvious reading is that the
contact detector missed a form. Nine of those inputs are ASP.NET hidden postback
fields, and the two visible ones are DNN search boxes —
`dnn$dnnSEARCH$txtSearch` and `dnn$dnnSEARCH3$txtSearch`. `has_form_fields`
returns False, exactly as its docstring intends: "One field and a button is a
search box or a newsletter signup, which is not a contact form." There is no
contact form on this page, and the section really is a heading and some copy.

Worth recording because the alternative was to *fix* something that was working,
which would have cost a real check its judgement.

**Evidence.** Suite 2,186 passing, 16 deselected, unchanged. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures.

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `contact-page` (new) | 2 | 2 rendered | 62 | 0.75 | 0 | true | 1 |
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

Queue: **4 gaps and 4 dropped fields to 5 and 5**, every one still a single
section. Five sources remain.

### 2026-08-10 — evidence 1/7: `cmw-blog`, and `<article>` was not a kind of thing

First source of TC-112. **Nothing promoted to a second section**, which is the
ordinary outcome and not a reason to reach for a release. What the source did do
is expose a classification defect that would have poisoned the queue for the
next six iterations.

`cmw-blog` section 2 is a listing of ten posts, each an image, a title and a
**date** — "Nov 13, 2017", "Sep 21, 2017". It came out as `feature_cards`, so
`primary_action` had nowhere to go and the queue ranked *"give
`feature-cards-4up` a primary_action field"* — the wrong question, since
`blog-post-cards-4up` already declares one.

**Two blind spots, one after the other.** The heading rule from iteration 63
reads the first heading outside the cards, and a blog listing routinely has no
heading at all — the grid is the whole section. The cards answer for themselves
where a heading cannot: iteration 63 recorded that the `keys-to-success` grids
had "no link, no date, no excerpt", and here there is a date on every card. I
checked the corpus first — every card body there is a descriptive sentence, none
date-like — then added the rule.

That fixed `extract_sections` and changed nothing, because **`static_role`
outranks it and has the same blind spot in a purer form**: a row of two or more
`<article>` elements returns `feature_cards`. `<article>` is the element a blog
post is written in. Taking it for a feature card is the recurring failure at its
most literal, and the date rule is now shared by both classifiers rather than
duplicated.

The section routes to `Cards/blog-post-cards-3up` with repeat kind `blog_post`.

**Its plan then got worse, and that is honest.** Coverage fell 0.4878 → 0.0 and
the section now blocks — because `blog-post-cards-3up` declares `item.media`
**required** where `feature-cards-4up` had it optional, and all ten card images
in this capture resolve to nothing (a saved page pointing at `file:///portals/...`
that does not exist). The correct template refuses to build a post grid with no
pictures. That is an acquisition limit of the source, not a routing regression,
and the ranked report holds those unresolved assets back as such.

**One thing worth noting for the next source.** The new queue entry is
`blog-post-cards-3up`/`primary_action`, and that is not a new asymmetry — it is
the one TC-105's `KNOWN_WIDTH_VARIANT_ASYMMETRY` table already names, whose
entry read "a gap nobody has measured yet". It now has one measured section.
One, not two.

**Evidence.** Suite 2,181 → 2,186 passing, 16 deselected. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures. The date rule
was proved four ways: removing it, dropping its majority threshold, letting a
bare month and year count, and putting it ahead of the heading each fail a
different test.

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `cmw-blog` (new) | 2 | 2 rendered | 62 | 0.0 | 1 | false | 1 |
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

Queue: **3 gaps and 3 dropped fields to 4 and 4**, all still single sections.
Six sources remain.

### 2026-08-10 — the `item.*` shape: four of six were the wrong question

Six of the seven remaining gaps were `item.*` — a field on a repeat item the
matched template's items do not declare. No template was widened; the shape was
measured first, and **every one of the four sections had the same thing in
common: the extractor labelled its group `other`**, its own word for a repeated
structure it could not name.

| section | role | template | template repeats | item fields |
|---|---|---|---|---|
| `html-dnn-services.section.4` | split_feature | `split-media` | **nothing** | `text` |
| `figma-freeform-nonprofit` volunteer-cta | call_to_action | `cta-banner` | **nothing** | `label` |
| `figma-auto-layout-saas` logo-cloud | logo_cloud | `logo-bar` | `logo` | `label` |
| `html-elementor-studio.section.3` | process_steps | `stats-band-3up` | `stat` | `number`, `title` |

**Two of the templates repeat nothing at all**, and that splits the six cleanly.
Asking for `item.event_type` on `cta-banner` is a category error: there is no
item for the field to belong to, and declaring one would not give the banner
anywhere to put a second value. The corpus's own annotations describe what is
really there — `harbor.about` has a `list_item` group of two bullets,
`riverkind.cta` a `list_item` group of two event types — and name those very
templates as acceptable. So a per-item field on a non-repeating template is now
held back, with the real question recorded: whether a split or a CTA should be
able to carry a short list. **That is one question, not four missing fields.**
Filed as TC-110.

The other two survive as genuine gaps, because their templates do repeat and
simply lack the field. Filed as TC-111, one section each, held under TC-109's
rule. One premise of mine died here: I expected the process-steps section to be
misrouted, since `icon-feature-list` is also acceptable and declares
`item.title`. Measured, it is the opposite — `icon-feature-list` would lose
*two* fields (`item.number` and `section_title`) where the stats band loses one,
so the matcher chose the template that keeps more. Pack 1.10.0 is part of why.

The new rule was proved three ways: removing it fails the positive test,
applying it to every field fails the guard that a section-level field on the
same template still ranks, and applying it regardless of the repeat group fails
the guard that `logo-bar`'s missing label still ranks.

**Evidence.** Suite 2,177 → 2,181 passing, 16 deselected. Benchmark aggregate
identical on all ten metrics, no threshold or regression failures. All three
sites re-analysed `--refresh --render` (`action == "execute"`) and re-planned
`--refresh`, all unchanged:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

The ranked queue falls from **7 gaps and 7 dropped fields to 3 and 3**, and all
three are single sections held deliberately: TC-109's kicker, TC-111's logo
label and step title. Nothing in the queue now has enough evidence to justify a
release, which is where the discipline says to stop rather than to widen.

### 2026-08-10 — pack 1.10.0: the evidence TC-104 waited four iterations for

Rank 1 of the reopened queue was `Content/stats-band-3up`/`section_title` at two
sections. **The classification check came from the corpus rather than from
judgement**, which is what makes this different from the four iterations that
held it: `html-dnn-services.harbor.stats` is annotated `acceptable_templates:
['stats-band-3up']` and carries a `section_title` heading "A dependable partner";
`html-elementor-studio.juniper.process` is annotated
`['stats-band-3up', 'icon-feature-list']` and carries "Our process". Both matched
a template their own answer key names, and both lost a heading the template had
no field for.

`stats-band-3up` gained a heading row mirroring `stats-grid-4up`'s, and its three
values moved from `heading_1..3` to `heading_2..4`.

**Closing an asymmetry leaves its excuse behind, and nothing said so.** The two
stat templates were a declared exception in TC-105's table — `stats-grid-4up` had
a heading and the band did not. With the band widened they agree, and the
exception became a description of something that no longer happens. Removing it
was in the brief; noticing that *nothing would have caught it if I had forgotten*
was not. The symmetry test now asserts that every declared exception still
describes a real asymmetry, and it was proved by putting the obsolete entry back
and watching it fail. An excuse for a problem the library no longer has reads as
a live exception to whoever decides what to work on next.

**Evidence.** Suite 2,177 passing, 16 deselected. Corpus:
`high_confidence_precision` **0.9444 (17/18) → 0.9474 (18/19)** as another
section reached high confidence; the other nine metrics unchanged, no threshold
or regression failures. All three sites re-analysed `--refresh --render`
(`action == "execute"`) and re-planned `--refresh`, all unchanged — none of them
uses a stats band with a heading:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

The ranked queue falls from **8 gaps and 9 dropped fields to 7 and 7**. What is
left is six `item.*` entries and TC-109's eyebrow. The `item.*` shape is new and
unexamined: a repeat group carrying fields its template's items do not declare —
`item.event_type`, `item.label`, `item.benefit`, `item.text`, `item.title`. Some
of those read like extraction naming rather than missing capability, and the next
iteration should find out which before widening anything.

### 2026-08-10 — TC-106: the corpus was dark, and it had seven gaps in it

**The filing's premise was wrong, and that is the whole result.** TC-106 said
closing it meant running the planner over benchmark cases, which would change
what the benchmark computes — a scoring-regime call. It does not. A match
already records which requirements its chosen template cannot meet, and the
planner copies *exactly those strings* into an entry's warnings. So the report
now reads matches for corpus cases and plans for projects, both speak one
vocabulary, and **the benchmark's aggregate is byte-identical** because nothing
was added to it.

What a match cannot report is losses that appear only at binding: an asset that
resolved to nothing, and the planner's second word about a capacity overflow.
Neither costs anything — the first is held back as an acquisition defect
wherever it is seen, and the second repeats a warning the match already made.

`load_benchmark_predictions` moved out of the benchmark command verbatim, into
`design/benchmark_corpus.py`, so both callers read one corpus rather than two.

**The queue went from 1 gap to 8.** Seven were invisible, on the five cases the
pipeline is actually measured against:

| rank | template | field | sections |
|---|---|---|---|
| 1 | `Content/stats-band-3up` | `section_title` | **2** (dnn-services, elementor-studio) |
| 2–3 | `CTAs/cta-banner` | `item.event_type`, `item.label` | 1 (figma-nonprofit) |
| 4 | `Cards/feature-cards-4up` | `eyebrow` | 1 (kts) |
| 5 | `Content/logo-bar` | `item.label` | 1 (figma-saas) |
| 6–7 | `Content/split-media` | `item.benefit`, `item.text` | 1 (dnn-services) |
| 8 | `Content/stats-band-3up` | `item.title` | 1 (elementor-studio) |

**Rank 1 is the evidence TC-104 was waiting for.** `stats-band-3up` was one of
the four templates left unwidened for want of a measured section; it now has two,
on two different cases, and both matched it correctly. It is a governed release
whenever someone wants to take it.

**The corpus also answers a question projects cannot**, and that turned out to
matter immediately. Annotations declare `acceptable_templates` per section, so
where a section matched something the corpus says is wrong, a loss on it is a
routing defect and not a missing field. One gap was exactly that:
`centered-hero`/`hero_media` on `figma-freeform-nonprofit`, whose annotation
expects `split-hero` or `split-media-reverse`. Widening `centered-hero` would
have bound the content and buried the reason it was reached — the same mistake
iteration 62 caught by hand on `keys-to-success`. It is now held back with that
reason, and a project, which has no answer key, is never second-guessed this way.

Every assertion was proved by breaking the property: removing the routing guard
fails it, treating an absent expectation as a mismatch fails the project guard,
and treating every expectation as a mismatch fails the guard that the corpus's
real gaps still rank.

**Evidence.** Suite 2,170 → 2,177 passing, 16 deselected. Benchmark aggregate
identical to the run before this change on all ten metrics; no threshold or
regression failures. All three sites re-analysed `--refresh --render`
(`action == "execute"`) and re-planned `--refresh`, all unchanged:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

`kts-fidelity` errored once during analysis and reproduced on retry, as it has
before; the figures above are from the successful run, not the stale artifact.

### Iteration 68 — a deliberate omission was being ranked as a gap, and the queue runs out

The report's remaining media entry was `video-feature`/`decorative_media` on
`keys-to-success.section.10`. The extractor puts it there on purpose: the
`_feature_media` branch keeps a mascot floated beside the video out of the
section's media, because counting it made the section overflow a template that
holds one picture. **The report was ranking that decision as a defect**, and
acting on it would have asked for a field whose only purpose is to undo it.

`decorative_media` is now held back with its reason recorded, alongside forms,
unresolved assets and unsupported interactions. Unlike the form rule this needs
no corroborating evidence in the plan: the role is assigned in exactly one place
in the codebase, and only where the decision was made. No template declares the
field, and none should.

An existing ranking test had used `decorative_media` as its example of a
one-section gap, so it stopped meaning what it said. Its data changed to a field
that really is one. Both new tests were proved in both directions — removing the
rule fails them, and widening it to hold back every field fails the guard that a
real loss on the same template still ranks.

**The ranked report is now one entry**, and that entry is deliberately not being
closed. `feature-cards-4up`/`eyebrow` is one section wanting a kicker above a
card grid. Widening one card template breaks the symmetry TC-105 asserts;
widening all eight is a large capability change for a single data point, which
is what 1.6.0's unmeasured half already cost. Filed as TC-109, to re-open when a
second section anywhere wants the same thing.

**Evidence.** Suite 2,168 → 2,170 passing, 16 deselected. Corpus unchanged on all
ten metrics, no threshold or regression failures. All three sites re-analysed
`--refresh --render` (`action == "execute"`) and re-planned `--refresh`:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

**Where the goal stands.** TM1 and TM2 are done. TM3 has run the ranked queue
from five gaps and eight dropped fields down to one, and the one that remains is
a judgement recorded rather than work outstanding. TM4 has its symmetry test,
its capacity ledger and its slot-position test; the regression test that the
report *stays* empty is not reachable, because the projects it would read are
build artefacts and are not committed.

What is left needs a decision rather than an iteration. **TC-106** would run the
planner over benchmark cases so corpus-wide really means corpus-wide — but that
changes what the offline benchmark computes, and a prior regime change moved a
site from 79.4 to 59.4 with no quality change, so it is a scoring-regime call.
**TC-104**'s four remaining templates and **TC-109** are both held on evidence,
which is the discipline working rather than a blockage. The loop stops here.

### Iteration 67 — a subtitle wearing the other name

TC-108, shipped as **agency pack 1.9.0**. I filed this last iteration as a
vocabulary split needing the alias table widened. Reading the seven component
trees says otherwise, and the smaller answer is the right one.

| template | first heading | second heading |
|---|---|---|
| `video-feature` | **`eyebrow`** | `title` |
| `bio-about` | `title` | **`eyebrow`** |
| `class-photo-cards-4up` | `section_title` | `subtitle` |
| `split-media`, `split-media-reverse` | `title` | `subtitle` |
| `cta-banner`, `cta-split` | `title` | `subtitle` |

**Six templates put the second heading below the first; five call it a subtitle
and one called it an eyebrow.** `bio-about`'s own sample copy gives it away —
"About Us" then "Jane Smith, Founder & CEO", which is a headline and the line
under it. The field is now `subtitle`. Two lines changed; the executable
template is byte-identical, so the audited executable digest did not move and
only the release payload did.

**The alias table needed nothing.** Both names mean what they say, and
`class-photo-cards-4up` is correctly named too: "Our Classes" over "Explore our
most popular classes" is an ordinary title and subtitle. It only read as
inverted because the `keys-to-success` page used those two slots for a kicker
and a headline — which is the page's choice, not the template's error.

**Nothing measured changed, and that is the honest report.** No plan bound
`bio-about.eyebrow`; the only eyebrow binding in the repository is on
`video-feature`, which keeps its field. The defect was latent: a section's
kicker binding to that slot would have been published *under* the headline it
belongs above, and a deck could never reach the slot built for it.

So the release ships with a test rather than a number.
`test_an_eyebrow_slot_opens_above_its_title_and_a_subtitle_follows_it` reads
each template's real slot order and asserts the name matches the position. It
was proved in both directions: restoring `bio-about`'s old name fails it, and so
does renaming `video-feature`'s correct `eyebrow` to `subtitle`.

**Evidence.** Suite 2,167 → 2,168 passing, 16 deselected. Corpus unchanged on all
ten metrics, no threshold or regression failures. All three sites re-analysed
`--refresh --render` (`action == "execute"`) and re-planned `--refresh`, all
unchanged:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

### Iteration 66 — the queue was asking for a body field to hold a kicker

The ranked report's top entry was `feature-cards-4up`/`body` on
`keys-to-success.section.5`. Acting on it would have given a card grid a body
field. The source says otherwise: `<div class="vj-text text-primary fw-bold
mb-1">Our Classes</div>` sits **above** `<h2>MOST POPULAR CLASSES</h2>`. It is a
kicker, and a card grid is right to have no field for body copy.

**`_eyebrow_for` already recognises this part — but only when the source spells
it as a heading.** A Vanjaro page spells it `div.vj-text`, and
`normalize_text_blocks` rewrites a text-bearing leaf div into a paragraph so the
half-dozen `find_all("p")` call sites can see it. That rewrite is what turned the
kicker into body copy: correct for its own purpose, and wrong here. A paragraph
above the headline is now read as an eyebrow, mirroring the heading rule, and
carries `implied: true` — the same admission `implied_title` makes when the
source had no heading element to report a level from.

**The content is still dropped, and that is the honest outcome.** Coverage does
not move; the loss is renamed from `body` to `eyebrow`. What changes is that the
queue now asks a true question. `feature-cards-4up` has no eyebrow field — but
neither does `class-photo-cards-4up`, which is the template this very page was
built from and which declares `subtitle` instead. Two templates in the library
say `eyebrow`, five say `subtitle`, and neither name aliases to the other, so one
editorial part is unreachable across most of the library. Filed as TC-108, with
the detail that `class-photo-cards-4up` ships "Our Classes" as the sample copy of
its `section_title` slot — the opposite of what the field names suggest.

**Three tests, and each was made to fail on purpose.** Disabling the new rule
fails the positive one. Removing its position check fails both guards, including
the pre-existing heading-eyebrow guard. Removing the precedence that lets a real
heading kicker win fails the third — but only after it was rewritten: as first
written it passed either way, because it asserted which eyebrow was reported and
not that the losing line survived. Without that assertion, a paragraph could be
skipped as an eyebrow that was never emitted, and vanish.

**Evidence.** Suite 2,164 → 2,167 passing, 16 deselected. Corpus unchanged on all
ten metrics, no threshold or regression failures. All three sites re-analysed
`--refresh --render` (`action == "execute"`) and re-planned `--refresh`:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

### Iteration 65 — the asymmetry becomes a failing check instead of a discovery

TC-105. No template changed and no pack was released; this iteration only makes
the next accidental asymmetry fail a test rather than cost a site three sections.

**"Templates sharing a repeat kind" is two properties, not one.** Grouping by
repeat kind puts `class-photo-cards-4up` beside `feature-cards-3up` because both
repeat a `card` — different designs that happen to share a generic word. It also
puts `blog-post-cards-3up` beside `-4up`, which are one design at two widths.
Only the second pairing carries an obligation strong enough that any difference
is a defect, and that pairing is the one the goal's problem statement leads with.

So there are two tests. The sharp one compares templates whose ids differ only
by their count suffix — four families, `blog-post-cards`, `feature-cards`,
`gallery` and `footer` — and has **one** exception: `blog-post-cards-3up` lacks
the `section_body` and `action` its wider twin declares. The broad one compares
by repeat kind and carries four declared exceptions, each with its reason: the
navbar pair differs by the CTA that is in its name, a class-card grid has a
subtitle the feature grids do not, a stats *band* has no heading where the
*grid* does, and the blog pair's gap again.

Section-level fields only, deliberately. `feature-cards-3up` offers a per-card
button and `-4up` does not, which is a real decision about a narrower card. What
the *section* can hold is not that kind of decision.

**Both tests were proved to fail.** A green suite can mean nothing was checking —
iteration 64's lesson — so each assertion was exercised by deleting a declared
exception and confirming the failure names the right templates and fields. The
first attempt to prove it went differently and taught something: mutating
`gallery-6up` to drop `section_body` was rejected by two *existing* invariants
before either new test ran, because a manifest may not drop a field whose
executable slot remains. That direction was already guarded. What was not
guarded, and now is, is a field that never arrives.

**The four unmeasured asymmetries are listed, not closed.** No site has asked a
3-up blog grid for a section body, a feature grid for a subtitle, or a stats band
for a heading. Widening them on symmetry alone would repeat pack 1.6.0, where the
half of the release with no evidence behind it helped nothing.

**Evidence.** Suite 2,162 → 2,164 passing, 16 deselected. Corpus unchanged on all
ten metrics, no threshold or regression failures. All three sites re-analysed
`--refresh --render` (`action == "execute"`) and re-planned `--refresh`, all
unchanged, all valid, none blocking:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.6667 | 0 | true | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

### Iteration 64 — the split pair catches up with the template it mirrors

TC-102, shipped as **agency pack 1.8.0**. `edca.home.section.2` is "Who is EDCA
Consulting?" over a picture and three paragraphs, and `split-media-reverse` owned
one body slot, so two paragraphs were dropped.

**TC-2 nearly sent this somewhere else.** A heading asking who a company is,
above a picture and three paragraphs, is an *about* section — and `bio-about`
already owns three body slots, so reclassifying it would have bound everything
with no release at all. Two things ruled that out. `bio-about` places its media
on the **left** and this section's is on the right, with no reversed variant, so
the content would have been bought with a mirrored layout. And the three
templates declare the identical layout — `split`, two columns — differing only in
media side and, arbitrarily, in how many paragraphs they can hold. That
asymmetry is the defect, not the classification.

So both halves of the mirrored pair were widened, not just the one with
evidence. Fixing only `split-media-reverse` would have left the library holding
three paragraphs when the picture is on the right and one when it is on the left,
which is the state TC-5 exists to prevent. Three slots, matching `bio-about`,
because that is the family's number — not because edca happens to need exactly
three.

**Nothing audited capacity, so this release added the ledger for it.** The
suite went green on the first run, which was itself the finding: the field
ledger makes *adding a field* deliberate, but `slots_per_owner` could go from
one to three with only the executable digest to notice — and a digest records
that something changed, not that anyone meant it. `test_section_field_capacity_
matches_the_audited_ledger` now pins every section-owned multi-slot field. Writing
it immediately turned up one I had not known about: `contact-section` holds three
contact lines. Seven fields are audited; everything else owns one slot.

**Evidence.** Suite 2,161 → 2,162 passing, 16 deselected. Corpus unchanged on
all ten metrics, no threshold or regression failures. All three sites re-analysed
`--refresh --render` (`action == "execute"`) and re-planned `--refresh`:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.25 → **0.6667** | 1 → **0** | false → **true** | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.9412 | 0 | true | 2 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

**`edca-pilot` produces a valid plan for the first time.** Its section 2 now
scores 0.9288 high; the capacity shortfall had been multiplying its match score
down, so widening the template both bound the paragraphs and lifted the section
above the confidence floor. Its one remaining loss is the contact form, which is
policy rather than a defect — forms are never rebuilt from a template.

The ranked report is down to **two gaps and two dropped fields**, both single
sections on `kts-fidelity`, and neither has a filed task: the "Our Classes"
eyebrow and a decorative mascot. Every backlog item with measured evidence
behind it is now closed.

### Iteration 63 — a card-shaped grid learns what kind of thing it holds

TC-107. Two of `keys-to-success`'s card sections are a grid of instructors and a
grid of blog posts, and both were being built as generic feature cards.

**There is no evidence in the cards themselves.** Both grids are picture,
heading, one short line — no link, no date, no excerpt, no author. The existing
`_looks_like_blog_cards` detector wants a "Read More" link or a `post`-classed
block with a forty-character excerpt, and correctly finds neither. A detector
that reads only the items has nothing to go on, which is why both templates
built for people and for posts were unreachable from any HTML source.

**What separates them is the heading the section gives itself.** "MEET THE
INSTRUCTORS" over a grid says what the grid holds, in the author's own
visitor-facing words. This is not a new idea in the codebase: the Figma adapter
already classifies `team_grid` from "team"/"instructors"/"people cards" and
`blog_cards` from "blogs"/"articles"/"latest news", read off a frame's name. The
HTML side had no equivalent, so this is parity rather than invention — and the
two adapters now produce the same role vocabulary.

**The first version read the wrong heading.** It took `content["headings"][0]`,
which is the *section's* heading only when the section has one; where it does
not, the first heading belongs to the first card. An existing test caught it
immediately — a fixture of three `<article>` posts titled "Post One", "Post Two"
and "Post Three" became a blog grid on the strength of a card title. The rule
now reads the first heading that lies outside every card, and returns nothing
when there is none.

**Then the sections stopped binding altogether, and the corpus never noticed.**
With the new roles in place, kts coverage fell 0.8971 → 0.5147 and two sections
began blocking. `html_ownership` decides the repeat kind from the section role,
and `team_grid`/`blog_cards` were in none of its four role sets — so no group
was built at all, the cards collapsed into section-level content, and both
sections matched `CTAs/cta-split` at semantic compatibility 0.000. The offline
benchmark stayed at 1.0 throughout, because no benchmark case has a team or blog
grid. **Only the three real sites showed it.** The four scattered role sets are
now one named map of card-grid roles to what their cards are.

**Evidence.** Suite 2,156 → 2,161 passing, 16 deselected. Corpus unchanged —
all ten metrics identical, including `semantic_role_accuracy` 1.0 and
`template_top1_accuracy` 0.92, with no threshold or regression failures. All
three sites re-analysed `--refresh --render` (`action == "execute"`) and
re-planned `--refresh`:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.25 | 1 | false | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.8971 → **0.9412** | 0 | true | 5 → **2** |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.8182 | 0 | true | 0 |

Section 7 matches `team-member-grid-4up` at 0.9589 **high**, up from
`feature-cards-4up` at 0.9204 medium; section 8 matches `blog-post-cards-4up` at
0.9509 **high**, up from 0.9000 medium. Both are the templates the source page
was built from. The ranked report falls from five gaps and eight dropped fields
to **three gaps and three dropped fields**, each now a single section.

### Iteration 62 — the top-ranked gap was not a gap, and the second one was

The report's rank 1 was `Cards/feature-cards-4up`/`body`, three sections of
`keys-to-success`. TC-2 requires proving the section is classified correctly
before widening anything, so I read the source rather than the plan.

**Two of the three sections are routed to the wrong template.**
`keys-to-success.section.7` is a grid of instructors and `.section.8` a grid of
blog posts, and their source markup is `team-member-grid-4up` and
`blog-post-cards-4up` — templates that already declare `section_body`, in the
very slot the dropped copy occupies. Both were matched to `feature-cards-4up`,
which does not declare it, and neither correct template appears in the top three
alternatives. The cause is that the extractor gives every card-shaped repeat
group the kind `card` and the role `feature_cards`, so a person, an article and
a feature are the same thing to the matcher. **Widening `feature-cards-4up`
would have bound the copy and buried the routing defect** — the report would
have gone quiet while a team grid kept being built as generic feature cards.
Filed as TC-107. This is the recurring failure in a new dress: a *shape* is not
a kind of thing, just as a tag is not.

The third section is different again. `section.5` really is a
`class-photo-cards-4up` section, but its copy — "Our Classes" — sits *above* the
headline as an eyebrow, not below it as a deck. TC-103 was filed calling it "the
short line that introduces the cards"; it is not a line that introduces
anything, and its extracted order (13, after every card) does not match the
source either.

**Rank 2 verified clean, so that is what shipped.** Northstar's section 4:
role `testimonials` at 0.95 confidence, repeat kind `testimonial`, two quotes
with authors, matched to `Cards/testimonial-cards-3up` at 0.87 against a next
alternative of 0.40. Correctly classified, correctly routed, and the template
simply had no field for the heading "Trusted by focused teams". **Agency pack
1.7.0** declares `section_title` on it; the three authors move from
`heading_1..3` to `heading_2..4`.

One capability change, per TC-3. The other four templates lacking `section_title`
stay unverified — no section anywhere has demanded a heading from them, and
1.6.0's lesson is that the unmeasured half of a release helps nothing.

**Six tests failed and none was adjusted to pass.** The audited field ledger and
the slot-key contract were updated deliberately, because changing them *is* the
release. `_testimonial_columns` indexed `components[0]` to find the grid, which
the new heading displaced — replaced with a search by type, since a position is
not a kind of thing either. The column-expansion test still passed untouched,
but its overrides no longer meant what its docstring said, so its data was
corrected to a section heading plus four quote-author pairs. Two tests I wrote
in iteration 61 used `testimonial-cards-3up` as the example of a template that
*still* lacks a section title; that became false, so they moved to
`pricing-cards-3up`, which preserves what they were testing.

**Evidence.** Suite 2,156 passing, 16 deselected. Corpus: nine of ten metrics
unchanged; `high_confidence_precision` **rose 0.9333 (14/15) → 0.9444 (17/18)**
as more sections reached high confidence. No threshold or regression failures.
All three sites re-analysed `--refresh --render` (`action == "execute"`) and
re-planned `--refresh`:

| site | sections | provenance | style obs | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.25 | 1 | false | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.8971 | 0 | true | 5 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.7727 → **0.8182** | 0 | true | 1 → **0** |

**The control site now loses nothing.** It has never been the target of a fix,
which is the point: the gap that closed it was found by measurement across the
corpus rather than by looking at the site in hand. The ranked report falls from
five gaps and eight dropped fields to four and six, with two entries correctly
reported as stale rather than ranked.

### Iteration 61 — the join exists, and it found two gaps nobody had filed

TC-101. `design/capability_gaps.py` reads every composition plan under a
workspace root, attributes each loss to the template that produced it,
aggregates across projects and ranks by sections lost. Surfaced as
`vanjaro project capability-gaps [ROOT] [--json] [--held-back]`.

The acceptance criterion was that it reproduce the two known gaps without being
told. It did, and the ranking is not what the backlog assumed:

| rank | template | field | kind | sections |
|---|---|---|---|---|
| 1 | `Cards/feature-cards-4up` | `body` | no field | 3 (kts) |
| 2 | `Cards/testimonial-cards-3up` | `section_title` | no field | 2 (northstar, pilot-measure) |
| 3 | `Cards/feature-cards-4up` | `primary_action` | no field | 1 (kts) |
| 4 | `Content/split-media-reverse` | `body` | owns 1, needs 3 | 1 (edca) |
| 5 | `Content/video-feature` | `decorative_media` | no field | 1 (kts) |

Ranks 3 and 5 were not in the backlog at all. Rank 2 is TC-104's evidence
arriving early and from the control site: `testimonial-cards-3up` has no
section title, and that costs a heading on Northstar today — TC-104 was filed
from a library survey and assumed it might route to nothing.

**A loss is not the same thing as a capability gap, and ranking one that is not
sends the next iteration to widen a template that is behaving correctly.** Three
kinds are held back with the reason recorded rather than dropped: a form field
(a form is never rebuilt from a template, so the fix would be to give a template
a field it must not have), an asset that resolved to nothing (the template owned
the slot; the picture never arrived), and an unsupported interaction (a missing
behaviour is not a missing field). Eleven losses across the four projects are
held back this way — and the form-field rule keys on whether the plan carries
the form's inventory, not on the field's name, so a form the pipeline silently
dropped still reads as a gap.

**Two shapes of loss, and the existing counter only sees one.**
`_content_losses` matches `source field 'X' is not editable by template`, so
edca's overflow — `body needs 3 slots, template owns 1` — has never been counted
as a loss anywhere. That is why edca reports one content loss while dropping two
paragraphs. The report reads both, plus the static-only shape, and folds the
matcher's and the planner's report of the same overflow into one gap: counting
warnings would rank a capacity gap above a missing field purely for being
mentioned twice.

**The report is only as fresh as the plans it reads, and some plans cannot be
refreshed.** The first run ranked `feature-cards-3up`/`section_title` — a gap
pack 1.6.0 closed. `pilot-measure`'s plan predates the release and must not be
re-analysed, because that invalidates the `portal_mutation` approval already
granted. So each gap is now checked against the library as it stands rather than
against the day the plan ran, and one that the catalogue has since closed is
reported as stale instead of ranked. The check proves itself on this data:
`feature-cards-3up` moves to stale, `testimonial-cards-3up` stays live.

**Not included, deliberately.** The offline benchmark never builds a composition
plan, so no benchmark case can report a gap. Filed as TC-106 rather than
extending the report into the benchmark, because that changes what the benchmark
computes.

**Evidence.** Suite 2,134 → 2,156 passing, 16 deselected. Corpus unchanged: all
ten metrics at their established values (`responsive_observation_coverage`
0.8864, `template_top1_accuracy` 0.92, `high_confidence_precision` 0.9333, five
extraction metrics 1.0), no threshold failures, no regression failures. All
three real sites re-analysed with `--refresh --render` (`execution.action ==
"execute"`) and re-planned with `--refresh`:

| site | sections | provenance | style observations | coverage | blocking | valid | losses |
|---|---|---|---|---|---|---|---|
| `edca-pilot` | 4 | 4 rendered | 124 | 0.25 | 1 | false | 1 |
| `kts-fidelity` | 11 | 11 rendered | 352 | 0.8971 | 0 | true | 5 |
| `northstar-recheck` | 5 | 5 rendered | 155 | 0.7727 | 0 | true | 1 |

All three are byte-identical to iteration 60, which is the expected result for a
change that adds a reader and touches no part of the pipeline.
