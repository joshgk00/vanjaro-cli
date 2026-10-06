# Real-Source Trial Goal

**Status:** Active
**Started:** 2026-09-25
**Owner:** Josh Slaughter (Clicks and Mortars)
**Driver:** Claude, working on its own inside the limits below
**Parent goal:** `agency-tool-goal.md`

## Goal

Prove the agency tool on real client material, not synthetic fixtures. Take
one real project per source kind (Figma, live website, and images) from intake
to a verified, handoff-ready hidden build on a local test portal. Get a real
fidelity score for each one. Fix every tool defect the trials expose so the
next project needs less hand work.

This is the missing evidence behind the parent goal's success measures. As of
2026-09-25, every benchmark case is synthetic, and all 11 project workspaces
are live-HTML projects. No real Figma or image project has reached verify.

## Why this goal exists

The first real Figma trial (`artifacts/projects/kts-figma-trial`, 2026-09-25)
got through analyze, plan, and every build stage, and then stalled:

- Analyze and plan were strong. There were 12 sections, editable coverage was
  9/9, and native blocks were 9/10. The one blocker was real: a stat value drawn
  as vector outlines. An audited overlay fixed it.
- Publish needs a completed verify. Verify needs capture evidence. Capture
  sees only published content, and the new page is an unpublished draft. The
  standard workflow cannot finish a fresh build.

The tool only gets better through trials like this, so the trials drive the
backlog.

## Success measures

| Measure | Required result |
|---|---|
| Real trials that reach a completed `verify` stage | 3 (Figma, live HTML, image) |
| Each trial has a scored desktop fidelity capture | Yes, with the score recorded |
| Each trial has an editor handoff report | `vanjaro project handoff` output saved |
| Plan quality per trial | Editable ≥ 0.85, native ≥ 0.90, no-generic-fallback ≥ 0.90 |
| Fidelity per trial | ≥ 75 desktop draft threshold, or a ranked list of what blocks it |
| Workflow defects found by a trial | Fixed with tests, or filed below with evidence |
| Non-integration test suite | 100% passing after every change |
| Offline benchmark corpus (`vanjaro migrate benchmark-all`) | No metric moves down |

