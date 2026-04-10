# Crawl Output Format

`vanjaro migrate crawl` writes its output to `artifacts/migration/{site-slug}/`.
Every file below is produced by the CLI — the skill reads them but never writes
them by hand.

## Directory layout

```
artifacts/migration/{site-slug}/
  site-inventory.json       — master manifest (pages + assets + global refs)
  page-url-map.json         — source URL → Vanjaro page path
  design-tokens.json        — theme tokens in theme-extract-tokens format
  pages/
    {slug}/
      section-001-{type}.json
      section-002-{type}.json
      ...
  global/
    header.json             — written when the crawler detects a <header>
    footer.json             — written when the crawler detects a <footer>
  assets/
    manifest.json           — one entry per downloaded asset
    {filename}.{ext}        — the downloaded files
```

## site-inventory.json

```json
{
  "source_url": "https://example.com/",
  "crawled_at": "2026-04-09T12:34:56+00:00",
  "pages": [
    {
      "url": "https://example.com/",
      "path": "/",
      "title": "Example Co — Home",
      "slug": "home",
      "sections": [
        {
          "file": "pages/home/section-001-hero.json",
          "type": "hero",
          "template": "Centered Hero"
        },
        {
          "file": "pages/home/section-002-cards.json",
          "type": "cards",
          "template": "Feature Cards (3-up)"
        }
      ]
    }
  ],
  "assets": {
    "count": 24,
    "manifest": "assets/manifest.json"
  },
  "global": {
    "header": "global/header.json",
    "footer": "global/footer.json"
  }
}
```

Fields:
- `pages[].path` — the URL path as seen by the source site (`/about`, `/services/consulting`).
- `pages[].slug` — the filesystem-safe slug used for the `pages/{slug}/` directory.
- `pages[].sections[].template` — the crawler's best-guess block template name. It's a hint, not a decision; Stage 2 reviews and may override.
- `global` — only contains keys for global elements the crawler actually detected.

## page-url-map.json

Source URL → Vanjaro-side path. Seeded by the crawler from `pages[].slug`. Used by `vanjaro migrate rewrite-urls` in Stage 5.

```json
{
  "https://example.com/": "/",
  "https://example.com/about": "/about",
  "https://example.com/services": "/services",
  "https://example.com/services/consulting": "/services-consulting"
}
```

If the Vanjaro pages are created with different names, hand-edit this file (or
run `vanjaro migrate build-id-map` in Stage 4 and merge the results).

## pages/{slug}/section-{NNN}-{type}.json

Per-section content extracted from the source page. File names use three-digit
padded indices so natural-sort ordering works (`section-002-` sorts before
`section-010-`).

```json
{
  "type": "hero",
  "template": "Centered Hero",
  "content": {
    "headings": ["Transform Your Business"],
    "paragraphs": [
      "We deliver innovative solutions that drive measurable growth for companies of all sizes."
    ],
    "buttons": [
      {"text": "Get Started", "href": "/contact"}
    ],
    "images": [
      {
        "src": "https://example.com/images/hero-bg.jpg",
        "alt": "Team collaboration",
        "role": "background"
      }
    ],
    "lists": [],
    "structured_data": {}
  }
}
```

`vanjaro migrate assemble-page` reads these files and maps the first
heading/paragraph/button into the `heading_1`, `text_1`, `button_text_1`,
`button_href_1` override slots for the referenced template. Explicit per-slot
overrides can be passed at assemble time for anything beyond the first of each
type.

## global/header.json and global/footer.json

Navigation and footer content extracted from the source site.

```json
{
  "type": "header",
  "content": {
    "logo": {
      "src": "https://example.com/logo.png",
      "alt": "Example Co"
    },
    "nav_items": [
      {"label": "Home", "href": "/"},
      {"label": "About", "href": "/about"},
      {"label": "Services", "href": "/services"},
      {"label": "Contact", "href": "/contact"}
    ],
    "images": [
      {"src": "https://example.com/logo.png", "alt": "Example Co", "role": "logo"}
    ]
  }
}
```

The crawler only writes these files if it detects `<header>` / `<footer>`
elements (or their `role="banner"` / `role="contentinfo"` equivalents). If the
source site builds its header with generic `<div>`s, these files may be absent
— handle that case gracefully.

## assets/manifest.json

Array of asset records. `vanjaro migrate crawl` populates `source_url`,
`local_file`, `filename`, `size_bytes`, `content_type`. Stage 3 upload populates
`vanjaro_url` and `vanjaro_file_id`. `vanjaro migrate rewrite-urls` reads the
populated manifest to rewrite image `src` attributes.

```json
[
  {
    "source_url": "https://example.com/images/hero-bg.jpg",
    "local_file": "assets/hero-bg.jpg",
    "filename": "hero-bg.jpg",
    "size_bytes": 145320,
    "content_type": "image/jpeg",
    "vanjaro_url": null,
    "vanjaro_file_id": null,
    "uploaded": false
  }
]
```

After Stage 3 upload:

```json
{
  "source_url": "https://example.com/images/hero-bg.jpg",
  "local_file": "assets/hero-bg.jpg",
  "filename": "hero-bg.jpg",
  "size_bytes": 145320,
  "content_type": "image/jpeg",
  "vanjaro_url": "/Portals/0/Images/hero-bg.jpg",
  "vanjaro_file_id": 1234,
  "uploaded": true
}
```

## design-tokens.json

Same schema as the `theme-extract-tokens` skill output. Colors, fonts, spacing,
border radius, menu styling. Feeds directly into Stage 3.2 (`theme set-bulk`).

## library-plan.json (produced in Stage 2, not by the crawler)

Standard `vanjaro blocks build-library` plan format — see
`.claude/skills/block-composer/references/plan-format.md`. This file is written
by the skill during Stage 2, not by `vanjaro migrate crawl`.

## page-id-map.json (produced in Stage 4, not by the crawler)

Source URL → Vanjaro page ID, produced by `vanjaro migrate build-id-map`. Used
by `vanjaro migrate verify` and `verify-all` in Stage 6.

```json
{
  "https://example.com/": 35,
  "https://example.com/about": 36,
  "https://example.com/services": 37
}
```
