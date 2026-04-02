# Assets -- vanjaro-cli

Manage files and folders in the Vanjaro asset library. These commands require the VanjaroAI module (Vanjaro.AI.dll) installed on the DNN site.

## Commands

### `vanjaro assets folders [OPTIONS]`

List all asset folders.

**Options:**
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro assets folders --json
```

**JSON output:**
```json
[
  {
    "folder_id": 0,
    "folder_path": "",
    "display_name": "Root"
  },
  {
    "folder_id": 1,
    "folder_path": "Images/",
    "display_name": "Images"
  }
]
```

### `vanjaro assets list [OPTIONS]`

List files in a folder.

**Options:**
- `--folder INT` -- Folder ID to list files from (default: all files)
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro assets list --json
vanjaro assets list --folder 1 --json
```

**JSON output:**
```json
[
  {
    "file_id": 10,
    "file_name": "logo.png",
    "folder_path": "Images/",
    "relative_path": "Images/logo.png",
    "url": "/Portals/0/Images/logo.png",
    "extension": "png",
    "size": 24576,
    "width": 200,
    "height": 80,
    "content_type": "image/png",
    "last_modified": "2024-01-15T10:30:00"
  }
]
```

### `vanjaro assets upload FILE_PATH [OPTIONS]`

Upload a local file to the asset library. The file content is base64-encoded and sent to the API.

**Options:**
- `--folder TEXT` -- Folder path to upload into (e.g., `Images/`). Defaults to root.
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro assets upload ./logo.png --folder "Images/" --json
vanjaro assets upload ./document.pdf --json
```

### `vanjaro assets delete FILE_ID [OPTIONS]`

Delete a file by ID.

**Options:**
- `--force` -- Skip confirmation prompt
- `--json` -- Output as JSON

**Example:**
```bash
vanjaro assets delete 10 --force --json
```

**JSON output:**
```json
{
  "status": "deleted",
  "file_id": 10
}
```

## Workflows

### Upload and Reference an Image

```bash
# List folders to find the right destination
vanjaro assets folders --json

# Upload the image
vanjaro assets upload ./hero-banner.jpg --folder "Images/" --json

# Find the uploaded file URL
vanjaro assets list --folder 1 --json | jq '.[] | select(.file_name == "hero-banner.jpg") | .url'
```

### Audit Asset Usage

```bash
# List all files
vanjaro assets list --json | jq '.[] | {file_name, size, content_type}'

# Find large files (over 1MB)
vanjaro assets list --json | jq '[.[] | select(.size > 1048576)] | sort_by(.size) | reverse'
```

### Bulk Upload

```bash
# Upload multiple files
for file in ./images/*.png; do
  vanjaro assets upload "$file" --folder "Images/" --json
done
```

### Clean Up Unused Files

```bash
# List files and review
vanjaro assets list --json | jq '.[] | "\(.file_id)\t\(.file_name)\t\(.size)"'

# Delete specific files
vanjaro assets delete 10 --force
vanjaro assets delete 11 --force
```

## Error Handling

- "File not found" on upload: The local file path does not exist. Check the path.
- "Folder ID must be a non-negative integer": Folder IDs start at 0. Use `assets folders` to see valid IDs.
- "File ID must be a positive integer": File IDs start at 1. Use `assets list` to see valid file IDs.
- Confirmation prompt on `delete`: Use `--force` to skip in scripts.
- Large file uploads may time out: The file is base64-encoded in the JSON payload. Very large files (50MB+) may exceed server limits.
