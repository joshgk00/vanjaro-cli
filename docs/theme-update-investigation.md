# Theme Update Investigation — Handoff Document

**Date:** 2026-04-02 through 2026-04-03
**Site:** vanjarocli.local (IIS → C:\Websites\vanjarocli\Website)
**Platform:** DNN 9.10.2 + Vanjaro 1.6, "Basic" theme
**Goal:** Change theme design settings (colors, fonts) via CLI without breaking site CSS

---

## The Problem

Changing any theme design control (even a single color) via the VanjaroAI API endpoint produces CSS that breaks the site layout. The same breakage occurs when using the browser-based ThemeBuilder UI. The factory-compiled Theme.css works; any recompiled Theme.css does not visually render correctly, even though the CSS content is structurally valid.

**Update from CLI investigation (2026-04-03):** the anonymous home page is not currently rendering with the Vanjaro shell at all. It is emitting an `Xcillion` bundle, while the login page emits the expected Vanjaro `Theme.css` bundle. That means at least part of the apparent "theme breakage" is really a shell mismatch between published anonymous pages and Vanjaro-managed pages.

---

## Architecture: How Theme CSS Works

### Theme Settings Flow
1. Theme controls (~1,143 values: colors, fonts, spacing, etc.) are stored in `~/Portals/0/vThemes/Basic/editor/{categoryGuid}/theme.json`
2. When settings are saved, `ThemeManager.ProcessScss()` runs:
   - Iterates all categories and controls
   - For each control: uses saved value from theme.json if present, otherwise uses `ctl.DefaultValue` from the control definition
   - Builds SCSS: font @imports → SCSS variable declarations (`$var: value !default;`) → Before.scss → Bootstrap 5.1.0 → custom CSS → After.scss
   - Writes `Theme.scss` to disk
   - Runs `dart.exe sass.snapshot Theme.scss Theme.css --load-path=Bootstrap/`
   - Increments DNN's CRM (Client Resource Management) version
3. DNN's ClientDependency framework bundles Theme.css into a composite `.cdC` file served via `DependencyHandler.axd`

### Two Different Save Endpoints

**ThemeBuilder (browser UI):**
- Endpoint: `POST /API/ThemeBuilder/settings/save?guid={categoryGuid}`
- Sends ALL ~1,143 control values in every request (complete state)
- Calls `ThemeManager.Save(guid, allValues)` then `ProcessScss(portalId, true)`
- Requires: TabId header, ModuleId header, editor cookies, anti-forgery token

**VanjaroAI (our CLI):**
- Endpoint: `POST /API/VanjaroAI/AIDesign/UpdateSettings`
- Originally sent only changed controls; merged with existing theme.json
- Calls `ThemeManager.Save(catGuid, values)` then `ProcessScss(portalId, false)`
- Requires: admin cookies + API key (no TabId/ModuleId needed)

### CSS Delivery to Browser

**Registration:** `Base.ascx.cs` (Vanjaro skin) conditionally registers Theme.css:
```csharp
if (PageManager.InjectThemeCSS(PortalSettings))
    WebForms.LinkCSS(Page, "ThemeCSS", 
        "~/Portals/" + PortalSettings.PortalId + "/vThemes/" + ThemeName + "/Theme.css", 
        true, "DnnPageHeaderProvider", 0);
```

**Caching:** DNN's ClientDependency framework caches bundled CSS in:
- `App_Data/ClientDependency/*.cdC` (gzipped CSS bundles, versioned by CRM version)
- `App_Data/ClientDependency/*-map.xml` (bundle composition map)
- DependencyHandler.axd serves these bundles via URL: `/DependencyHandler.axd/{hash}/{crmVersion}/css`

---

## What We Found

### 1. API Fix (Applied — Correct but Insufficient)

**File:** `C:\Code\vanjaro-ai\source\DesktopModules\Vanjaro\AI\Controllers\AIDesignController.cs`

Two bugs in `UpdateSettings`:

**Bug A — Partial save:** On a fresh theme, theme.json is empty (`[]`). The old code read theme.json, merged in changed values, and saved only those. ProcessScss then fell back to raw `ctl.DefaultValue` for the ~1,141 unchanged controls. The ThemeBuilder sends all 1,143 values every time.

