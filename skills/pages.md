# Pages Skill

Manage Vanjaro/DNN pages via the PersonaBar Pages API.

## Commands

### `vanjaro pages list`

```bash
vanjaro pages list
vanjaro pages list --keyword "about"
vanjaro pages list --json        # returns array of page objects
```

Fetches all pages with hierarchy (indented names for children).

### `vanjaro pages get <id>`

```bash
vanjaro pages get 42
vanjaro pages get 42 --json
```

### `vanjaro pages create`

```bash
vanjaro pages create --title "New Page"
vanjaro pages create --title "Blog" --name "blog" --parent 5
vanjaro pages create --title "Hidden" --hidden
vanjaro pages create --title "Blog" --json
```

### `vanjaro pages copy <id>`

```bash
vanjaro pages copy 10
vanjaro pages copy 10 --title "Home - Copy"
```

### `vanjaro pages delete <id>`

```bash
vanjaro pages delete 42 --force        # skip confirmation
vanjaro pages delete 42                # prompts for confirmation
```

### `vanjaro pages settings <id>`

```bash
vanjaro pages settings 42                        # view current settings
vanjaro pages settings 42 --title "New Title"   # update title
vanjaro pages settings 42 --hidden              # remove from menu
vanjaro pages settings 42 --visible             # add back to menu
```

## API Endpoints Used

| Action | Method | Endpoint |
|--------|--------|----------|
| List | GET | `/API/PersonaBar/Pages/SearchPages` |
| Get | GET | `/API/PersonaBar/Pages/GetPageDetails` |
| Create / Update | POST | `/API/PersonaBar/Pages/SavePageDetails` |
| Delete | POST | `/API/PersonaBar/Pages/DeletePage` |
| Copy | POST | `/API/PersonaBar/Pages/CopyPage` |
