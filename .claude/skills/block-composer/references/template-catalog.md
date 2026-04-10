# Block Template Catalog

Available templates in `artifacts/block-templates/`. These are the building blocks the agent maps design patterns to.

## Heroes

| Template | File | Description |
|----------|------|-------------|
| Centered Hero | `Heroes/centered-hero.json` | Full-width hero with centered heading, subtext, and CTA button |
| Split Hero | `Heroes/split-hero.json` | Two-column hero: text + CTA on left, image on right |

## Cards

| Template | File | Description |
|----------|------|-------------|
| Feature Cards (3-up) | `Cards/feature-cards-3up.json` | Three equal-width cards with icon, heading, text, and button |
| Feature Cards (4-up) | `Cards/feature-cards-4up.json` | Four equal-width cards with icon, heading, text, and button |
| Testimonial Cards (3-up) | `Cards/testimonial-cards-3up.json` | Three quote cards with testimonial text, author name, and role |
| Pricing Cards (3-up) | `Cards/pricing-cards-3up.json` | Three pricing tier cards with price, feature list, and CTA |
| Blog Post Cards (3-up) | `Cards/blog-post-cards-3up.json` | Three blog post cards with image, category tag, heading, excerpt, and read more link |
| Team Member Grid (4-up) | `Cards/team-member-grid-4up.json` | Four team member cards with photo, name, role, and short bio |
| Gallery (3-up) | `Cards/gallery-3up.json` | Three-column image gallery with caption + category — for portfolios, project showcases, visual indices |
| Gallery (6-up) | `Cards/gallery-6up.json` | Six-column (3x2) image gallery with caption + category — for larger portfolios and showcases |

## CTAs

| Template | File | Description |
|----------|------|-------------|
| CTA Banner | `CTAs/cta-banner.json` | Full-width centered call-to-action with heading, text, and button |
| CTA Split | `CTAs/cta-split.json` | Two-column CTA: text on left, button on right |

## Content

| Template | File | Description |
|----------|------|-------------|
| Bio/About | `Content/bio-about.json` | Two-column: image on left, bio text + heading on right |
| Contact Section | `Content/contact-section.json` | Two-column: contact info on left, form placeholder on right |
| Logo Bar | `Content/logo-bar.json` | Horizontal row of partner or client logos with optional section heading |
| FAQ Accordion | `Content/faq-accordion.json` | Five Q&A pairs with section heading — for FAQ pages, knowledge bases, support sections |
| Stats Grid (4-up) | `Content/stats-grid-4up.json` | Four-column stats with large numbers and labels — for impact metrics, company stats, achievements |

## Lists

| Template | File | Description |
|----------|------|-------------|
| Icon Feature List | `Lists/icon-feature-list.json` | Vertical list of icon + heading + text rows |

## Navigation

| Template | File | Description |
|----------|------|-------------|
| Footer (3-column) | `Navigation/footer-3col.json` | Three-column footer with nav links, contact info, and social |

## Template Capabilities

Each template supports content overrides via named slots:
- `heading_1`, `heading_2`, etc. — heading text
- `text_1`, `text_2`, etc. — paragraph text
- `button_1`, `button_2`, etc. — button labels
- `button_1_href`, etc. — button link targets
- `image_1_src`, `image_1_alt`, etc. — image sources and alt text

Use `vanjaro blocks compose <template> --list-slots` to see all available slots for a template.

## When No Template Fits

If a design section doesn't match any template:
1. Check if a template can be adapted with overrides (e.g., different heading style)
2. Check if a template with fewer/more columns covers the pattern
3. If truly novel, flag it for custom template creation using the `block-template-author` skill