**Bug B — Wrong ProcessScss parameter:** ThemeBuilder calls `ProcessScss(portalId, true)`. Our code called `ProcessScss(portalId, false)`. The boolean is `CheckVisibilityPermission` — controls which categories/controls/fonts are loaded during compilation.

**Fix applied:** Build complete control list from `collected.Controls` instead of merging with partial theme.json. Changed ProcessScss boolean to `true`. DLL rebuilt and deployed.

**Result:** Fix is correct but didn't solve the visual problem because the issue is deeper.

### 2. ProcessScss Produces Valid but Visually Broken CSS

We confirmed via diff that the recompiled Theme.css is **structurally identical** to the factory version — same Bootstrap classes, same layout rules. Differences are limited to:
- Font @import URLs (different registered fonts produce different import lines)
- Color values (expected cascading changes from the primary color change)
- File size difference: ~600 bytes (accounted for by font URL differences)

**Both the ThemeBuilder and our API produce the same broken result.** The user confirmed this by changing a color through the browser UI — same breakage.

### 3. CSS File Is Correct but Not Rendered

- Direct browser access to `http://vanjarocli.local/Portals/0/vThemes/Basic/Theme.css` shows the correct CSS with `#ff0000` primary color
- The ClientDependency cache bundles (`.cdC` files) contain `#ff0000` when decompressed
- Yet the browser renders the page without the updated theme styles

### 4. Logged-In vs Logged-Out Discrepancy

**Logged out (anonymous):** Page has NO theme styling at all — raw unstyled HTML. The DependencyHandler.axd returns only a small 36KB bundle (DNN framework CSS only, no Theme.css/Bootstrap).

**Logged in (admin):** Page has proper layout with Bootstrap grid, buttons, columns. Loads many individual CSS files (bootstrap.min.css, grapes.min.css, editor CSS) plus a larger 58KB DependencyHandler bundle.

This suggests `PageManager.InjectThemeCSS()` may be returning `false` for anonymous users, or Theme.css registration is conditional on authentication state.

### 5. Aggressive Caching

Even after:
- Replacing Theme.css on disk
- Touching web.config (app pool recycle)
- Incrementing CRM version in database (87 → 88)
- Deleting all ClientDependency cache files

...the browser still showed old styles. The cache regenerated immediately with correct content (confirmed by decompressing .cdC files), but the visual output didn't change.

### 6. Anonymous Home Page Uses Xcillion, Not Vanjaro

Additional verification on 2026-04-03 changed the working theory significantly:

- `GET /` (anonymous home page) returns `<link href="/DependencyHandler.axd/d6dfca36dba9156e2ae9633191b9260f/89/css" ...>`
- The ClientDependency map for `d6dfca36...` resolves to legacy Xcillion assets:
  - `/Resources/Shared/stylesheets/dnndefault/7.0.0/default.css`
  - `/Portals/_default/Skins/Xcillion/bootstrap/css/bootstrap.min.css`
  - `/Portals/_default/Skins/Xcillion/skin.css`
- `GET /Login` returns `<link href="/DependencyHandler.axd/98a091450d4bee8b7af9b0f85f5fd39b/89/css" ...>`
- The ClientDependency map for `98a09145...` resolves to Vanjaro assets:
  - `/Portals/0/vThemes/Basic/Theme.css`
  - `/Portals/_default/Skins/Vanjaro/Resources/css/skin.css`

This means the anonymous home page is not missing Theme.css because `InjectThemeCSS()` returned false inside the Vanjaro skin. It is on a different skin path altogether.

### 7. `InjectThemeCSS()` Is Probably Not the Anonymous Root Cause

Source review of `PageManager.InjectThemeCSS()` shows it only returns `false` when all of the following are true:
- The current user can inject the editor (`InjectEditor(PortalSettings)` is true)
- The `vj_InitUX=true` cookie is present
- `Editor.Options.InjectThemeCSS` is false
- The request is not already in certain control/querystring modes

An anonymous user does not satisfy `InjectEditor(PortalSettings)`, so this method should return `true` for anonymous requests that are already using the Vanjaro skin. That makes the home-page Xcillion shell mismatch a stronger explanation than conditional Theme.css injection.

