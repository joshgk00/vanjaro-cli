# Vanjaro CLI — Complete Build Specification

**Version:** 1.0
**Date:** April 2, 2026
**Author:** Josh Slaughter + Claude
**Repo:** https://github.com/joshgk00/vanjaro-cli
**Target:** Python 3.10+ CLI tool for managing Vanjaro/DNN websites from Claude Code

---

## 1. Project Vision

Build a Python CLI tool (`vanjaro-cli`) that enables Claude Code (or any AI coding agent) to programmatically create, edit, and manage websites built on the Vanjaro page builder for the DNN Platform. The tool wraps Vanjaro's REST APIs and DNN's Persona Bar APIs into structured CLI commands with JSON output, paired with SKILL.md files that let Claude Code load only the relevant context for each task.

### 1.1 Use Cases

1. **Build a website from scratch** — Create pages, apply layouts, add building blocks (sections, grids, headings, text, images, buttons), populate content, and publish.
2. **Build from a design** — Given a design mockup or description, translate it into Vanjaro page structures using available blocks and templates from the Template Library.
3. **Edit an existing site** — Read current page content, modify text/images/links, rearrange blocks, update navigation, and publish changes.
4. **Manage content updates** — Routine content management: update copy, swap images, add new pages, adjust SEO settings.

### 1.2 Design Principles

- **CLI + Skills, not MCP** — Keep the context window lean by loading skills on demand rather than exposing dozens of MCP tools simultaneously.
- **JSON everywhere** — Every command supports `--json` output for structured parsing by AI agents.
- **Test everything** — Full pytest coverage with mocked API responses. Integration test markers for testing against a live instance.
- **CLI-Anything pattern** — Follow the 7-phase methodology: Analyze, Design, Implement, Plan Tests, Write Tests, Document, Publish.
- **Idempotent where possible** — Commands should be safe to retry.

---

## 2. Architecture

### 2.1 Project Structure

```
vanjaro-cli/
├── pyproject.toml                  # Build config
├── setup.py                        # pip install -e .
├── requirements.txt                # Runtime deps
├── requirements-dev.txt            # Test/dev deps
├── .env.example                    # Environment variable template
├── .gitignore
├── README.md
│
├── vanjaro_cli/
│   ├── __init__.py                 # __version__ = "0.1.0"
│   ├── cli.py                      # Main Click group, registers all command groups
│   ├── config.py                   # Config load/save (~/.vanjaro-cli/config.json) + env vars
│   ├── auth.py                     # DNN JWT authentication (login, reissue, logout)
│   ├── client.py                   # HTTP client (auth headers, CSRF, error handling, retries)
│   │
│   ├── commands/
│   │   ├── __init__.py             # Exports all Click groups
│   │   ├── auth_cmd.py             # vanjaro auth login/logout/status
│   │   ├── pages_cmd.py            # vanjaro pages list/get/create/copy/delete/settings
│   │   ├── content_cmd.py          # vanjaro content get/update/publish
│   │   ├── blocks_cmd.py           # vanjaro blocks list/categories/add/remove
│   │   ├── layouts_cmd.py          # vanjaro layouts list/apply/templates
│   │   ├── assets_cmd.py           # vanjaro assets list/upload/delete
│   │   ├── theme_cmd.py            # vanjaro theme get/set/css
│   │   ├── site_cmd.py             # vanjaro site info/settings/nav
│   │   └── modules_cmd.py          # vanjaro modules list/add/remove/settings
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── page.py                 # Page + PageSettings (Pydantic)
│   │   ├── content.py              # PageContent + ContentBlock (GrapesJS JSON)
│   │   ├── block.py                # Block + BlockCategory models
│   │   ├── asset.py                # Asset (file/image) models
│   │   └── module.py               # DNN Module models
│   │
│   └── utils/
│       ├── __init__.py
│       ├── output.py               # Shared output formatting (table, json, tree)
│       └── grapesjs.py             # GrapesJS component tree helpers
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures, mock server, auth tokens
│   ├── test_auth.py
│   ├── test_client.py
│   ├── test_pages.py
│   ├── test_content.py
│   ├── test_blocks.py
│   ├── test_layouts.py
│   ├── test_assets.py
│   ├── test_theme.py
│   ├── test_site.py
│   ├── test_modules.py
│   ├── test_grapesjs.py            # GrapesJS helper unit tests
│   └── integration/
│       ├── __init__.py
│       ├── conftest.py             # Live instance fixtures (reads VANJARO_BASE_URL env)
│       ├── test_live_auth.py       # Integration: real login
│       ├── test_live_pages.py      # Integration: real page CRUD
│       └── test_live_content.py    # Integration: real content read/write
│
└── skills/
    ├── SKILL.md                    # Master skill overview
    ├── auth.md                     # Authentication skill
    ├── pages.md                    # Page management skill
    ├── content.md                  # Content editing skill
    ├── blocks.md                   # Block management skill
    ├── layouts.md                  # Layout/template skill
    ├── assets.md                   # Asset management skill
    ├── theme.md                    # Theme customization skill
    ├── site.md                     # Site administration skill
    └── modules.md                  # Module management skill
```

### 2.2 Dependencies

**Runtime:**
```
click>=8.1
requests>=2.31
pydantic>=2.0
python-dotenv>=1.0
```

**Dev/Test:**
```
pytest>=7.0
responses>=0.23
click[testing]
pytest-cov
```

