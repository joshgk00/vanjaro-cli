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
| RT-3 | 3 | `vanjaro --profile X auth login --url …` ignores the global `--profile` and saves to the hostname profile, overwriting its `base_url`. Honor the global flag, or refuse the conflict. | 2026-09-25 login wrote the child-portal URL into `vanjarocli-local`. |
| RT-4 | 4 | Figma: 73 `FIGMA_VECTOR_EXPORT_UNRESOLVED` warnings (icons). Find out why vector exports fail and whether icons reach the build. | KTS analyze report |
| RT-5 | 5 | Figma sources with no tablet/mobile frames: say plainly in the plan and verify output that these breakpoints are inferred, and don't count them as missing evidence the operator can fix. | KTS capture: tablet/mobile `reference_not_declared` |
| RT-6 | 6 | `project capture --references` resolves the path against the workspace, not the current directory. Accept either, or say so in the error. | 2026-09-25 "does not exist" error on a correct repo-relative path |
| RT-8 | 2 | Figma static references are captured but never scored: `no valid source-paired comparisons recorded`. Wire Figma frame evidence into the fidelity scorer. | KTS capture evidence `qa/capture-evidence/8569cce6….json` |
| RT-9 | 3 | KTS visual gaps found by eye: header/footer render empty (globals are still drafts); class cards lose their colored panels and some titles (Prelude, Symphony); team photos aren't circles and the grid is uneven; headings render underlined; hero is much shorter; marquee color is wrong. | Figma vs page 188 screenshots, 2026-09-25 |
| RT-10 | 4 | Capture records don't record which publish they measured, so evidence taken before publication, or against an earlier publish, still counts at launch. Bind the publish receipt fingerprint into capture records and reject mismatches at launch. | 2026-09-26 review of the RT-1 change |
| RT-7 | 7 | Trial 2 (live website) and trial 3 (images): need Josh to name the sources. | none yet |

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