### 8. `ResetSettings()` Still Uses the Older Compilation Flag

`AIDesignController.ResetSettings()` still calls:

```csharp
Vanjaro.Core.Managers.ThemeManager.ProcessScss(portalId, false);
```

So even after fixing `UpdateSettings()` to use `true`, the reset path still recompiles with the older visibility setting. That makes `theme reset` a poor rollback mechanism until the reset endpoint is aligned with the save path.

### 9. Edit Mode Failure Is a Server-Side Null Reference, Not Just Broken CSS

After changing a single theme control on the Vanjaro-shell page `/VGRT-Home`, edit mode started failing again. Authenticated requests to:

- `GET /VGRT-Home?mid=0&icp=true`

returned HTML with an error route such as:

- `~/Default.aspx?tabid=35&error=Object+reference+not+set+to+an+instance+of+an+object.`

The DNN log at `Portals/_default/Logs/2026.04.03.log.resources` shows the corresponding stack trace:

- `System.NullReferenceException: Object reference not set to an instance of an object.`
- `at Vanjaro.Common.Foundation.AngularModuleBase.OnInit(EventArgs e)`
- `at Vanjaro.UXManager.Library.Extension.OnInit(EventArgs e)`
- `at Vanjaro.Skin.Base.InjectExtensionControl()`

This changes the working theory for edit mode: the failure is not only that compiled theme CSS looks wrong. The editor bootstrap path itself is crashing during initialization.

Source review points to a likely weak spot:

- `Vanjaro.Skin.Base.InjectExtensionControl()` loads `~/DesktopModules/Vanjaro/UXManager/Library/Extension.ascx` whenever `mid=0`
- `Vanjaro.UXManager.Library.Extension.OnInit()` only populates `ext` when a valid `guid` query-string is present
- `AngularModuleBase.OnInit()` assumes `App` is non-null and uses `App.Name` later in initialization

Further source review of the editor UI confirms that this is not just an invalid manual repro URL:

- `UXManager/Library/Base.ascx.cs` registers `CurrentTabUrl` for the editor and opens some page-level tools with `&mid=0&icp=true&guid=...`
- `GrapesJsManagers/editor.js` builds `CurrentExtTabUrl` as `CurrentTabUrl + '?mid=0&icp=true'` (or `&mid=0&icp=true` when a query string already exists)
- The editor only appends `&guid=...` later when opening a specific extension/tool such as block settings, image manager, revisions, or permissions

That means `mid=0&icp=true` without a `guid` is a normal page-level editor entry pattern. If `Extension.ascx` is always injected for `mid=0`, then `Extension.OnInit()` and/or `AngularModuleBase.OnInit()` need to tolerate `ext == null`. This is now the strongest code-level root-cause candidate for the edit-mode crash.

### 10. Fresh Baseline Site Identified on 2026-04-06

A separate local site exists at:

- `http://vanjarobaseline.local`
- IIS path: `C:\Websites\vanjarobaseline\Website`
- Database: `vanjarobaseline`

This baseline site appears freshly created on 2026-04-06:

- `Portals.CreatedOnDate = 2026-04-06 06:31:28`
- `Portals.LastModifiedOnDate = 2026-04-06 06:49:20`

Important shell findings:

- `Home` (`TabID 21`) is still Xcillion
- `Signin` (`TabID 33`) is Vanjaro shell
- `Test Page` (`TabID 34`) is Vanjaro shell

So `Test Page` is the correct clean-room Vanjaro test page on the baseline site.

User testing on 2026-04-06 reported that a browser ThemeBuilder color update on the baseline site **did not break the editor**. That makes `vanjarobaseline.local/Test-Page` the current best reproduction baseline.

Additional implementation step completed:

- `Vanjaro.AI.dll` was copied into `C:\Websites\vanjarobaseline\Website\bin\`
- `http://vanjarobaseline.local/API/VanjaroAI/...` now returns `401` instead of `404`, confirming the AI routes are active on the baseline site

This means the remaining blocker for a full AI-vs-browser A/B test on the baseline site is authentication/profile setup, not package availability.