### 2.3 Configuration

Config stored at `~/.vanjaro-cli/config.json` using named profiles:
```json
{
  "active_profile": "vanjarocli-local",
  "profiles": {
    "vanjarocli-local": {
      "base_url": "http://vanjarocli.local",
      "cookies": { ".DOTNETNUKE": "...", "__RequestVerificationToken": "..." },
      "api_key": "<base64-key>",
      "portal_id": 0
    },
    "staging": {
      "base_url": "https://staging.example.com",
      "cookies": { "..." },
      "api_key": "<different-key>",
      "portal_id": 0
    }
  }
}
```

- Profiles auto-created from URL hostname on login (e.g., `http://vanjarocli.local` → `vanjarocli-local`)
- `--profile` global flag overrides the active profile for a single command
- Backward-compatible with old flat config format (auto-migrates to "default" profile)

Environment variables override (for CI/automation):
- `VANJARO_BASE_URL`
- `VANJARO_PORTAL_ID`

---

## 3. Target Platform APIs

### 3.1 Authentication

**Cookie-based auth via Vanjaro's AJAX login endpoint** (NOT DNN JWT):

Login flow:
1. `GET /Login` — Fetch the login page to get anti-forgery token + tabId from HTML
2. `POST /API/Login/Login/UserLogin` — Body: `{"Username":"...","Password":"...","Remember":false}` with headers `RequestVerificationToken`, `TabId`, `ModuleId`
3. Server sets `.DOTNETNUKE` auth cookie on success
4. All subsequent API calls include the auth cookie automatically

**Why not JWT?** DNN's `[ValidateAntiForgeryToken]` attribute (used on all Vanjaro API controllers) requires cookie-based sessions. JWT alone cannot satisfy this requirement.

### 3.2 Anti-Forgery Token (CSRF)

All API calls require the `RequestVerificationToken` header:
- Obtained by fetching the homepage (`GET /`) with auth cookies — scrape the hidden `__RequestVerificationToken` input from HTML
- Fetched once per client session, cached in memory
- Both the cookie and header token are needed (ASP.NET double-submit pattern)

### 3.3 API Key (VanjaroAI endpoints only)

Content endpoints use the VanjaroAI module which adds a second auth layer:
- `X-Api-Key` header with a pre-shared key
- Key generated via `POST /API/VanjaroAI/AIApiKey/Generate` (SuperUser only)
- Server stores SHA256 hash in DNN Host Settings; raw key returned once
- Optional until first key is generated — module works without one initially

### 3.3 API Endpoints (Confirmed Working)

**Vanjaro native** (service root: `/API/Vanjaro/`):

| Controller | Endpoint | Status |
|-----------|----------|--------|
| **Page** | `GetPages` | Working — returns `{Text, Value, Url}` format |
| **Page** | `Get`, `Save` | Blocked by `[DnnPageEditor]` — use VanjaroAI instead |

**VanjaroAI** (service root: `/API/VanjaroAI/`, requires Vanjaro.AI module):

| Controller | Key Endpoints | Auth |
|-----------|--------------|------|
| **AIPage** | List, Get, Create, Update, Publish, Delete | Admin + API Key |
| **AIBlock** | List, Get, Update | Admin + API Key |
| **AIGlobalBlock** | List, Get, Create, Update, Publish, Delete | Admin + API Key |
| **AIDesign** | GetSettings, UpdateSettings, RegisterFont, ResetSettings | Admin + API Key |
| **AIAsset** | ListFolders, CreateFolder, ListFiles, Upload, Delete | Admin + API Key |
| **AIBranding** | GetBranding, UpdateBranding | Admin + API Key |
| **AITemplate** | List, Get, Apply | Admin + API Key |
| **AISiteAnalysis** | Analyze | Admin + API Key |
| **AIHealth** | Check | Admin + API Key |
| **AIApiKey** | Generate, Revoke, Status | SuperUser only |

**DNN PersonaBar** (service root: `/API/PersonaBar/`):

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `Pages/GetPageDetails` | Full page details by pageId | Working |
| `Pages/CopyPage` | Copy page | Working |

**DNN Pages extension** (service root: `/API/Pages/`):

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `Pages/SavePageDetails` | Create or update page settings | Working |
| `Pages/DeletePage` | Delete page | Working |

### 3.4 DNN Persona Bar APIs

Base path: `/API/PersonaBar/`

| Endpoint | Purpose |
|----------|---------|
| `Pages/SearchPages` | Search/list pages with hierarchy |
| `Pages/GetPageDetails` | Full page details by tabId |
| `Pages/SavePageDetails` | Create or update page |
| `Pages/DeletePage` | Delete page |
| `Pages/CopyPage` | Copy page |
| `Modules/GetModules` | List modules on a page |
| `Modules/AddModule` | Add module to page |
| `Modules/DeleteModule` | Remove module from page |
| `Security/GetAntiForgeryToken` | CSRF token |

### 3.5 GrapesJS Content Format

Pages are stored as GrapesJS JSON. The component tree structure:

