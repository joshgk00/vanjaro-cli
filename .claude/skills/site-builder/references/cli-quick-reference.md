# CLI Quick Reference for Site Builder

Commands organized by workflow phase. All commands support `--json` for structured output.

## Authentication
```bash
vanjaro auth login --url http://site.local    # Authenticate (creates profile from hostname)
vanjaro auth status                            # Check session
vanjaro api-key generate                       # Generate API key (requires SuperUser)
vanjaro api-key status                         # Check API key
```

## Site Info
```bash
vanjaro site health                            # DNN version, Vanjaro version, connectivity
vanjaro site info                              # Full site analysis
vanjaro site nav                               # Page hierarchy tree
```

## Branding
```bash
vanjaro branding update --site-name "Name" --footer-text "Copyright 2026"
```

## Theme
```bash
vanjaro theme get --json                       # All theme controls
vanjaro theme get --category "Site" --json     # Controls by category
vanjaro theme get --modified --json            # Only changed controls
vanjaro theme set --variable "$var" --value V  # Set one control
vanjaro theme set-bulk file.json               # Batch set controls
vanjaro theme register-font --name N --family F --import-url URL
vanjaro theme list-fonts                       # Available fonts
vanjaro theme reset --force                    # Reset all to defaults
vanjaro theme css get --output portal.css      # Fetch custom CSS
vanjaro theme css update --file custom.css     # Replace custom CSS
vanjaro theme css append --file extra.css      # Append to custom CSS
```

## Pages
```bash
vanjaro pages list                             # All pages
vanjaro pages create --title T --name N [--parent P] [--hidden]
vanjaro pages copy PAGE_ID --title T           # Duplicate page
vanjaro pages delete PAGE_ID --force           # Remove page
vanjaro pages settings PAGE_ID --title T       # Update metadata
vanjaro pages shell PAGE_ID [--fix]            # Audit/fix Vanjaro shell
vanjaro pages seo PAGE_ID                      # View SEO settings
vanjaro pages seo-update PAGE_ID --title T --description D
```

## Content
```bash
vanjaro content get PAGE_ID [--draft|--published] [--output F]
vanjaro content update PAGE_ID --file F        # Push draft (does NOT publish)
vanjaro content publish PAGE_ID                # Make draft live
vanjaro content snapshot PAGE_ID               # Backup current version
vanjaro content rollback PAGE_ID --file F      # Restore from snapshot
vanjaro content diff PAGE_ID                   # Draft vs published comparison
```

## Blocks
```bash
vanjaro blocks scaffold --sections S --output F   # Generate page layout
vanjaro blocks templates [--category C]            # List block templates
vanjaro blocks compose TEMPLATE [--set K=V] [--list-slots] [--output F]
vanjaro blocks build-library --plan F [--dry-run] [--output-dir D]
vanjaro blocks list PAGE_ID                        # Top-level blocks on page
vanjaro blocks tree PAGE_ID                        # Full component tree
vanjaro blocks add PAGE_ID --type T --content C --parent P
vanjaro blocks remove PAGE_ID COMP_ID --force
```

## Custom Blocks
```bash
vanjaro custom-blocks list                     # All custom blocks in sidebar
vanjaro custom-blocks create --name N --category C --file F
vanjaro custom-blocks delete GUID --force
```

## Global Blocks
```bash
vanjaro global-blocks list                     # All global blocks
vanjaro global-blocks get GUID                 # Block detail
vanjaro global-blocks create --name N --category C --file F
vanjaro global-blocks update GUID --file F     # Update content
vanjaro global-blocks publish GUID             # Make live
vanjaro global-blocks delete GUID --force
```

## Assets
```bash
vanjaro assets list [--folder F]               # List uploaded files
vanjaro assets upload FILE [--folder F]        # Upload file to site
```