### 11. Fresh Baseline vs Current Site Drift Report

A repeatable comparison script was added:

- `C:\Code\vanjaro-cli\tools\theme-compare.ps1`

Current generated report:

- `C:\Code\vanjaro-cli\docs\theme-site-comparison-2026-04-06.md`

High-signal findings from that report:

- Baseline `Theme.css` hash differs from both:
  - repo factory `Theme.css`
  - current contaminated `vanjarocli` site
- Baseline `Theme.scss` hash also differs from both factory and current
- Baseline `theme.json` main category contains 1,143 values, but its values differ from current
- Example: baseline primary color is `rgb(38, 35, 35)` while the current site retained `#ff0000`
- Baseline published Vanjaro test page uses bundle key `4efed7f5a054f8c8a43265e606bd965f` at CRM version `44`
- Current `VGRT-Home` uses bundle key `a11762ae99635938b97ea22874659425` at CRM version `93`

This confirms we now have:

1. a separate baseline environment,
2. a repeatable comparison tool,
3. evidence that the current site has materially drifted from the fresh baseline.

---

## What We Tried

| Action | Result |
|--------|--------|
| Fix AIDesignController to save complete control list | ✅ Code fix correct, CSS still visually broken |
| Change ProcessScss boolean from `false` to `true` | ✅ Code fix correct, CSS still visually broken |
| Register missing Google Fonts (Albert Sans, Aboreto, etc.) | ❌ No effect on visual output |
| Reset theme settings via API | ❌ Also produces broken CSS (same ProcessScss path) |
| Restore factory Theme.css from dev site | ✅ Site works when factory CSS is on disk |
| Swap recompiled CSS without running ProcessScss | ❌ Published view showed no change (caching) |
| Increment CRM version in HostSettings table | ❌ No visible effect |
| Delete all ClientDependency cache files | ❌ Cache regenerated but no visible change |
| Touch web.config to recycle app pool | ❌ No visible effect |
| Compare factory vs recompiled CSS (full diff) | ✅ Only expected differences (fonts, colors) |
| Verify .cdC bundles contain correct CSS | ✅ Decompressed bundles have #ff0000 |
| Inspect live anonymous HTML + ClientDependency map | ✅ Home page resolves to Xcillion bundle, not Vanjaro |
| Inspect `InjectThemeCSS()` source | ✅ Does not explain anonymous omission by itself |
| Inspect `ResetSettings()` source | ✅ Still uses `ProcessScss(portalId, false)` |
| Fix Color Picker validation for shorthand/alpha hex | ✅ Fixed, no more 400 errors for `#fff` etc. |
| Fix validation to allow `$variable` references | ✅ Fixed, no more 400 errors for `$secondarycolor` etc. |
| Skip re-validation of unchanged control defaults | ✅ Fixed, no more 400 for `none` dropdown values |
| Retry theme set after all validation fixes (2026-04-05) | ❌ API returns 200 but CSS still visually broken |
| Full cache clear + CRM bump to 92 + factory CSS restore | ✅ Logged-in view recovers with factory CSS |
| Identify fresh baseline site (`vanjarobaseline.local`) | ✅ Separate DB/site found; `Test Page` is Vanjaro-shell |
| Browser ThemeBuilder test on baseline site | ✅ User reports editor did not break |
| Deploy `Vanjaro.AI.dll` to baseline site | ✅ AI routes now return `401` instead of `404` |
| Generate baseline-vs-current comparison report | ✅ Drift captured in `tools/theme-compare.ps1` output |
| Fix CLI profile resolution bug caused by repo `.env` | ✅ Active profile now wins over `.env`; baseline auth and API-key flow work |
| Run AI theme save on fresh baseline site | ✅ Save, compile, on-disk CSS update, and bundle version rollover all confirmed on `Test Page` |
| Run browser ThemeBuilder save on fresh baseline site | ✅ Save, compile, on-disk CSS update, and bundle version rollover also confirmed on `Test Page` |
| Reproduce authenticated edit-mode request after theme change | ✅ Returns `Object reference not set...` on `tabid=35` |
| Inspect DNN logs for edit-mode failure | ✅ Null reference in `AngularModuleBase.OnInit` via `Extension.OnInit` |
| Inspect editor bootstrap source path | ✅ `mid=0` extension injection appears brittle when `guid` is missing/unresolved |
| Trace real editor URL construction | ✅ Page-level editor starts from `mid=0&icp=true`; `guid` is added only for specific tools |

