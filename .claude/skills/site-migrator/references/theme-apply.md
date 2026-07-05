# Theme Apply — mapping design tokens to Vanjaro theme controls

Applies `design-tokens.json` (from `vanjaro migrate crawl`) to the target
site's theme. Theme controls are LESS variables set in bulk; the server
recompiles the theme SCSS on save.

## Workflow

1. **Enumerate the live controls** (the variable names are discoverable, not
   memorized — the active theme exposes ~800+):

   ```bash
   vanjaro theme get --json
   ```

   Payload: `{theme_name, controls[], available_fonts[], total}`. Each control
   carries `lessVariable`, `title`, `type`, `category`, `currentValue`.
   Filter by `category` to find what you need.

2. **Build a set-bulk file** mapping the crawl's design tokens onto variables:

   ```json
   [
     {"lessVariable": "$primarycolor", "value": "#bc302f"},
     {"lessVariable": "$siteFontFamily", "value": "Poppins, sans-serif"}
   ]
   ```

3. **Apply and verify**:

   ```bash
   vanjaro theme set-bulk --file theme-settings.json
   vanjaro theme palette-export --json   # confirm the palette round-trips
   ```

## Key categories and variables

| Category | Count | What lives there |
|----------|-------|------------------|
| `Site` | 12 | Global palette + site font + border radius (see below) |
| `Styles: Heading` | 120 | Per-level heading styles (`$hsoneFontFamily`, `$hstwoFontFamily`, `$hsThreeFontFamily` … per h1–h6 + display sizes) |
| `Styles: Text` | 120 | Paragraph styles (`$psoneFontFamily`, …) |
| `Styles: Button` | 130 | Button styles per variant |
| `Styles: Menu` | 170 | Nav/menu typography and colors |
| `Link` | 21 | `$linkNormalFontFamily`, hover/active variants |

`Site` category variables (complete list): `$primarycolor`, `$secondarycolor`,
`$tertiary`, `$quaternary`, `$successcolor`, `$infocolor`, `$warningcolor`,
`$dangercolor`, `$lightcolor`, `$darkcolor`, `$siteFontFamily`,
`$siteBorderRadius`.

A typical migration maps: source palette → the `Site` color variables; body
font → `$siteFontFamily` (+ `Styles: Text`/`Button`/`Menu` font families when
the source differentiates); heading font → the `Styles: Heading` font-family
variables per level.

## Fonts

`available_fonts` in the `theme get` payload lists what's installable by name.
For fonts not in the list, see `vanjaro theme --help` for registration
commands before referencing them in a set-bulk file.

## Gotchas

- Values are raw CSS strings — include the full font stack, not just a name.
- `theme set-bulk` reports the applied count; a count lower than your file's
  entry count means unknown `lessVariable` names were skipped — re-check them
  against `theme get`.
- On a SHARED portal the theme is portal-global: applying a migration's theme
  restyles every other site on that portal. Expected on a dedicated target;
  call it out explicitly when the portal is shared.
