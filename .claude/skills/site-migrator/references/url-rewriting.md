# URL Rewriting Rules

When migrating content from a source site to Vanjaro, all URLs must be rewritten.

## Image URLs

Source images are downloaded, uploaded to Vanjaro's asset library, and references are
rewritten in content JSON.

| Before | After |
|--------|-------|
| `https://source.com/images/photo.jpg` | `/Portals/0/Images/photo.jpg` |
| `https://cdn.source.com/assets/hero.webp` | `/Portals/0/Images/hero.webp` |
| `data:image/png;base64,...` | `/Portals/0/Images/inline-{hash}.png` |

The exact Vanjaro path comes from the `assets upload` response. Use the asset manifest
to look up the mapping.

## Internal Links

Source site internal links must map to new Vanjaro page URLs.

| Before | After |
|--------|-------|
| `https://source.com/about` | `/about` |
| `https://source.com/services/consulting` | `/services/consulting` |
| `/contact` | `/contact` (relative stays relative) |
| `#section-id` | `#section-id` (anchors stay as-is) |

Build a page URL map from the page creation step:

```json
{
  "https://source.com/": "/",
  "https://source.com/about": "/about",
  "https://source.com/services": "/services",
  "https://source.com/contact": "/contact"
}
```

## External Links

Leave external links unchanged. They point outside the site and should still work.

## Email and Tel Links

Leave `mailto:` and `tel:` links unchanged.

## URL Rewriting Order

1. Download and upload all assets first (populates the asset manifest)
2. Build the page URL map (after all pages are created)
3. Rewrite image `src` attributes using the asset manifest
4. Rewrite internal `href` attributes using the page URL map
5. Leave external links, anchors, mailto, and tel links unchanged