---

## Current State

- **Theme.css on disk:** Restored to factory version (292,552 bytes) after latest failed test
- **ClientDependency cache:** Cleared and regenerated with CRM version 92
- **Browser rendering:** Logged-in published view breaks after any ProcessScss call; factory CSS restores it
- **Fresh baseline site:** `http://vanjarobaseline.local/Test-Page` is currently the preferred clean-room Vanjaro test page
- **Fresh baseline AI save:** confirmed working end-to-end on `Test Page`; `theme.json`, `Theme.scss`, `Theme.css`, and the published bundle all changed after `vanjaro theme set`
- **Fresh baseline browser save:** also confirmed working end-to-end on `Test Page`; ThemeBuilder updated the same artifacts and rolled the published bundle to version `47`
- **Authenticated edit mode (`/VGRT-Home?mid=0&icp=true`):** Throws `NullReferenceException` during Vanjaro editor bootstrap
- **DLL deployed:** Updated Vanjaro.AI.dll with validation fixes (variable refs, shorthand hex, skip unchanged defaults)
- **Baseline AI routes:** Active after deploying `Vanjaro.AI.dll` to baseline `bin`
- **CRM version:** 92
- **theme.json:** Contains complete control values from last UpdateSettings call
- **Anonymous home page HTML:** Currently references Xcillion bundle key `d6dfca36dba9156e2ae9633191b9260f`
- **Login page HTML:** References Vanjaro bundle key `98a091450d4bee8b7af9b0f85f5fd39b`

### Validation Fixes Applied (2026-04-05)

Three validation issues were found and fixed by Josh in `AIDesignController.cs`:
1. **Color Picker:** Hex regex expanded from `^#[0-9a-fA-F]{6}$` to `^#[0-9a-fA-F]{3,8}$` to accept shorthand (`#fff`) and alpha (`#00000026`) values
2. **All control types:** Variable references (`$secondarycolor`, `$siteBorderRadius`) now pass through validation
3. **Unchanged defaults:** Only user-changed values are strictly validated; existing values from `collected.Controls` are passed through without re-validation

These fixes eliminated all 400 errors. The UpdateSettings call now succeeds (returns 200), but the resulting CSS still visually breaks the site.

---

## Fresh Baseline AI Result (2026-04-06)

The fresh baseline site can now be exercised through the distributable packages only:

- `vanjaro-cli`
- `Vanjaro.AI`

### Baseline Auth Bug Was in the CLI, Not the Site

Baseline login cookies were valid, but `vanjaro api-key generate` originally returned `Session expired`.

The actual cause was:

- repo `.env` contained `VANJARO_BASE_URL=http://vanjarocli.local`
- `load_config()` preferred `VANJARO_BASE_URL` over the active saved profile
- so the active `vanjarobaseline-local` profile loaded baseline cookies but sent requests to `vanjarocli.local`

That is now fixed in:

- `C:\Code\vanjaro-cli\vanjaro_cli\config.py`
- `C:\Code\vanjaro-cli\tests\test_config.py`

After that fix:

- `vanjaro api-key status` worked on `vanjarobaseline.local`
- `vanjaro api-key generate` succeeded

### AI Save Test on Fresh Baseline

Target page:

- `http://vanjarobaseline.local/Test-Page`
- `TabID 34`
- shell confirmed as Vanjaro via `vanjaro pages shell 34`

Test control:

- `Primary`
- guid `fe5745d2-d4db-48bb-8f0c-3a7c37a3d0a3`

Observed results after setting `#00aa55`:

- CLI command succeeded
- baseline `theme.json` stored `"Value": "#00aa55"` for the target guid
- baseline `Theme.scss` contained `$primarycolor:#00aa55 !default;`
- baseline `Theme.css` contained many resolved `#00aa55` declarations
- published page HTML advanced to a new bundle URL:
  - `/DependencyHandler.axd/e6144b652673637620070207751784e6/45/css`

