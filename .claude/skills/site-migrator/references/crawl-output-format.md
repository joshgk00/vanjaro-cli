# Crawl Output Format

The source site crawl produces `artifacts/migration/{site-slug}/` with these files.

## site-inventory.json

Top-level manifest of everything crawled.

```json
{
  "source_url": "https://example.com",
  "crawled_at": "2026-04-08T14:30:00Z",
  "pages": [
    {
      "url": "https://example.com/",
      "title": "Home — Example Co",
      "slug": "home",
      "parent": null,
      "meta_description": "We help businesses grow.",
      "meta_keywords": "consulting, growth, strategy",
      "sections": [
        {
          "type": "hero",
          "pattern": "Centered Hero",
          "content_file": "pages/home/section-1-hero.json"
        },
        {
          "type": "cards",
          "pattern": "Feature Cards (3-up)",
          "content_file": "pages/home/section-2-cards.json"
        }
      ],
      "images": [
        {
          "source_url": "https://example.com/images/hero-bg.jpg",
          "local_file": "assets/hero-bg.jpg",
          "used_in": ["pages/home/section-1-hero.json"]
        }
      ]
    }
  ],
  "global_elements": {
    "header": {
      "type": "global",
      "content_file": "global/header.json"
    },
    "footer": {
      "type": "global",
      "content_file": "global/footer.json"
    }
  },
  "assets": {
    "total": 24,
    "downloaded": 24,
    "failed": 0,
    "manifest": "assets/manifest.json"
  },
  "design_tokens": "design-tokens.json",
  "library_plan": "library-plan.json"
}
```

## design-tokens.json

Same format as `theme-extract-tokens` output. Extracted from the source site's CSS.

See `skills/theme-extract-tokens.md` for the full schema.

## pages/{slug}/section-{n}-{type}.json

Per-section content extracted from the source page. Each file contains the actual text,
image references, and link targets for one section.

```json
{
  "type": "hero",
  "pattern": "Centered Hero",
  "content": {
    "heading_1": "Transform Your Business",
    "text_1": "We deliver innovative solutions that drive measurable growth for companies of all sizes.",
    "button_1": "Get Started",
    "button_1_href": "/contact"
  },
  "images": [
    {
      "role": "background",
      "source_url": "https://example.com/images/hero-bg.jpg",
      "local_file": "assets/hero-bg.jpg",
      "alt": "Team collaboration"
    }
  ]
}
```

## global/header.json and global/footer.json

Navigation and footer content extracted from the source site.

```json
{
  "type": "header",
  "logo": {
    "source_url": "https://example.com/logo.png",
    "local_file": "assets/logo.png",
    "alt": "Example Co"
  },
  "nav_items": [
    {"label": "Home", "href": "/"},
    {"label": "About", "href": "/about"},
    {"label": "Services", "href": "/services"},
    {"label": "Contact", "href": "/contact"}
  ]
}
```

## assets/manifest.json

Maps source URLs to local files and (after upload) to Vanjaro asset URLs.

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

After asset upload (Stage 3), `vanjaro_url` and `vanjaro_file_id` are populated, and
`uploaded` is set to `true`. Content files reference images by `source_url`, which gets
rewritten to `vanjaro_url` during content assembly.

## library-plan.json

Standard `build-library` format — same as `block-composer` output.
See `.claude/skills/block-composer/references/plan-format.md`.