```json
{
  "pages": [
    {
      "frames": [
        {
          "component": {
            "type": "wrapper",
            "components": [
              {
                "type": "section",
                "classes": ["section-block"],
                "components": [
                  {
                    "type": "column",
                    "components": [
                      {
                        "type": "heading",
                        "content": "Welcome to Our Site",
                        "attributes": { "data-level": "h1" }
                      },
                      {
                        "type": "text",
                        "content": "<p>Body text here...</p>"
                      },
                      {
                        "type": "button",
                        "content": "Learn More",
                        "attributes": { "href": "/about" }
                      }
                    ]
                  }
                ]
              }
            ]
          }
        }
      ]
    }
  ],
  "styles": [
    {
      "selectors": [".section-block"],
      "style": { "padding": "60px 0", "background-color": "#ffffff" }
    }
  ],
  "assets": []
}
```

**Component types available (39 blocks, 60+ component types):**

Basic blocks: `section`, `grid`, `column`, `heading`, `text`, `button`, `icon`, `link-group`, `list`, `image`, `image-gallery`

Extended types: `custom-code`, `divider`, `spacer`, `videobox`, `carousel` (with carousel-item, carousel-inner, carousel-image, carousel-caption, carousel-text, carousel-heading, carousel-link), `picture-box`, `image-frame`, `image-box`, `list-box`, `link-text`, `icon-box`, `button-box`, `text-inner`, `globalblockwrapper`, `blockwrapper`, `module`, `modulewrapper`, `table`, `cell`, `row`, `thead`, `tbody`, `tfoot`, `map`, `link`, `label`, `video`, `image`, `script`, `svg`, `iframe`

**Template Library categories:** About, Banners, Call to Actions, Counters, Footers, Icon Boxes, Portfolio, Pricing Tables, Services, Team, Testimonial

**Global blocks on this instance:** Footer, Header, Shared Styles

---

## 4. Command Reference

### 4.1 Phase 1 — Core Commands (EXISTING, needs refinement)

These commands exist in the current repo and need to be validated against the live instance and refined.

#### `vanjaro auth`

```
vanjaro auth login --url URL [-u USERNAME] [-p PASSWORD] [--json]
vanjaro auth logout [--json]
vanjaro auth status [--json]
```

```
vanjaro profile list [--json]
vanjaro profile use NAME [--json]
vanjaro profile delete NAME [--force] [--json]
vanjaro api-key generate [--json]
vanjaro api-key revoke [--json]
vanjaro api-key status [--json]
vanjaro api-key set KEY [--json]
```

**Implementation notes:**
- `login` prompts for username/password if not provided (secure prompt, no echo for password)
- Saves cookies + base_url to a named profile (auto-derived from hostname)
- `--profile` option on login creates/updates a specific profile
- `status` shows auth state, base URL, and cookie presence
- `api-key generate` requires SuperUser login, saves key to active profile automatically
- `profile list` shows all configured sites with active marker

#### `vanjaro pages`

```
vanjaro pages list [--keyword SEARCH] [--json]
vanjaro pages get PAGE_ID [--json]
vanjaro pages create --title TITLE [--parent ID] [--description DESC] [--hidden] [--json]
vanjaro pages copy PAGE_ID [--title NEW_TITLE] [--json]
vanjaro pages delete PAGE_ID [--force] [--json]
vanjaro pages settings PAGE_ID [--title TITLE] [--hidden|--visible] [--description DESC] [--json]
```

**Implementation notes:**
- `list` shows hierarchical tree with indentation by `level` field
- `create` uses PersonaBar `SavePageDetails` endpoint
- `delete` requires `--force` or interactive confirmation
- `settings` is dual-mode: view-only if no flags, update if flags provided
- All endpoints return camelCase JSON; models handle conversion to snake_case

#### `vanjaro content`

```
vanjaro content get PAGE_ID [--output FILE] [--locale LOCALE] [--draft|--published] [--json]
vanjaro content update PAGE_ID [--file FILE] [--locale LOCALE] [--version VERSION] [--json]
vanjaro content publish PAGE_ID [--locale LOCALE] [--json]
```

**Implementation notes:**
- Uses VanjaroAI endpoints (`/API/VanjaroAI/AIPage/*`) which bypass the `[DnnPageEditor]` restriction
- Requires the Vanjaro.AI DNN module to be installed on the target site
- `get` returns parsed GrapesJS JSON (component tree + styles) with version metadata
- `--draft` (default) includes unpublished changes; `--published` returns only the live version
- `update` creates a new draft version (does NOT publish). Accepts GrapesJS JSON from file or stdin
- `--version` provides optimistic concurrency — update fails if the page was modified since you read it
- `publish` publishes the latest draft version
- ContentJSON/StyleJSON are stored as JSON strings in the database; the CLI parses/serializes transparently

### 4.2 Phase 2 — Block & Layout Commands (TO BUILD)

#### `vanjaro blocks`

```
vanjaro blocks list [--category CATEGORY] [--json]
vanjaro blocks categories [--json]
vanjaro blocks get BLOCK_ID [--json]
vanjaro blocks add PAGE_ID --block-type TYPE [--position INDEX] [--json]
    # Adds a block to a page at a given position in the component tree
vanjaro blocks remove PAGE_ID --component-id ID [--json]
    # Removes a component from the page
vanjaro blocks custom list [--json]
vanjaro blocks custom save --name NAME --content-file FILE [--json]
vanjaro blocks custom delete BLOCK_ID [--force] [--json]
vanjaro blocks global list [--json]
vanjaro blocks global get BLOCK_ID [--json]
vanjaro blocks global save BLOCK_ID --content-file FILE [--json]
```

