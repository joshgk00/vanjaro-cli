# Site Builder Workflow Checklist

Use this as a progress tracker. Each phase has a verification step before moving to the next.

## Phase 1: Prerequisites
- [ ] `vanjaro auth status --json` — session active
- [ ] `vanjaro api-key status --json` — API key set
- [ ] `vanjaro site health --json` — site reachable, DNN + Vanjaro versions confirmed
- [ ] Design input gathered (screenshots, mockups, URL, or description)

## Phase 2: Branding
- [ ] `vanjaro branding update --site-name "..." --footer-text "..."` — site name and footer set
- [ ] Verify: site name shows in browser tab

## Phase 3: Theme — Extract Tokens
- [ ] Analyze design for colors, fonts, spacing, border radius
- [ ] Produce `artifacts/design-tokens.json`
- [ ] Note items in `custom_css_needed` for Phase 5

**Skill reference**: `skills/theme-extract-tokens.md`

## Phase 4: Theme — Apply Controls
- [ ] Register custom fonts: `vanjaro theme register-font`
- [ ] Apply colors: `vanjaro theme set-bulk colors.json`
- [ ] Apply site globals (font, border radius): `vanjaro theme set-bulk site-globals.json`
- [ ] Apply heading typography (H1-H10): `vanjaro theme set-bulk headings.json`
- [ ] Apply paragraph typography (P1-P10): `vanjaro theme set-bulk paragraphs.json`
- [ ] Apply button styling (B1-B10): `vanjaro theme set-bulk buttons.json`
- [ ] Apply menu styling: `vanjaro theme set-bulk menu.json`
- [ ] Apply link styling: `vanjaro theme set-bulk links.json`
- [ ] Verify: `vanjaro theme get --modified --json | jq '.total'` — expect 100-130 controls

**Skill reference**: `skills/theme-apply.md`

## Phase 5: Theme — Custom CSS
- [ ] Write CSS for items identified in `custom_css_needed`
- [ ] Apply: `vanjaro theme css update --file custom.css`
- [ ] Verify: site renders correctly with custom styles

## Phase 6: Block Library — Analyze Design
- [ ] Analyze design for recurring UI patterns across all pages
- [ ] Deduplicate patterns (same structure = one block)
- [ ] Map patterns to templates from `artifacts/block-templates/`
- [ ] Identify global blocks (header, footer only)
- [ ] Flag patterns needing new templates

**Skill reference**: `.claude/skills/block-composer/SKILL.md`

## Phase 7: Block Library — Create New Templates (if needed)
- [ ] Create any missing templates flagged in Phase 6
- [ ] Validate each: `python .claude/skills/block-template-author/scripts/validate_template.py <file>`

**Skill reference**: `.claude/skills/block-template-author/SKILL.md`

## Phase 8: Block Library — Generate Plan & Register
- [ ] Generate library plan: `artifacts/library-plan.json`
- [ ] Dry run: `vanjaro blocks build-library --plan artifacts/library-plan.json --dry-run`
- [ ] User confirms the plan
- [ ] Register: `vanjaro blocks build-library --plan artifacts/library-plan.json`
- [ ] Verify: all blocks show "OK" status

## Phase 9: Page Structure
- [ ] Plan page hierarchy (parent/child relationships)
- [ ] Create pages: `vanjaro pages create --title "..." --name "..." [--parent N]`
- [ ] Audit shells: `vanjaro pages shell PAGE_ID --fix` for any non-Vanjaro pages
- [ ] Record page IDs for content phase

## Phase 10: Page Content
For each page:
- [ ] Identify which custom blocks from the library apply to this page
- [ ] Compose page content using `blocks compose` or `blocks scaffold`
- [ ] Push as draft: `vanjaro content update PAGE_ID --file page.json`
- [ ] Verify structure: `vanjaro blocks tree PAGE_ID`
- [ ] Publish: `vanjaro content publish PAGE_ID`

## Phase 11: Global Blocks
- [ ] Create or update header global block
- [ ] Create or update footer global block
- [ ] Publish: `vanjaro global-blocks publish GUID`
- [ ] Verify: header/footer appear on all pages

## Phase 12: Final Verification
- [ ] Browse every page — layout matches design
- [ ] Check responsive breakpoints (mobile, tablet, desktop)
- [ ] Verify navigation links work
- [ ] Verify SEO settings: `vanjaro pages seo PAGE_ID`
- [ ] Check for visual regressions after theme + content changes
