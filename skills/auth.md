# Auth Skill

Manage authentication with a Vanjaro/DNN site using DNN's JWT token endpoint.

## Commands

### `vanjaro auth login`

```bash
vanjaro auth login --url https://your-site.com --username admin --password secret
# or via env vars:
VANJARO_BASE_URL=https://your-site.com vanjaro auth login
```

Stores the JWT token in `~/.vanjaro-cli/config.json` (chmod 600).

### `vanjaro auth logout`

```bash
vanjaro auth logout
```

Invalidates the token server-side and removes it from local config.

### `vanjaro auth status`

```bash
vanjaro auth status --json
# {"status":"authenticated","base_url":"https://...","has_token":true}
```

## How it works

- Calls `POST /API/JwtAuth/Login` with `{"u": username, "p": password}`
- Receives `Token` (JWT) and `RenewToken` (refresh)
- Tokens auto-refresh when within 60 seconds of expiry
- CSRF tokens for mutating requests are fetched from `/API/PersonaBar/Security/GetAntiForgeryToken`

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VANJARO_BASE_URL` | Site base URL |
| `VANJARO_USERNAME` | DNN username |
| `VANJARO_PASSWORD` | DNN password |
| `VANJARO_TOKEN` | Override stored token |
| `VANJARO_PORTAL_ID` | Portal ID for multi-site (default: 0) |
