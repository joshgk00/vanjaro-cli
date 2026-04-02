# Auth -- vanjaro-cli

Authentication, profile management, and API key commands.

## Commands

### `vanjaro auth login [OPTIONS]`

Authenticate via DNN login form and store session cookies.

**Options:**
- `--url URL` -- Base URL of the Vanjaro site (or set `VANJARO_BASE_URL` env var)
- `--username, -u TEXT` -- DNN username (or set `VANJARO_USERNAME`; prompted if omitted)
- `--password, -p TEXT` -- DNN password (or set `VANJARO_PASSWORD`; prompted if omitted)
- `--profile NAME` -- Save credentials to a named profile
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro auth login --url http://my-site.com --profile prod
```

**JSON output:**
```json
{
  "status": "ok",
  "base_url": "http://my-site.com",
  "message": "Logged in successfully."
}
```

### `vanjaro auth logout [OPTIONS]`

Clear stored session cookies.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro auth logout
```

### `vanjaro auth status [OPTIONS]`

Show current authentication status.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro auth status --json
```

**JSON output:**
```json
{
  "status": "authenticated",
  "base_url": "http://my-site.com",
  "portal_id": 0,
  "has_cookies": true
}
```

---

### `vanjaro profile list [OPTIONS]`

List all configured profiles.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro profile list --json
```

**JSON output:**
```json
[
  { "name": "dev", "base_url": "http://dev.example.com", "active": true },
  { "name": "staging", "base_url": "http://staging.example.com", "active": false }
]
```

### `vanjaro profile use NAME`

Switch the active profile.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro profile use staging
```

### `vanjaro profile delete NAME [OPTIONS]`

Delete a profile.

**Options:**
- `--force` -- Skip confirmation prompt
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro profile delete old-site --force
```

---

### `vanjaro api-key generate [OPTIONS]`

Generate a new API key (requires SuperUser login). The key is saved to the active profile automatically. Any previous key is replaced.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro api-key generate --json
```

**JSON output:**
```json
{
  "status": "ok",
  "api_key": "abc123...",
  "message": "API key generated."
}
```

### `vanjaro api-key revoke [OPTIONS]`

Revoke the current API key on the server and remove it from local config.

**Options:**
- `--json` -- Output as JSON

### `vanjaro api-key status [OPTIONS]`

Check API key status on both server and local config.

**Options:**
- `--json` -- Output as JSON

**JSON output:**
```json
{
  "server_configured": true,
  "local_configured": true,
  "message": "API key is active."
}
```

### `vanjaro api-key set KEY [OPTIONS]`

Manually set an API key in the active profile without calling the server.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro api-key set "my-api-key-value"
```

## Workflows

### First-Time Setup

```bash
# Log in and create a profile
vanjaro auth login --url http://my-site.com --profile mysite

# Verify authentication
vanjaro auth status --json

# Generate an API key (needed for content/blocks/templates commands)
vanjaro api-key generate
```

### Multi-Site Management

```bash
# Create profiles for each environment
vanjaro auth login --url http://dev.example.com --profile dev
vanjaro auth login --url http://staging.example.com --profile staging

# List profiles
vanjaro profile list

# Switch to a specific site
vanjaro profile use dev
```

### Environment Variable Authentication

```bash
# Set env vars for CI/CD
export VANJARO_BASE_URL=http://my-site.com
export VANJARO_USERNAME=admin
export VANJARO_PASSWORD=secret

# Login picks up env vars automatically
vanjaro auth login
```

## Error Handling

- "No site URL provided": Pass `--url` or set `VANJARO_BASE_URL` environment variable.
- "401 Unauthorized" on login: Check username/password. DNN locks accounts after repeated failures.
- "Profile not found" on `profile use`: Run `vanjaro profile list` to see available profiles.
- API key commands fail with 403: Only SuperUser (host) accounts can generate API keys.

## Config Storage

Credentials are stored in `~/.vanjaro-cli/config.json`. This file contains session cookies and API keys -- keep it secure.