**Implementation notes:**
- `list` pulls from `/API/Vanjaro/Block/GetAllBlocks` and the GrapesJS BlockManager
- `add` is a compound operation: fetch page content → insert block component at position → save page content
- Block types map to GrapesJS component types (section, heading, text, button, etc.)
- Custom blocks are user-saved reusable sections
- Global blocks (Header, Footer, Shared Styles) are shared across pages
- Block operations require understanding the GrapesJS component tree structure

**GrapesJS helper functions needed (in `utils/grapesjs.py`):**

```python
def find_component(tree: dict, component_id: str) -> Optional[dict]:
    """Walk the tree to find a component by its GrapesJS ID."""

def insert_component(tree: dict, parent_id: str, component: dict, position: int = -1) -> dict:
    """Insert a component as a child of parent_id at position."""

def remove_component(tree: dict, component_id: str) -> dict:
    """Remove a component from the tree by ID."""

def create_block_component(block_type: str, content: str = "", attributes: dict = None) -> dict:
    """Create a GrapesJS component dict for a given block type."""

def list_components(tree: dict, depth: int = 0) -> list[dict]:
    """Flatten the component tree for display (id, type, depth, content preview)."""
```

#### `vanjaro layouts`

```
vanjaro layouts list [--json]
    # List available page layouts/templates
vanjaro layouts get LAYOUT_ID [--json]
vanjaro layouts apply PAGE_ID --layout LAYOUT_ID [--json]
    # Apply a layout template to a page
vanjaro layouts templates list [--category CATEGORY] [--json]
    # List Template Library templates (About, Banners, CTAs, etc.)
vanjaro layouts templates get TEMPLATE_ID [--json]
vanjaro layouts templates apply PAGE_ID --template TEMPLATE_ID [--position INDEX] [--json]
    # Insert a template section into a page
vanjaro layouts save-as-template PAGE_ID --name NAME [--json]
    # Save current page as a reusable template
```

**Implementation notes:**
- Template Library may come from Vanjaro's CDN or local storage
- `apply` replaces the page's component tree with the layout structure
- `templates apply` inserts a template section into an existing page (non-destructive)
- `save-as-template` wraps the page action from the context menu

### 4.3 Phase 3 — Assets, Theme & Site Commands (TO BUILD)

#### `vanjaro assets`

```
vanjaro assets list [--folder PATH] [--type image|file|all] [--json]
vanjaro assets upload FILE_PATH [--folder PATH] [--json]
vanjaro assets delete ASSET_ID [--force] [--json]
vanjaro assets get ASSET_ID [--json]
```

**Implementation notes:**
- Uses `/API/Vanjaro/Upload/` endpoints
- Upload is multipart/form-data
- Useful for programmatic image management when building pages

#### `vanjaro theme`

```
vanjaro theme get [--json]
vanjaro theme set --property KEY --value VALUE [--json]
vanjaro theme css get [--output FILE]
vanjaro theme css update --file FILE [--json]
```

**Implementation notes:**
- `get/set` wrap `/API/Vanjaro/Theme/GetThemeSettings` and `UpdateThemeSettings`
- `css get/update` manage custom CSS additions
- Theme properties include colors, fonts, spacing, etc.

#### `vanjaro site`

```
vanjaro site info [--json]
vanjaro site settings [--json]
vanjaro site settings set --key KEY --value VALUE [--json]
vanjaro site nav [--json]
    # Show navigation menu structure
vanjaro site nav update --file NAV_FILE [--json]
    # Update navigation from JSON
vanjaro site seo PAGE_ID [--json]
vanjaro site seo update PAGE_ID --title TITLE --description DESC [--json]
```

#### `vanjaro modules`

```
vanjaro modules list PAGE_ID [--json]
vanjaro modules add PAGE_ID --module-type TYPE --pane PANE [--json]
vanjaro modules remove PAGE_ID MODULE_ID [--force] [--json]
vanjaro modules settings MODULE_ID [--json]
vanjaro modules settings set MODULE_ID --key KEY --value VALUE [--json]
```

**Implementation notes:**
- Uses DNN PersonaBar Modules API
- `pane` refers to content pane positions on the page
- Module types are DNN-registered module definitions

---

## 5. HTTP Client Design

### 5.1 VanjaroClient Class

```python
class VanjaroClient:
    """HTTP client with cookie auth, anti-forgery tokens, and API key support."""

    def __init__(self, config: Config):
        self._config = config
        self._session = requests.Session()  # Loaded with auth cookies from config
        self._verification_token: str | None = None

    def get(self, path: str, **kwargs) -> requests.Response:
    def post(self, path: str, **kwargs) -> requests.Response:
    def delete(self, path: str, **kwargs) -> requests.Response:

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Core request method.
        1. Verify authenticated (cookies present)
        2. Ensure anti-forgery token (fetched once per session from homepage)
        3. Build headers (Content-Type, Accept, RequestVerificationToken, X-Api-Key)
        4. Make request
        5. On 401: raise AuthError with re-login guidance
        6. On non-2xx: raise ApiError with extracted message
        """

    def _ensure_antiforgery(self):
        """GET homepage with auth cookies → scrape __RequestVerificationToken hidden input."""

    def _build_headers(self) -> dict:
        """Content-Type + Accept + RequestVerificationToken + X-Api-Key (if configured)."""

    def _raise_for_status(self, response: requests.Response):
        """Extract error from JSON body (Message, message, ExceptionMessage).
        Detects HTML error pages and truncates with clean message."""
```

