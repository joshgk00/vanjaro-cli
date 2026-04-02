# Content Skill

Read and write Vanjaro page content (GrapesJS JSON format).

## Commands

### `vanjaro content get <page-id>`

```bash
vanjaro content get 42                          # print JSON to stdout
vanjaro content get 42 --output page42.json    # save to file
vanjaro content get 42 --locale fr-FR          # specific locale
```

Returns full GrapesJS state: `components`, `styles`, and the raw API response.

### `vanjaro content update <page-id>`

```bash
vanjaro content update 42 --file page42.json   # from file
cat page42.json | vanjaro content update 42    # from stdin
vanjaro content update 42 --file page42.json --json  # structured output
```

Input JSON should contain `components` and `styles` arrays (standard GrapesJS format).

### `vanjaro content publish <page-id>`

```bash
vanjaro content publish 42
vanjaro content publish 42 --json
```

Publishes pending draft changes.

## Typical Claude Code Workflow

```bash
# 1. Pull current content
vanjaro content get 42 --output page42.json

# 2. Edit page42.json (e.g., via Claude)

# 3. Push changes
vanjaro content update 42 --file page42.json

# 4. Publish
vanjaro content publish 42
```

## API Endpoints Used

| Action | Method | Endpoint |
|--------|--------|----------|
| Get content | GET | `/API/Vanjaro/Page/GetPageContent` |
| Update content | POST | `/API/Vanjaro/Page/UpdatePageContent` |
| Publish | POST | `/API/Vanjaro/Page/PublishPage` |
