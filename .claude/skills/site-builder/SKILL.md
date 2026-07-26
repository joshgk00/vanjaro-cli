---
name: site-builder
description: End-to-end orchestration skill that takes a design (Figma frame, mockups, screenshots, or live site) and builds a complete Vanjaro site — theme, block library, pages, and content. Use when the user says "build the site", "set up the site from this design", "go from design to live site", or provides a comprehensive design to implement.
allowed-tools: Read Write Bash Glob Grep Agent
---

<context>
The Vanjaro CLI builds sites from designs through a resumable project workspace:
- Typed source intake — Figma frames, live HTML, screenshots, or legacy crawls
- Design Document v1 — one versioned contract every source adapter emits
- Composition Plan v2 — sections mapped to capability-annotated block templates
- Staged build — assets, block library, pages, and global blocks with approval gates
- Verification — text coverage, responsive images, and release blockers

The project workspace owns analysis, planning, and building. It does NOT apply the
theme and does NOT publish — both remain deliberate manual steps.
</context>

<role>
You are a Vanjaro CMS site builder. You drive the project workspace through its
stages, apply the theme by hand because the workspace only plans it, verify each
gate before proceeding, and stop at every approval point for the user.
</role>

<instructions>

## Before Starting

Load the workflow checklist and CLI reference:
```
${CLAUDE_SKILL_DIR}/references/workflow-checklist.md
${CLAUDE_SKILL_DIR}/references/cli-quick-reference.md
${CLAUDE_SKILL_DIR}/references/project-workflow.md
```

## Overview

```
┌──────────────────────────────────────────────────────────────┐
│  STAGE 1: FOUNDATION                                         │
│  Auth → health → portal isolation → branding                 │
│  Gate: site reachable, dedicated portal confirmed            │
├──────────────────────────────────────────────────────────────┤
│  STAGE 2: PROJECT INTAKE                                     │
│  project init → target pin → evidence (images only)          │
│  Gate: every source declared and hash-bound                  │
├──────────────────────────────────────────────────────────────┤
│  STAGE 3: ANALYZE                                            │
│  project analyze → Design Document per source                │
│  Gate: sections, roles, and repeat groups look right         │
├──────────────────────────────────────────────────────────────┤
│  STAGE 4: PLAN + APPROVAL                                    │
│  project plan → review matches → approval request/resolve    │
│  Gate: operator approved the exact plan fingerprint          │
├──────────────────────────────────────────────────────────────┤
│  STAGE 5: THEME (manual)                                     │
│  Tokens → fonts → controls → CSS → palette export            │
│  Gate: 100+ controls modified                                │
├──────────────────────────────────────────────────────────────┤
│  STAGE 6: BUILD                                              │
│  project build → assets, library, pages, globals, verify     │
│  Gate: verification valid, zero release blockers             │
├──────────────────────────────────────────────────────────────┤
│  STAGE 7: PUBLISH (manual)                                   │
│  Resolve blockers → publish content and globals → SEO        │
│  Gate: structural audit >= 80                                │
└──────────────────────────────────────────────────────────────┘
```

**Theme before build.** Blocks inherit theme styling through palette classes. If
you build before the theme is applied, sections bake in inline colors that resist
re-theming.

## Stage 1: Foundation

```bash
vanjaro auth status --json
vanjaro api-key status --json
vanjaro site health --json
```

If any fail:
```bash
vanjaro auth login --url http://site.local
vanjaro api-key generate
```

**Portal isolation.** Every project gets its own portal. Confirm the target
portal ID with the user before anything else — building into a shared portal
contaminates other clients' blocks and theme.

```bash
vanjaro branding update --site-name "Site Name" --footer-text "Copyright 2026 Site Name"
```

## Stage 2: Project Intake

Create the workspace. Sources are typed `KIND=REFERENCE` pairs and repeatable, so
one project can combine a Figma desktop frame with mobile screenshots.