### 5.2 Error Handling

```python
class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        self.message = message
        self.status_code = status_code
```

All commands catch `ApiError` and exit with code 1, printing the error message. With `--json`, errors output: `{"error": "message", "status_code": 401}`.

---

## 6. Data Models

All models use Pydantic v2 with `model_config = ConfigDict(populate_by_name=True)` to handle camelCase API responses.

### 6.1 Page

```python
class Page(BaseModel):
    id: int                         # tabId
    name: str                       # page name
    title: str                      # page title (browser tab)
    url: str                        # relative URL
    parent_id: int = 0              # parent tabId (0 = root)
    is_deleted: bool = False
    include_in_menu: bool = True
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "Visible"
    level: int = 0                  # hierarchy depth
    has_children: bool = False
    portal_id: int = 0

    @classmethod
    def from_api(cls, data: dict) -> "Page":
        """Handle both 'tabId'/'id' and 'TabId' spellings."""
```

### 6.2 PageContent

```python
class ContentBlock(BaseModel):
    id: Optional[str] = None
    type: str = "default"
    content: str = ""
    tag_name: Optional[str] = None
    classes: list[str] = []
    attributes: dict = {}
    styles: dict = {}
    components: list["ContentBlock"] = []

class PageContent(BaseModel):
    page_id: int
    locale: str = "en-US"
    components: list[ContentBlock] = []
    styles: list[dict] = []
    assets: list[dict] = []
    raw: dict = {}                  # Original API response for passthrough

    @classmethod
    def from_api(cls, data: dict, page_id: int) -> "PageContent":
        """Parse GrapesJS JSON, handling BlockData wrapper."""

    def to_api_payload(self) -> dict:
        """Serialize back to Vanjaro API format."""
```

### 6.3 Block (Phase 2)

```python
class Block(BaseModel):
    id: str
    label: str
    category: str = ""
    content: str = ""               # HTML template
    media: str = ""                 # Icon/preview
    is_custom: bool = False
    is_global: bool = False

class BlockCategory(BaseModel):
    name: str
    blocks: list[Block] = []
```

### 6.4 Asset (Phase 3)

```python
class Asset(BaseModel):
    id: int
    file_name: str
    folder: str = ""
    url: str = ""
    size: int = 0
    content_type: str = ""
    created_date: Optional[str] = None
```

---

## 7. Skills (SKILL.md Files)

Each skill file is a self-contained reference that Claude Code loads on demand. Format:

### 7.1 Master Skill (`skills/SKILL.md`)

```markdown
# vanjaro-cli

CLI tool for managing Vanjaro/DNN websites. Load specific skills for detailed usage.

## Available Skills

| Skill | Commands | Use When |
|-------|----------|----------|
| auth | login, logout, status | Connecting to a Vanjaro site |
| pages | list, get, create, copy, delete, settings | Managing page structure |
| content | get, update, publish | Reading/writing page content |
| blocks | list, categories, add, remove, custom, global | Working with building blocks |
| layouts | list, apply, templates | Applying page layouts |
| assets | list, upload, delete | Managing images and files |
| theme | get, set, css | Customizing site appearance |
| site | info, settings, nav, seo | Site-level configuration |
| modules | list, add, remove, settings | Managing DNN modules |

## Quick Start
1. `vanjaro auth login --url http://your-site.com`
2. `vanjaro pages list --json`
3. `vanjaro content get PAGE_ID --output page.json`
4. Edit page.json
5. `vanjaro content update PAGE_ID --file page.json`
6. `vanjaro content publish PAGE_ID`
```

### 7.2 Per-Command Skills

Each skill file (pages.md, content.md, blocks.md, etc.) should include:
1. Full command syntax with all options
2. API endpoints used
3. Example workflows (with actual CLI commands)
4. JSON output schemas
5. Common patterns and gotchas
6. Error handling guidance

---

## 8. Testing Strategy

### 8.1 Unit Tests (mocked HTTP)

Use the `responses` library to mock all API calls. Every command must have tests for:

1. **Success case** — correct output (both text and `--json`)
2. **Error case** — API returns error, verify exit code 1 and error message
3. **Empty state** — no results (empty list, 404)
4. **Auth failure** — 401, verify error message
5. **Edge cases** — special characters, long names, nested pages, etc.

**Test structure per command group:**

```python
# tests/test_pages.py
class TestPagesList:
    def test_list_text_output(self, runner, mock_config, mocked_responses): ...
    def test_list_json_output(self, runner, mock_config, mocked_responses): ...
    def test_list_empty(self, runner, mock_config, mocked_responses): ...
    def test_list_with_keyword(self, runner, mock_config, mocked_responses): ...
    def test_list_api_error(self, runner, mock_config, mocked_responses): ...

class TestPagesGet:
    def test_get_success(self, runner, mock_config, mocked_responses): ...
    def test_get_json(self, runner, mock_config, mocked_responses): ...
    def test_get_not_found(self, runner, mock_config, mocked_responses): ...