After reverting the color back to `#262323`, the page advanced again to:

- `/DependencyHandler.axd/3b1d509725c0cc919623b55928033563/46/css`

### Meaning

This is the strongest evidence so far that the distributable AI/CLI theme-save path works correctly on a fresh site:

- auth works
- API key flow works
- theme save works
- SCSS compilation works
- CSS output updates on disk
- ClientDependency bundle version rolls forward

So the current evidence no longer supports the idea that the AI endpoint inherently breaks theme updates everywhere. The remaining A/B question is narrower:

- does the browser ThemeBuilder path produce the same on-disk artifacts and bundle rollover on the fresh baseline for the same change?

### Browser vs AI A/B Result

That browser-vs-AI question is now partially answered on the fresh baseline.

Browser ThemeBuilder save of the same `Primary` color change (`#00aa55`) produced:

- updated `theme.json`
- updated `Theme.scss`
- updated `Theme.css`
- published bundle:
  - `/DependencyHandler.axd/d3a4777b9b9cfcafa66e0bce02964e22/47/css`

The interesting difference is serialization format:

- **AI save** stored:
  - `theme.json`: `"#00aa55"`
  - `Theme.scss`: `$primarycolor:#00aa55 !default;`
- **Browser save** stored:
  - `theme.json`: `"rgb(0, 170, 85)"`
  - `Theme.scss`: `$primarycolor:rgb(0, 170, 85) !default;`

But both paths compiled to a working `Theme.css` containing resolved `#00aa55` declarations and both rolled the ClientDependency bundle forward.

### Implication

On the fresh baseline:

- AI save works
- browser save works
- both produce usable CSS
- the main observed difference is value normalization (`hex` vs `rgb`) before compilation

That points away from the AI endpoint as the root cause of the current-site breakage and toward one of:

- state drift on `vanjarocli.local`
- a site-specific shell/cache/runtime issue
- a separate editor bootstrap defect unrelated to the fresh-site theme save path

---

## Key Files