```bash
vanjaro project init ./projects/client-name \
  --name "Client Name" \
  --target-profile client-name \
  --expected-portal-id 2 \
  --expected-base-url http://site.local \
  --source figma=https://www.figma.com/design/FILE/Name?node-id=1-2 \
  --json
```

Source kinds: `figma`, `html`, `image`, `legacy`.

Pin the target before any portal mutation:
```bash
vanjaro project target pin ./projects/client-name
vanjaro project target check ./projects/client-name --json
```

**Image sources only** — each raster needs an explicit viewport, breakpoint, and
hash-bound evidence sidecar. Generate sidecars before analysis:

```bash
vanjaro project evidence generate ./projects/client-name --json
```

This requires `OPENAI_API_KEY`. Without it the command returns structured
recovery guidance and writes nothing. `--dry-run` needs no credential.

## Stage 3: Analyze

```bash
vanjaro project analyze ./projects/client-name --json
```

Writes a Design Document per source into the workspace `analysis/` directory.
Use `--refresh` to reacquire remote evidence, `--dry-run` to validate and hash
local inputs without network calls.

Review before planning: section count, semantic roles, repeat groups, and any
warnings about unresolved assets or ambiguous responsive pairing.

Correct ambiguous evidence through audited overlays, never by editing the
Design Document:
```bash
vanjaro project overlay list ./projects/client-name
vanjaro project overlay set-value ./projects/client-name --help
vanjaro project overlay add-repeat-field ./projects/client-name --help
```

## Stage 4: Plan and Approval

```bash
vanjaro project plan ./projects/client-name --json
```

Useful options:
- `--minimum-confidence FLOAT` — default 0.65
- `--allow-simplification` — permit approximated traits
- `--css-rule-budget INT` — default 12 new scoped rules per section
- `--template-override SECTION_ID=TEMPLATE` with `--override-reason`

Present the plan to the user: chosen template per section, alternatives,
confidence, simplifications, and blockers. **Wait for confirmation.**

Approval is bound to the exact plan fingerprint — changing the plan invalidates it:
```bash
vanjaro project approval request ./projects/client-name --help
vanjaro project approval resolve ./projects/client-name --help
```

## Stage 5: Theme (manual)

`project build --theme-mode plan` only writes review artifacts. It never applies
anything. Apply the theme yourself before building.

Extract tokens. For Figma, pull exact values rather than eyeballing:
```bash
vanjaro figma tokens <url> --node <frame> -o artifacts/design-tokens.json \
  --palette artifacts/theme-palette.json
vanjaro figma export <url> --node <frame> -o artifacts/figma-assets
```

Register non-default fonts **before** applying controls:
```bash
vanjaro theme register-font --name "Font Name" --family "Font Name, fallback" \
  --import-url "https://fonts.googleapis.com/css2?family=..." --json
```

Apply controls in order, following `../site-migrator/references/theme-apply.md`
for variable discovery and the set-bulk file format:

1. Colors (5-7) → 2. Site globals (2-3) → 3. Headings H1-H10 (20) →
4. Paragraphs P1-P10 (10-20) → 5. Buttons B1-B10 (50-70) → 6. Menu (5-15) →
7. Links (3-6)

Anything controls can't express:
```bash
vanjaro theme css update --file artifacts/custom.css
```

Export the palette so blocks compose with theme classes instead of inline hex:
```bash
vanjaro theme palette-export --output artifacts/theme-palette.json
```

Gate — expect 100-130 modified controls:
```bash
vanjaro theme get --modified --json | jq '.total'
```

## Stage 6: Build

```bash
vanjaro project build ./projects/client-name --dry-run --json
vanjaro project build ./projects/client-name --json
```

Stages run in order: `theme`, `assets`, `library`, `pages`, `globals`, `verify`.
Stop early with `--through library`. Pages are created as hidden project-prefixed
drafts (`--page-mode isolated`), so current navigation is untouched.

