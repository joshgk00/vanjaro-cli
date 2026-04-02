# vanjaro-cli Skills

A CLI tool for managing Vanjaro/DNN websites from Claude Code.

## Available Skills

| Skill | File | What it does |
|-------|------|--------------|
| `auth` | [auth.md](auth.md) | Login, logout, check auth status |
| `pages` | [pages.md](pages.md) | List, create, copy, delete, and configure pages |
| `content` | [content.md](content.md) | Read and write GrapesJS page content |

## Quick Start

```bash
# Install
pip install -e .

# Authenticate
vanjaro auth login --url https://your-site.com

# List pages
vanjaro pages list --json

# Get page content
vanjaro content get 42 --output page42.json
```

## All commands support `--json` for structured output

This makes the CLI easy to use from Claude Code, scripts, and CI pipelines.