| File | Path |
|------|------|
| AIDesignController (fixed) | `C:\Code\vanjaro-ai\source\DesktopModules\Vanjaro\AI\Controllers\AIDesignController.cs` |
| ThemeBuilder save endpoint | `C:\Code\vanjaro-ai\source\DesktopModules\Vanjaro\UXManager\Extensions\Menu\ThemeBuilder\Controllers\SettingsController.cs` |
| ProcessScss method | `C:\Code\vanjaro-ai\source\DesktopModules\Vanjaro\Core\Library\Managers\ThemeManager.cs:198-351` |
| Theme CSS registration | `C:\Code\vanjaro-ai\source\Portals\_default\Skins\Vanjaro\Base.ascx.cs:151-152` |
| InjectThemeCSS logic | `C:\Code\vanjaro-ai\source\DesktopModules\Vanjaro\Core\Library\Managers\PageManager.cs:61-67` |
| Factory Theme.css (working) | `C:\Code\vanjaro-ai\website\Portals\0\vThemes\Basic\Theme.css` (292,552 bytes) |
| Site Theme.css (recompiled) | `C:\Websites\vanjarocli\Website\Portals\0\vThemes\Basic\Theme.css` (292,558 bytes) |
| ClientDependency cache | `C:\Websites\vanjarocli\Website\App_Data\ClientDependency\` |
| DNN database | `localhost\CB2016SQLSERVER`, database `vanjarocli`, Integrated Security |

---

## Open Questions

1. **Why does the browser not render the correct CSS when the cache files contain it?** Is there an additional caching layer (IIS output cache, kernel cache, HTTP.sys cache) that we haven't cleared?

2. **Why is the anonymous home page still on an Xcillion shell?** Is the home page `SkinSrc`/`ContainerSrc` explicitly set to Xcillion, or is it inheriting the portal default shell from the original DNN template?

3. **How many pages are affected by shell mismatch?** The home page clearly is. The login page is not. We need a page-by-page audit before trusting theme updates.

4. **Is the editor view breakage the same root cause or separate?** The Vanjaro editor currently has evidence of a real null-reference crash in its extension bootstrap path. That may be separate from the published-view shell/cache issues.

5. **Does the real edit-mode navigation include a `guid` query parameter that our direct repro omitted?** If normal editor navigation supplies `guid`, then the null reference may only affect a subset of editor entry URLs. If it does not, then `Extension.OnInit()` needs a null-safe fallback.

6. **Would a full IIS reset (not just app pool recycle) clear whatever cache is persisting?** We only touched web.config; we couldn't run `iisreset` due to permission issues.

7. **Can we authenticate cleanly against `vanjarobaseline.local` to run the AI half of the A/B comparison?** The package is deployed and routes are active, but we still need a baseline admin session/profile.

---

## Recommended Next Steps

1. **Use `vanjarobaseline.local/Test-Page` as the clean-room Vanjaro baseline** — it is fresh, separate from `vanjarocli`, and proven to accept both browser and AI-driven theme saves cleanly
2. **Treat old breakage on `vanjarocli.local` as site drift, not as proof the distributable workflow is unsafe** — that site had to be rebuilt from baseline before testing could be trusted again
3. **Keep the reset script as part of the workflow** — `C:\Code\vanjaro-cli\tools\reset-vanjarocli-from-baseline.ps1` is now the recovery path when a local test site drifts beyond trust
4. **Normalize non-Vanjaro pages when they are part of the test path** — especially home/root pages, which are still Xcillion on both sites
5. **Keep editor null-reference work separate from published CSS investigation** — the current evidence still points to a separate core/editor bootstrap issue

---

## Final Conclusion

The distributable theme-update approach is viable.

After rebuilding `vanjarocli.local` from the fresh `vanjarobaseline.local` site and retesting:

- browser ThemeBuilder saves worked
- AI/CLI theme saves worked
- repeated primary color changes worked
- published pages stayed intact
- the theme bundle updated correctly

This means the earlier failures were not reproduced on a clean site and are best explained by drift/corruption in the previous `vanjarocli.local` state rather than a fundamental flaw in:

- `vanjaro-cli`
- `Vanjaro.AI`

The validated distributable stack is:

- CLI builds browser-shaped full-category payloads
- AI endpoint saves that category and compiles with `ProcessScss(portalId, true)`
- site is tested on a known-good Vanjaro-shell page

## Safe Workflow

For repeatable use on future sites:

1. Authenticate to the target site:
   - `vanjaro auth login --url http://<site>`
   - `vanjaro api-key generate`
2. Verify the test page is actually using the Vanjaro shell:
   - `vanjaro pages shell PAGE_ID`
3. Start with a small theme change on a known-good Vanjaro page.
4. Apply AI-driven theme changes with:
   - `vanjaro theme set ...`
   - or `vanjaro theme set-bulk ...`
5. Verify both:
   - published page remains intact
   - edit mode still behaves as expected for that site
6. If the local site becomes untrustworthy, rebuild it from baseline with:
   - `C:\Code\vanjaro-cli\tools\reset-vanjarocli-from-baseline.ps1`
7. After any site reset/restore, re-authenticate and generate a fresh API key:
   - `vanjaro auth login --url http://<site>`
   - `vanjaro api-key generate`

## Recovery Notes

The reset script now does all of the following:

- backs up the current site files
- backs up the current target database
- snapshots the baseline database before cloning
- copies baseline website files to the target site
- rewrites `web.config` back to the target database name
- restores the baseline database into the target database name
- rewrites `PortalAlias` from baseline host to target host
- remaps the restored app-pool database user to the target IIS app pool login
- requires fresh CLI auth and a new API key after restore because site-side key state is reset

That final app-pool remap was necessary to fix the first restore attempt on `vanjarocli.local`.

---

## Proposed Distributable Fix: Browser-Shaped Theme Save via VanjaroAI

If the goal is to keep the solution distributable through only:

- `vanjaro-cli`
- `Vanjaro.AI`

then the safest approach is to make the AI theme-save contract match the ThemeBuilder browser contract as closely as possible, instead of introducing core-platform patches.

### Why This Is the Right Direction

Browser network capture shows that ThemeBuilder does **not** send only the changed controls. Even when changing 1-2 values, it posts the complete value set for the active category to:

- `POST /API/ThemeBuilder/settings/save?guid={categoryGuid}`

The payload includes:

- every control in that category
- each control's current value
- the `Css` field (often an empty string)

That means the browser save contract is effectively:

- save one category at a time
- send the entire category state every time
- compile immediately with `ProcessScss(portalId, true)`

### Recommended AI Endpoint Shape

Keep the existing read endpoint (`GetSettings`) for discovery, but add a new browser-shaped save endpoint in `Vanjaro.AI`:

**Route:**

- `POST /API/VanjaroAI/AIDesign/SaveCategory`

**Request body:**

```json
{
  "categoryGuid": "726c5619-e193-4605-acaf-828576ba095a",
  "themeEditorValues": [
    {
      "guid": "fe5745d2-d4db-48bb-8f0c-3a7c37a3d0a3",
      "value": "#00aa55",
      "css": ""
    },
    {
      "guid": "....",
      "value": "....",
      "css": ""
    }
  ]
}
```

**Server behavior:**

1. Validate `categoryGuid`
2. Validate each `themeEditorValues[i].guid`
3. Validate each value against the current control definition
4. Save exactly as ThemeBuilder does:
   - `ThemeManager.Save(categoryGuid, themeEditorValues)`
5. Compile exactly as ThemeBuilder does:
   - `ThemeManager.ProcessScss(portalId, true)`
6. Return fresh settings for that category or the full settings response

**Important note:** this endpoint should not try to reconstruct the category on the server if the CLI already sent the full category payload. The whole point is to preserve the browser contract, not invent a second save model.

### Matching CLI Behavior

The CLI should stop treating `theme set` as "send a partial patch to the server". Instead, it should behave like a client-side orchestrator:

1. Call `GET /API/VanjaroAI/AIDesign/GetSettings`
2. Find the target control by `guid` or `lessVariable`
3. Read that control's `categoryGuid`
4. Build the **full category payload** from all controls in that category
5. Replace only the requested value(s)
6. Send the whole category to `SaveCategory`

This keeps the CLI distributable while making the save contract deterministic and browser-like.

### CLI Algorithm for `theme set`

For `vanjaro theme set --guid ... --value ...`:

1. Fetch all controls
2. Resolve the target control
3. Read its `categoryGuid`
4. Collect all controls in that category
5. Build:

```json
{
  "categoryGuid": "<category-guid>",
  "themeEditorValues": [
    { "guid": "<guid-1>", "value": "<current-or-updated-value>", "css": "" },
    { "guid": "<guid-2>", "value": "<current-or-updated-value>", "css": "" }
  ]
}
```

6. POST to `SaveCategory`

### CLI Algorithm for `theme set-bulk`

For `vanjaro theme set-bulk theme-updates.json`:

1. Fetch all controls
2. Resolve every requested control
3. Group requested updates by `categoryGuid`
4. For each category:
   - build the full category payload from current values
   - apply the requested overrides
   - POST one `SaveCategory` request for that category

This matches the browser more closely than sending one large cross-category partial update request.

### CLI Surface Proposal

The current user-facing commands can remain the same:

- `vanjaro theme get`
- `vanjaro theme set`
- `vanjaro theme set-bulk`
- `vanjaro theme reset`

Only the internal implementation changes:

- `theme set` becomes `GET controls -> build full category -> SaveCategory`
- `theme set-bulk` becomes `GET controls -> group by category -> SaveCategory per category`

That preserves backward-compatible CLI ergonomics while making the network behavior match ThemeBuilder.

### AI Package Proposal Summary

Recommended changes in `Vanjaro.AI`:

1. Add `SaveCategory`
2. Keep `GetSettings`
3. Update `ResetSettings()` to compile with `ProcessScss(portalId, true)`
4. Optionally keep the old `UpdateSettings` route for compatibility, but have the CLI stop using it for normal theme saves

### Why Not Add `pageId` / `moduleId`

There is no evidence so far that `pageId` or `moduleId` are the missing inputs for the theme-save pipeline. ThemeBuilder's save endpoint keys off:

- category GUID
- full category values
- current editor session/auth context

The strongest observed difference is payload shape and save semantics, not page/module identifiers.