Hands-on time savings (the parent goal's 60% target) need Josh's baseline
numbers. This goal records the tool's own time and hand steps per trial so that
comparison becomes possible later. It does not claim a saving.

## Authority

Josh said on 2026-09-25: "I want you to drive this." In practice, that means
the following.

### Claude may do these without asking

- Read any repo file, run tests, run offline benchmarks, and read from Figma
  with the token in `.env`.
- Create and change trial workspaces under `artifacts/projects/`.
- Record audited overlays when the source itself shows the right value, such as
  exported pixels or a sibling pattern. Cite the evidence in `--reason`.
- On local test portals only (`http://vanjarocli.local/*` and
  `http://vanjarobaseline.local`), run any project-owned stage: pin or check a
  target, upload assets, add blocks, create **hidden** draft pages, create
  project-prefixed header/footer blocks, capture, verify, and write the handoff.
- Log back in to local portals with `.env` (per the existing re-auth rule).
- Fix tool code, with tests, and commit to `main` in this repo (standing
  permission from 2026-06-10). Push after each finished unit.
- Update this document's progress log and the project memory.

### Claude must stop and ask Josh for these

- Resolving a tool approval gate (`vanjaro project approval resolve`). The
  tool's safety check blocks self-approval. Claude batches requests and hands
  Josh the exact commands. Josh can remove this stop by adding a permission rule
  for that command.
- Publishing any page content, even a hidden page this goal owns
  (`vanjaro content publish`). The safety check blocked this on 2026-09-25.
- `vanjaro project launch`, or anything that makes a page visible, puts it in a
  menu, replaces a homepage, or swaps the live site header/footer.
- Any change to theme settings, or to pages and blocks this goal did not create.
- Any non-local site, a new portal, or any credential or password change.
- Picking the real live website and real image mockups for trials 2 and 3,
  unless Josh already named them.
- New dependencies, and agency pack releases (governed releases stay Josh's
  call).

### 2026-10-05 update: Claude runs this as project manager

Josh said on 2026-10-05: "I want you to drive the efforts and coordinate.
Own the follow up and decisions. If there's anything that is reversible and
non destructive, feel free to make the call. Only bring things to me if you
truly can't decide or the effect will be hard to unwind or revert."

What changes:

- **Team.** Claude (Opus) plans, assigns, reviews, and commits. Coding goes to
  the `sonnet-implementer` helper (`.claude/agents/sonnet-implementer.md`,
  Sonnet at extra-high effort). Claude checks every helper result itself:
  reads the diff, reruns the suite, and rejects work that doesn't prove its
  claim. A helper's report is a claim, not proof.
- **Trial sources.** Claude may now pick the real live website and image
  mockups for the remaining trials, using sources already in this repo's
  history (earlier benchmark sites, the Keys to Success mockups). Reading a
  public site is reversible. Josh can swap the pick at any time.
- **Ranking and scope.** Claude reorders the backlog, adds items, and closes
  items without asking.

What does not change: everything in the "must ask" list above still goes to
Josh. Publishing, launch, approval gates, theme changes, and server installs
are hard to undo, so they stay his. Claude batches those asks into one
message with exact commands, and keeps working on other items while waiting.

### Stop conditions

Stop and report when any of these happens:

- A step would need an action from the "must ask" list.
- The test suite or benchmark goes down and a fix isn't clear within two tries.
- The site does something unexpected, such as a changed object Claude didn't
  create, a login failure after re-auth, or a lock the tool won't clear.
- Three work units in a row produce no measurable progress.

## Working loop

One bounded unit at a time:

1. Pick the highest-ranked open item below.
2. State the claim that proves it done, in a checkable form.
3. Do the work. Code changes come with tests. Portal steps use the tool's
   dry-run receipt before every apply.
4. Run `pytest -m "not integration"`. For extraction or matching changes, also
   run `vanjaro migrate benchmark-all`.
5. Commit, push, and add an entry to the progress log below.

## Backlog

| ID | Rank | Work | Evidence |
|---|---:|---|---|
| RT-1 | done | Break the publish ↔ verify ↔ capture loop for fresh builds. Done 2026-09-26: the fidelity gate moved from verify to launch. Either capture can see an owned hidden draft, or a supported path publishes an owned hidden page before verify. | KTS trial: capture says `captured output has no agency sections` on page 188 (`is_published: false`). `publish prepare` refuses with `verification_incomplete`. |
| RT-2 | 2 | Finish KTS Figma trial 1: capture, verify, handoff, fidelity score. | `artifacts/projects/kts-figma-trial` |
| RT-3 | done | Done 2026-10-05 (`8397ca1`). `vanjaro --profile X auth login --url …` ignores the global `--profile` and saves to the hostname profile, overwriting its `base_url`. Honor the global flag, or refuse the conflict. | 2026-09-25 login wrote the child-portal URL into `vanjarocli-local`. |
| RT-4 | done | Done 2026-10-05: vector groups export as SVGs; KTS analyze warnings 77 -> 4 (`kts-figma-trial-3`). Check at build that the site accepts .svg uploads. Figma: 73 `FIGMA_VECTOR_EXPORT_UNRESOLVED` warnings (icons). Find out why vector exports fail and whether icons reach the build. | KTS analyze report |
| RT-5 | 5 | Figma sources with no tablet/mobile frames: say plainly in the plan and verify output that these breakpoints are inferred, and don't count them as missing evidence the operator can fix. | KTS capture: tablet/mobile `reference_not_declared` |
| RT-6 | done | Done 2026-10-05 (`8397ca1`). `project capture --references` resolves the path against the workspace, not the current directory. Accept either, or say so in the error. | 2026-09-25 "does not exist" error on a correct repo-relative path |
| RT-8 | done | Done 2026-10-05 (`825b6e8`): the scorer already paired Figma frames; the real block was that a desktop-only design always got tablet/mobile blockers. Static designs are now scored on the breakpoints they declare, against the draft thresholds. Re-scoring trial 1 read-only gives 66.66 (below 75; header, footer, and video sections score low). Figma static references are captured but never scored: `no valid source-paired comparisons recorded`. Wire Figma frame evidence into the fidelity scorer. | KTS capture evidence `qa/capture-evidence/8569cce6….json` |
| RT-9 | 3 | KTS visual gaps found by eye: header/footer render empty (globals are still drafts); class cards lose their colored panels and some titles (Prelude, Symphony); team photos aren't circles and the grid is uneven; headings render underlined; hero is much shorter; marquee color is wrong. | Figma vs page 188 screenshots, 2026-09-25 |
| RT-10 | done | Done 2026-10-05: launch refuses `visual_fidelity_unbound`. Capture records don't record which publish they measured, so evidence taken before publication, or against an earlier publish, still counts at launch. Bind the publish receipt fingerprint into capture records and reject mismatches at launch. | 2026-09-26 review of the RT-1 change |
| RT-11 | done | Done 2026-09-26: `vanjaro project overlay set-action-url`. No audited way to give a button or link its destination. Figma designs rarely carry URLs, so every Figma project will stop at `N source action(s) have no URL mapping`. Add an overlay (for example `overlay set-action-url`) that records the operator's destination with provenance, and feeds plan and pages. | Trial 2: 12 actions (Register Now, Contact Us, Learn More ×5, Join Now, Load More, Call Me, Schedule a Free Call) |
| RT-12 | done | Footer builder rendered every footer entry as plain text and ignored link destinations, so Contact Us, Call Me, and Schedule a Free Call lost their `/contact-us` links. Done 2026-09-27: entries with a safe destination render as links. | Trial 2 `build/global-blocks-desired.json` footer had 0 hrefs |
| RT-13 | done | Done 2026-09-27: verify compares design destinations with built link hrefs. Verify counts missing destinations in the design, not in the built blocks, so RT-12 passed verify. Check built page and global link hrefs against the design's destinations. | Trial 2 verify: `missing_action_url_count: 0` while the footer had no links |
| RT-14 | done | Done 2026-10-05: logo exports; brand falls back to the Figma file name. Header brand falls back to the project name ('Kts Figma Trial 2') because the logo is 50 vector fragments with no export URL. Use the client or site name, and fix vector export (see RT-4). | Trial 2 verify warning |
| RT-15 | done | Done 2026-09-28: module committed (`1829c474`, local branch `vanjaro-ai-module-phase1`) and installed on the local site (old file kept as `Vanjaro.AI.dll.bak-20260927`). Publish prepare now passes. The local site's server module doesn't advertise `supportsExactVersionPublish` for global blocks, so `project publish prepare` refuses. The support exists only as **uncommitted** changes in the `vanjaro-ai` repo's `source` folder (AIGlobalBlockController, AIPageController, AILaunchController, models). Publish and launch have only run against mocks. Review, commit, build, and deploy the module to the local test site. | Trial 2 `publish prepare`: `portal global block endpoint does not advertise exact-version publication support` |
| RT-16 | done | Done 2026-10-05 (`9024841`): `init --source-origin`. EDCA saved page now plans valid, editable 0.69, 0 blockers (was 0.08, 3 blockers). Picture downloads at build may still be refused by the site. A saved copy of a live page loses its home address, so every relative picture path turns into `file:///…` and can't be fetched. Sites that block scripts (EDCA, Oasis) can only be trialed from a saved copy. Let the operator declare the original URL for a saved page, and use it for asset paths. | `artifacts/projects/edca-trial-1`: 3 blockers, all "asset was never acquired", editable 0.08 |
| RT-17 | partly done | 2026-10-05: card rows fixed; real re-plan editable 0.25 -> 0.42, losses 32 -> 5 (`artifacts/projects/qualityhc-trial-2`). Still open: hero (1), merged band (2), split media (7), merged reviews/FAQ (8); see RT-19. Card lists on a real site land on picture-only gallery templates, so card titles, text, and buttons are dropped. | `artifacts/projects/qualityhc-trial`: editable 0.25, 4 blockers, 6 sections lose `item.body`/`item.item_title` |
| RT-18 | done | Done 2026-10-05 (`9024841`). `project init` can't take a local file source: it needs an empty folder, but analyze needs the file inside it. Copy local sources into `sources/` at init. | `kts-mockup-trial` and `edca-trial-1` needed a hand edit of project.json |
| RT-19 | done | Done 2026-10-06: live re-plan editable 0.75, 2 blockers (`qualityhc-trial-3`). The Quality HC page is built with the YOOtheme page builder (`div.uk-section`). The tool finds no section edges in it, so sections fall back to the old guesswork path and some get merged (reviews + FAQ + services in one). Teach section detection about this builder. Also keep the fetched page HTML in the workspace so later steps and test fixtures can reuse it. | RT-17 helper report; `qualityhc-trial-2` sections 2, 7, 8 |
| RT-20 | 1 | Quality HC FAQ blocks: items carry title/body, the FAQ template wants question/answer, and the accordion interaction is unsupported. | `qualityhc-trial-3` section 10 |
| RT-21 | 2 | Quality HC hero blocks: 2 buttons and 3 badges, but no hero template has 2 actions. Needs a template change (agency pack release, Josh's call) or an audited overlay. | `qualityhc-trial-3` section 2 |
| RT-22 | 4 | The browser-render observation script does not know UIkit sections, so `--render` on these pages can't pair sections. | RT-19 helper report |
| RT-7 | 7 | Trial sources. Live website: Quality HC (`https://quality-hc.com/`, portal 1) picked 2026-10-05 because EDCA and Oasis refuse script downloads. Images: Keys to Success mockups, still to set up. | `artifacts/projects/qualityhc-trial` |

## Progress log

### 2026-09-25 — Trial 1 started (KTS Figma)

- New workspace `artifacts/projects/kts-figma-trial`, pack 1.12.0, target portal
  2 (`keys-to-success`). The historical July workspace is untouched.
- Analyze took 15 seconds: 1 page, 12 sections, 77 warnings (73 vector exports,
  3 fonts, 1 missing mobile frame).
- Plan blocker: the "Happy Students" stat value is outlined vector art (layer
  `239:1193`). An exported render shows ∞. Recorded overlay
  `kts-stats-happy-students-value`. The plan is now valid: editable 9/9,
  native 9/10, no-generic-fallback 9/10.
- Josh approved the plan and portal-mutation gates. Applied theme (preserve, no
  portal change), assets (24 uploads, 55 MB), library (10 blocks), pages
  (hidden page 188), and globals (2 project header/footer blocks plus a page
  update).
- Stuck at verify. See RT-1.
- RT-1 finding: Vanjaro shows only published content outside its page editor.
  Logged-out and logged-in browsers both get an empty page for draft 188.
  The page allows anonymous view but isn't in the menu. The tool's order
  (verify before publish) can't finish a fresh build unless the operator
  publishes the hidden page first. Publishing is Josh's action.
- Josh granted the publish. Page 188 was backed up
  (`qa/page-188-before-publish.json`), then published. It's still out of the
  menu. The desktop capture succeeded.
- The loop is worse than first thought: verify now refuses with `managed page
  'kts-figma-trial-home' is visible or published`. Verify needs capture,
  capture needs published content, and verify rejects published pages. RT-1
  needs a design change to the stage order.
- Scoring: the tool's scorer returns `not_scored` for Figma references (RT-8).
  Eye review: nearly all text and images arrived, including the ∞ stat, but the
  visual match is far off (RT-9). This is a rough estimate, not a measured
  score: about 90% of the content and less than half of the look.

### 2026-09-26 — RT-1 fixed: the look score gates launch, not publish

- Josh chose to move the look score to launch rather than add a preview step,
  after the code showed that publish already publishes only hidden content.
- Verify no longer scores fidelity or needs `qa/fidelity-evidence.json`.
  Handoff drops the fidelity check (verification weight 15 → 25).
- Launch prepare refuses `visual_fidelity_failed`. Apply refuses
  `visual_fidelity_stale` if evidence changed after the receipt, but a
  completed launch's GET-only re-entry skips the re-score. Legacy
  single-file evidence and unreadable evidence both refuse.
- Launch receipt format is now `agency-launch-review-v2`. The compatibility
  policy and release contract digests were updated to match.
- Suite 3,439 passed. Found during review and filed as RT-10: capture records
  aren't tied to a specific publish.

### 2026-09-26 — Trial 2 (clean run in the new order)

- `artifacts/projects/kts-figma-trial-2`: same Figma source, pack 1.12.0, and
  the ∞ overlay. Josh approved the plan and portal-mutation gates.
- Built hidden page 189, 24 assets, 10 blocks, and 2 project header/footer
  blocks. Every portal action was a create, apart from the one update to
  the trial's own page 189.
- Verify completed: source text coverage 1.0, and one blocker, `12 source
  action(s) have no URL mapping`. Handoff scored 65/100, `review_required`.
  Only `action_urls` and `verification` fail, both from the same cause.
- The KTS test portal has no Contact, Register, Classes, or Blog pages, so
  there are no real destinations to map to. Blocked on Josh (destinations)
  and RT-11 (a way to record them).
- Page 188 from trial 1 remains as a hidden leftover.

### 2026-09-27 — Trial 2 is publish-ready, but the server can't publish

- Added all 12 link targets with `overlay set-action-url`. Fixed the footer
  dropping links (RT-12), versioned the footer composer so plans rebuild, and
  made verify check the built links (RT-13). Josh re-approved twice.
- Verify: valid, 0 blockers, text coverage 1.0, every destination built.
  Handoff: `publish_ready`, 100/100.
- `publish prepare` refuses because the local server module is older than
  the tool's publish contract (RT-15). The needed server code is uncommitted
  in the vanjaro-ai repo. Stopped for Josh: deploying server code is outside
  this goal's authority.

### 2026-09-28 — Server module installed, publish waits on Josh

- Josh approved installing the server module. It's in, the site restarted
  and answers `ok`, and the old file is kept as a backup.
- `publish prepare` passed and saved `qa/publish-review.json` for the
  header, footer, and page 189 (all hidden). Publishing needs Josh's approval
  gate.

### 2026-10-05 — Claude takes over as project manager

- Josh handed over day-to-day decisions (see Authority). Opus plans and
  reviews; the Sonnet helper writes code.
- Next, in parallel with the publish ask: RT-8 (score Figma references),
  then RT-10, then the small fixes RT-3 and RT-6.

- Picked the live-website trial. EDCA and Oasis both cut the connection on
  any script download (normal sites like quality-hc.com answer fine), so
  Quality HC is the trial (`artifacts/projects/qualityhc-trial`, portal 1).
  Analyze: 10 sections. Plan: editable 0.25, native 1.0, 4 blockers. Filed
  RT-17 (card lists lose their text) and RT-16 (saved pages lose their home
  address). Leftover empty workspaces from the failed starts:
  `edca-live-trial`, `edca-trial`, `edca-trial-1`, `oasis-trial`.
- Done: RT-3, RT-6, RT-8 (helpers wrote them, Claude reviewed and reran the
  suite on main: 3,462 passed). Policy call made: a design that only has a
  desktop frame is judged on desktop alone. Easy to tighten later.
- Image trial set up as `artifacts/projects/kts-mockup-trial` (the 1440x8090
  Keys to Success mockup, portal 2). The next step sends the mockup to
  OpenAI to read it, which is Josh's call (sharing a client file outside).
- In progress with helpers: RT-17, RT-10, RT-16 + RT-18.
- RT-16 and RT-18 done (`9024841`, suite 3,475, benchmark no regressions).
  `artifacts/projects/edca-trial-2` (saved EDCA page + its origin) plans
  valid: editable 0.69, native 1.0, 0 blockers. Kept as a backup live trial.
- RT-10 done (suite 3,488). Any capture taken before a publish must be retaken after it.
- RT-17 card fix landed (suite 3,506, benchmark flat). Quality HC real re-plan: editable 0.42, 4 blockers left. Filed RT-19 (page-builder section edges).
- RT-4 and RT-14 done (suite 3,518). Fresh KTS Figma analyze: 12 sections, 4 warnings (was 77).
- RT-19 done (suite 3,552, benchmark flat). Live Quality HC: editable 0.75, native 1.0, blockers: hero (RT-21), FAQ (RT-20).