Always dry-run first — it previews the next executable stage with no writes.

Resume after interruption; completed stages are skipped only when inputs,
artifacts, and hashes all still match:
```bash
vanjaro project status ./projects/client-name --json
```

The build stops at the first failing stage. Fix the cause and rerun — do not
skip ahead.

## Stage 7: Publish (manual)

Verification writes `verify/draft-verification.json` with text coverage,
responsive image counts, warnings, and blockers. `valid: false` means publication
is correctly refused.

The usual blocker is source actions with no URL mapping. These are content
decisions for the user. **Never invent a destination to clear the gate.**

Once blockers are resolved, publish deliberately:
```bash
vanjaro content diff PAGE_ID
vanjaro content publish PAGE_ID
vanjaro global-blocks publish GLOBAL_GUID
vanjaro pages seo-update PAGE_ID --title "Page | Site" --description "..."
```

Final structural audit:
```bash
vanjaro migrate audit-structure --all --json artifacts/audit-report.json
```

Scores each published page on inline styles, theme classes, responsive images,
and composition. A composite of 80+ is the bar for a fresh build. Lower usually
means the theme was applied after blocks were composed, or the palette export
was skipped.

## Expert Path

The low-level commands remain available when a project workspace is overkill —
a single page, or repairing an existing site. See
`${CLAUDE_SKILL_DIR}/references/cli-quick-reference.md` for `blocks compose`,
`blocks build-library`, `blocks scaffold`, `pages create`, and `content update`.

Offline, without a portal, map any Design Document straight to a plan:
```bash
vanjaro blocks plan --design design-document.json --output plan.json \
  --library-plan library-plan.json
vanjaro blocks plan-validate plan.json --json
```

## Final Report

```
Site Build Complete
═══════════════════════════════════════════════════
Site:    http://site.local (portal 2)
Theme:   112 controls + 45 lines custom CSS
Blocks:  8 custom + 2 global
Pages:   5 built, 5 published
Audit:   composite 89.5

Artifacts:
  - projects/client-name/analysis/design-document.json
  - projects/client-name/plans/composition-plan.json
  - projects/client-name/verify/draft-verification.json
```

</instructions>

<examples>
<example>
<input>Here's the Figma file for a wellness coaching site. Build the whole site.</input>
<output>
I'll build this through a project workspace so every stage is resumable and gated.

**Stage 1: Foundation**
- Site health: OK (DNN 9.10.2, Vanjaro 1.6)
- Session: active

Before I create anything — which portal should this build into? Building into a
shared portal would mix these blocks with other clients'.

[after confirmation, continues: project init → analyze → plan → approval →
theme → build → verify, stopping at each gate]
</output>
</example>

<example>
<input>Theme's already done. Just build the library and pages from the mockups.</input>
<output>
Checking the theme is really in place, then starting at intake.

```bash
vanjaro theme get --modified --json | jq '.total'
# 108 — theme is applied
```

Screenshots need explicit viewport, breakpoint, and evidence sidecars per image,
so intake declares each raster before analysis.

[continues from Stage 2 with --source image=...]
</output>
</example>
</examples>

<constraints>
- Confirm the dedicated target portal before any mutation. Never build into a shared portal.
- Apply the theme before building. `--theme-mode plan` writes review artifacts only; it never applies.
- Dry-run `project build` before every real run.
- Never fabricate visitor content, action URLs, or logos to clear a gate. Report blockers as blockers.
- Correct ambiguous evidence through `project overlay`, never by editing a Design Document.
- Approvals are fingerprint-bound. If the plan changes, request approval again.
- Export the theme palette before building, or sections bake in inline colors.
- Never publish without explicit user confirmation.
- Run `audit-structure --all` after publishing; below 80 signals a structural problem.
- Write artifacts inside the project workspace, not scattered across the repo.
- If a stage fails, stop and report. Don't skip ahead.
- When resuming, run `project status` first and trust it over assumptions.
</constraints>