# ... etc for create, copy, delete, settings
```

### 8.2 Integration Tests (live instance)

Marked with `@pytest.mark.integration` so they're skipped by default. Run with `pytest -m integration`.

```python
# tests/integration/conftest.py
@pytest.fixture
def live_client():
    """Create a real client from VANJARO_BASE_URL env var."""
    url = os.environ.get("VANJARO_BASE_URL")
    if not url:
        pytest.skip("VANJARO_BASE_URL not set")
    # Login with VANJARO_USERNAME / VANJARO_PASSWORD
    ...
```

Integration tests should:
1. Create a test page → verify it exists → delete it
2. Read page content → modify → update → verify → revert
3. Upload an asset → verify → delete
4. NOT modify the Home page or other production content

### 8.3 GrapesJS Helper Tests

```python
# tests/test_grapesjs.py
class TestFindComponent:
    def test_find_root(self): ...
    def test_find_nested(self): ...
    def test_not_found(self): ...

class TestInsertComponent:
    def test_insert_at_end(self): ...
    def test_insert_at_position(self): ...
    def test_insert_into_empty(self): ...

class TestRemoveComponent:
    def test_remove_leaf(self): ...
    def test_remove_with_children(self): ...
    def test_remove_not_found(self): ...

class TestCreateBlockComponent:
    def test_heading(self): ...
    def test_text(self): ...
    def test_section_with_columns(self): ...
    def test_button_with_attributes(self): ...
    def test_image_with_src(self): ...
```

### 8.4 Test Fixtures

```python
# tests/conftest.py

BASE_URL = "https://example.vanjaro.com"

