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

### TC-105 — Family symmetry becomes a test

**Dependencies:** TC-103, TC-104

Assert that templates sharing a repeat kind declare the same section-level
fields, with deliberate exceptions declared in the test. This is what turns the
work above from six fixes into a property.

## Completion rule

Passing tests or shipping one pack release does not complete this goal. It
remains active until TM1–TM4 are implemented, the gap report is empty across the
corpus and all three real sites, and the symmetry test makes the next accidental
asymmetry a failing check rather than a discovery.

## Progress log

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