# JWT with exp=9999999999 (never expires in tests)
FAKE_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwibmFtZSI6ImFkbWluIiwiZXhwIjo5OTk5OTk5OTk5fQ.xxx"

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Redirect config to tmp_path, write fake config."""
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({
        "base_url": BASE_URL,
        "token": FAKE_TOKEN,
        "refresh_token": "fake-refresh",
        "portal_id": 0,
        "username": "admin"
    }))
    monkeypatch.setattr("vanjaro_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("vanjaro_cli.config.CONFIG_FILE", config_file)
    # Also patch in command modules that import CONFIG_FILE at module level
    monkeypatch.setattr("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file)

@pytest.fixture
def mocked_responses():
    with responses.RequestsMock() as rsps:
        yield rsps

def make_page(**overrides) -> dict:
    """Factory for PersonaBar-shaped page dicts."""
    base = {
        "tabId": 1, "name": "Home", "title": "Home", "url": "/",
        "parentId": 0, "isDeleted": False, "includeInMenu": True,
        "status": "Visible", "level": 0, "hasChildren": False, "portalId": 0
    }
    base.update(overrides)
    return base
```

---

## 9. Implementation Phases

### Phase 1: Core — COMPLETE
**Status:** Validated, 97 tests passing, all commands live-tested against vanjarocli.local.
**What was built:** auth, pages, content, profile, api-key commands + cookie-based client + models + VanjaroAI module (C#).
**Key changes from original spec:**
- Switched from JWT to cookie-based auth (JWT can't satisfy `[ValidateAntiForgeryToken]`)
- Content endpoints switched from Vanjaro native (`/API/Vanjaro/Page/*`) to VanjaroAI (`/API/VanjaroAI/AIPage/*`) to bypass `[DnnPageEditor]` restriction
- Added named profiles for multi-site management
- Added API key security layer (RequireApiKey + RequireAdmin on VanjaroAI endpoints)
- Added `content publish` command (VanjaroAI has distinct publish endpoint)
- Added `--version` conflict detection on `content update`

### Phase 2: Blocks & Layouts
**Effort:** Medium
**What to build:**
1. `utils/grapesjs.py` — Component tree manipulation helpers
2. `models/block.py` — Block and BlockCategory models
3. `commands/blocks_cmd.py` — Block CRUD commands
4. `commands/layouts_cmd.py` — Layout/template commands
5. Tests for all of the above
6. Skills: `blocks.md`, `layouts.md`

**Key challenge:** The `blocks add` command needs to fetch page content, manipulate the GrapesJS component tree, and save it back. This is the core value-add for AI-driven page building.

### Phase 3: Assets, Theme & Site
**Effort:** Medium
**What to build:**
1. `models/asset.py`, `models/module.py`
2. `commands/assets_cmd.py` — File/image upload and management
3. `commands/theme_cmd.py` — Theme settings and custom CSS
4. `commands/site_cmd.py` — Site info, settings, navigation, SEO
5. `commands/modules_cmd.py` — DNN module management
6. Tests and skills for all

### Phase 4: AI Workflow Commands
**Effort:** Large
**What to build:** Higher-level commands that combine primitives for common AI workflows:
1. `vanjaro build --from-design DESCRIPTION` — Create a page from a natural language description
2. `vanjaro build --from-template TEMPLATE` — Build from a Template Library template
3. `vanjaro diff PAGE_ID` — Show what changed since last publish
4. `vanjaro snapshot PAGE_ID` — Save a restorable snapshot of page state
5. `vanjaro rollback PAGE_ID --snapshot ID` — Restore a previous state

---

## 10. Live Instance Reference

**Instance:** http://vanjarocli.local (Windows machine, DNN 9.10.2 + Vanjaro 1.6 extension)
**Platform:** DNN 9.10.2 with Vanjaro 1.6 installed as extension (not standalone Vanjaro Platform)
**VanjaroAI module:** Installed (Vanjaro.AI.dll v1.0.0.0)

### Current Pages
| Name | Tab ID | In Nav | Notes |
|------|--------|--------|-------|
| Home | 21 | Yes | Landing page with hero, Welcome section |
| About Us | - | Hidden | Hidden from nav |
| Coaching | - | Yes | |
| Services | - | Yes | |
| Membership | - | Yes | |
| Contact | - | Yes | |

### Editor Tabs
- **BLOCKS** — 39 built-in blocks in BASIC category
- **CUSTOM** — Empty (no user-saved blocks yet)
- **GLOBAL** — Footer, Header, Shared Styles
- **LIBRARY** — Template Library with pre-built sections

### GrapesJS Editor Instance
- `window.VjEditor` — GrapesJS editor object
- `$.ServicesFramework(0).getServiceRoot('Vanjaro')` → `/API/Vanjaro/`
- 39 blocks, 60+ component types registered
- Editor commands: undo, redo, preview, copy, paste, layers, styles, traits, export

### Admin Menu
- **Site** → Pages, Users, Roles, Assets
- **Design** → Theme settings
- **Settings** → Site configuration
- **Tools** → Maintenance tools
- **Help** → Documentation

### Page Context Menu Actions
View, Copy, Settings, Hide from Nav Menu, Make Private, Save Page As Template, Set Page As

---

## 11. Coding Standards

1. **Type hints everywhere** — All function signatures fully typed, `from __future__ import annotations` in every module
2. **Self-documenting code** — Comments explain WHY, not WHAT. Descriptive names over comments.
3. **Pydantic models** — API response models use `Field(alias="camelCase")` + `populate_by_name=True`. Use `from_api()` / `to_api_payload()` methods.
4. **Click decorators** — `@click.option` with help text, types, and defaults. `--json` on every command.
5. **Error messages** — User-friendly, actionable (e.g., "Run `vanjaro auth login` to re-authenticate")
6. **Exit codes** — 0 for success, 1 for errors
7. **Module exports** — Every module with public API defines `__all__`
8. **Consistent naming** — snake_case in Python, camelCase for API payloads, kebab-case for CLI flags
9. **Shared helpers** — `get_client()`, `exit_error()`, `output_result()` in `commands/helpers.py`, not duplicated
10. **Domain exceptions** — `AuthError`, `ConfigError`, `ApiError` — never raise generic `Exception`

---

## 12. Development Workflow

1. Branch from `main` for features
2. Write tests first (or alongside)
3. All tests must pass before PR
4. `--json` output for every command
5. Update relevant SKILL.md when adding/changing commands
6. Integration tests run separately: `pytest -m integration`
7. Format with black, lint with ruff

---

## 13. Open Questions

1. ~~**Template Library source**~~ — **RESOLVED.** Templates are stored locally on the DNN instance, not loaded from CDN. The `GET /API/VanjaroAI/AITemplate/List` endpoint returns page templates (e.g., "Default", "Home") with metadata. Template count depends on what's installed on the instance.
2. ~~**Block content format**~~ — **RESOLVED.** No dedicated block insertion endpoint. Block addition is a read-modify-write on full page JSON. See Section 14 for details.
3. ~~**Multi-language support**~~ — **RESOLVED.** The `--locale` flag works. Tested `content get 34 --locale fr-FR` — returns the same content when no localized version exists. The VanjaroAI endpoint accepts locale as a parameter and the `VJ_Core_Pages` table stores content per locale. Multi-language content editing is supported but requires the site to have multiple languages enabled.
4. ~~**Workflow states**~~ — **RESOLVED.** VanjaroAI uses version-based draft/publish workflow. `content update` always creates a new draft version. `content publish` publishes the latest draft. The `expectedVersion` parameter on update provides conflict detection. Custom review workflows are supported by Vanjaro but not exercised by the CLI.
5. ~~**Permission model**~~ — **RESOLVED.** Page permissions are returned by `GetPageDetails` in a `permissions` object containing `permissionDefinitions` (View Tab, Edit Tab), `rolePermissions` (per-role access), and `userPermissions`. A separate `pagePermissions` object shows the current user's capabilities (addContentToPage, addPage, adminPage, copyPage, deletePage, etc.). The CLI operates as admin so all permissions are granted. Multi-user permission management could be added as a future feature.

---

## 14. Spec Clarifications & Design Decisions

*Captured 2026-04-02 via spec interview session.*

### Design Decisions

- **Build order**: Validate Phase 1 against live instance first, then update spec with findings, then build Phase 2 separately.
- **Live instance**: `http://vanjarocli.local` (fresh/throwaway install, not localhost:8085).
- **Block insertion mechanism**: Confirmed read-modify-write. No `AddBlockToPage` API exists. The CLI must: GET page → modify gjs-components → POST page/save. The save payload requires `gjs-html`, `gjs-css`, `gjs-components`, `styles`, and `IsPublished`.
- **Save payload investigation**: During validation, test whether the server re-renders HTML from gjs-components (allowing components-only modification) or stores all three independently. Read `PageManager.Update()` source AND test with live API call.
- **DNN Module blocks**: Deferred to Phase 3 `modules` command. Phase 2 `blocks add` handles only GrapesJS-native blocks (section, heading, text, button, etc.).
- **Block positioning**: Use `--parent-id` (GrapesJS component ID) + `--position` (index within parent). Default: when `--parent-id` is omitted, insert as direct child of root wrapper.
- **Publish flow**: Decide after validation whether `content publish` remains a separate command or merges into `content update --publish` based on whether the API has a distinct publish endpoint or just an `IsPublished` flag on save.
- **API audit approach**: Fix endpoint mismatches as encountered during validation rather than systematic audit upfront.
- **Skills**: Write skill files (auth.md, pages.md, content.md) after Phase 1 validation, documenting confirmed API behavior.

### Edge Cases & Behavior (Resolved)

- **Concurrency**: **RESOLVED.** VanjaroAI returns `version` metadata on every page response. The `content update` command supports `--version` for optimistic locking — update fails if the page was modified since you read it. Version is auto-incremented on each save.
- **Workflow errors**: VanjaroAI uses draft/publish model. Updates always create drafts. Publishing is a separate explicit action. Review workflows are supported by Vanjaro but not currently configured on vanjarocli.local.
- **Auth mechanism**: **RESOLVED.** Cookie-based auth via `/API/Login/Login/UserLogin` (Vanjaro's AJAX endpoint). JWT cannot satisfy `[ValidateAntiForgeryToken]`. Anti-forgery token scraped from homepage HTML.
- **API surface**: **RESOLVED.** Content operations use VanjaroAI endpoints (`/API/VanjaroAI/AIPage/*`) which bypass `[DnnPageEditor]`. Page management uses a mix of Vanjaro (`GetPages`) and PersonaBar (`GetPageDetails`, `SavePageDetails`) endpoints.
- **gjs-html regeneration**: **RESOLVED.** The VanjaroAI endpoint stores `ContentJSON`, `StyleJSON`, and `contentHtml` independently. The `contentHtml` field contains rendered HTML from the GrapesJS JSON. When updating via CLI, only `ContentJSON`/`StyleJSON` need to be sent — the `contentHtml` is stored alongside but the JSON is the source of truth for the editor. A GrapesJS rendering layer is NOT needed for the CLI; the server handles rendering when the page is viewed.

### Phase 1 Validation Results

- **97 unit tests passing** across 7 test files
- **All non-destructive commands live-tested** against vanjarocli.local
- **Content round-trip verified**: get → save to file → update from file → publish (version 2 → 3)
- **Multi-locale tested**: `--locale fr-FR` works (returns same content when no localized version exists)
- **API key flow verified**: generate → status (server+local configured) → content access with X-Api-Key header
- **Profile auto-creation verified**: login creates profile from hostname automatically

### Key Findings from Validation

| Finding | Detail |
|---------|--------|
| **Auth mechanism** | Cookie-based via Vanjaro AJAX, not DNN JWT. JWT can't satisfy `[ValidateAntiForgeryToken]`. |
| **Content access** | Standard Vanjaro endpoints blocked by `[DnnPageEditor]`. VanjaroAI module provides headless access via `[RequireAdmin]` + `[RequireApiKey]`. |
| **Page listing format** | Vanjaro's `GetPages` returns `{Text, Value, Url}` with `-  ` prefix for nesting, not PersonaBar's `{tabId, name, url}`. |
| **Version management** | Each content update creates a new DB row in `VJ_Core_Pages`. Version history maintained. Conflict detection via `expectedVersion`. |
| **Template storage** | Templates stored locally on DNN instance, not CDN. `AITemplate/List` returns installed templates. |
| **Permission model** | `GetPageDetails` returns full permission matrix: `permissionDefinitions`, `rolePermissions`, `userPermissions`, plus current user's `pagePermissions` capabilities. |
| **Content fields** | `contentJSON` (GrapesJS component tree), `styleJSON` (GrapesJS styles), `contentHtml` (rendered HTML). JSON is source of truth. |

### Confirmed API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/API/Login/Login/UserLogin` | POST | Cookie-based login (Vanjaro AJAX) |
| `/API/Vanjaro/Page/GetPages` | GET | List all pages (`{Text, Value, Url}` format) |
| `/API/PersonaBar/Pages/GetPageDetails` | GET | Full page details by pageId |
| `/API/Pages/Pages/SavePageDetails` | POST | Create or update page settings |
| `/API/Pages/Pages/DeletePage` | POST | Delete page |
| `/API/PersonaBar/Pages/CopyPage` | POST | Copy page |
| `/API/VanjaroAI/AIPage/Get` | GET | Get page content (ContentJSON, StyleJSON, version) |
| `/API/VanjaroAI/AIPage/Update` | POST | Update content (creates draft version) |
| `/API/VanjaroAI/AIPage/Publish` | POST | Publish latest draft |
| `/API/VanjaroAI/AIApiKey/Generate` | POST | Generate API key (SuperUser only) |
| `/API/VanjaroAI/AIApiKey/Revoke` | POST | Revoke API key (SuperUser only) |
| `/API/VanjaroAI/AIApiKey/Status` | GET | Check API key configuration |
| `/API/VanjaroAI/AIHealth/Check` | GET | Health check |

### Open Questions (Remaining for Phase 2+)

- **Block catalog API**: Need to verify if `/API/Vanjaro/Block/GetAllBlocks` works with cookie auth or needs VanjaroAI equivalent.
- **Template apply**: The `AITemplate/Apply` endpoint exists but hasn't been tested. Need to verify payload format.
- **Global block editing**: `AIGlobalBlock/*` endpoints exist but haven't been exercised from the CLI yet.
