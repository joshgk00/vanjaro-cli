# Theme Site Comparison

Generated: 2026-04-06 06:59:36

Baseline URL: http://vanjarobaseline.local/Test-Page
Current URL: http://vanjarocli.local/VGRT-Home

## Theme Files

| Path | Exists | Length | LastWriteTime | Hash |
| --- | --- | --- | --- | --- |
| C:\Code\vanjaro-ai\website\Portals\0\vThemes\Basic\Theme.css | True | 292552 | 2026-04-02 20:11:39 | 3B8665229023894B195522423C536749F790557F4B2A53AE1A2071F72B77D629 |
| C:\Websites\vanjarobaseline\Website\Portals\0\vThemes\Basic\Theme.css | True | 291622 | 2026-04-06 06:51:57 | 371AFCD28D7C8036B4A05E7D9B7CA9DDCF79CB096CB492EE0AE937AE19FA4B5C |
| C:\Websites\vanjarocli\Website\Portals\0\vThemes\Basic\Theme.css | True | 292558 | 2026-04-06 06:24:36 | 4D9602BD29FD09DE7F362E6A414FFC521F3B1E28A6E62A9E33FD363FF527F52E |
| C:\Code\vanjaro-ai\website\Portals\0\vThemes\Basic\Theme.scss | True | 123085 | 2026-03-16 20:19:08 | 7A960520DC2E96F1EF0A1DD369E0ED35E1F8C50F4F17CE8496C8D59C096A6159 |
| C:\Websites\vanjarobaseline\Website\Portals\0\vThemes\Basic\Theme.scss | True | 122052 | 2026-04-06 06:51:57 | 0258956D939B41596CA5350C843336CE3747871D14F4EC671A6360602B7EE203 |
| C:\Websites\vanjarocli\Website\Portals\0\vThemes\Basic\Theme.scss | True | 122896 | 2026-04-06 06:24:35 | B8A6772E265642FFC7DB84957A625E20CC6C274B49F289A2FEFFD145F852C3F1 |
| C:\Websites\vanjarobaseline\Website\Portals\0\vThemes\Basic\theme.editor.js | False |  |  |  |
| C:\Websites\vanjarocli\Website\Portals\0\vThemes\Basic\theme.editor.js | False |  |  |  |

## Portal Summary

### Baseline DB ($BaselineDb)
```text
PortalID|GUID|CreatedOnDate|LastModifiedOnDate
--------|----|-------------|------------------
0|44E026A1-90C6-4718-8F0D-449F1CCA1C61|2026-04-06 06:31:28.890|2026-04-06 06:49:20.190
```

### Current DB ($CurrentDb)
```text
PortalID|GUID|CreatedOnDate|LastModifiedOnDate
--------|----|-------------|------------------
0|5CE6579B-5247-4189-9209-B435AFC7F63D|2026-04-02 08:10:49.273|2026-04-02 08:16:35.467
```

## Tab Shell Summary

### Baseline
```text
TabID|TabName| | 
-----|-------|-|-
21|Home|[G]Skins/Xcillion/Home.ascx|
33|Signin|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
34|Test Page|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
```

### Current
```text
TabID|TabName| | 
-----|-------|-|-
21|Home|[G]Skins/Xcillion/Home.ascx|
33|Signin|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
34|About Us|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
35|VGRT Home|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
36|About Nancy|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
37|Services|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
38|Coaching|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
39|Contact|[g]skins/vanjaro/base.ascx|[g]containers/vanjaro/base.ascx
```

## Baseline Theme JSON

| CategoryGuid | Count | Length | Hash |
| --- | --- | --- | --- |
| 921af5fa-3030-4bae-aaec-0e353b9489ff | 1143 | 71410 | 2D5660FEF6CBDAEB3B4480008F3BB2377D4DCB780D35444537C0D09766CE1483 |
| be134fd2-3a3d-4460-8ee9-2953722a5ab2 | 0 | 0 | E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855 |

## Current Theme JSON

| CategoryGuid | Count | Length | Hash |
| --- | --- | --- | --- |
| 921af5fa-3030-4bae-aaec-0e353b9489ff | 1143 | 71339 | 743C7B856A84FDB549A1DE40D950342A519797F58683AEAD754BE62D9DE3FC3A |
| be134fd2-3a3d-4460-8ee9-2953722a5ab2 | 0 | 2 | 4F53CDA18C2BAA0C0354BB5F9A3ECBE5ED12AB4D8E11BA873C2F11161202B945 |

## Published Bundles

### Baseline
```text
4efed7f5a054f8c8a43265e606bd965f version 44
Map: C:\Websites\vanjarobaseline\Website\App_Data\ClientDependency\JOSH-PC-7f959a40e635d90a45f0ab7de1d881c7-map.xml
```

### Current
```text
a11762ae99635938b97ea22874659425 version 93
Map: C:\Websites\vanjarocli\Website\App_Data\ClientDependency\JOSH-PC-bbd4d0441b03bf5acac1318b40122d87-map.xml
```

## Follow-up Baseline AI Check

After this report was generated, the fresh baseline site was exercised through the updated CLI and AI package:

- `vanjaro theme set --guid fe5745d2-d4db-48bb-8f0c-3a7c37a3d0a3 --value "#00aa55"`
- then reverted back to `#262323`

Observed follow-up results on `http://vanjarobaseline.local/Test-Page`:

- `theme.json` updated with the requested `Primary` value
- `Theme.scss` updated with the new `$primarycolor`
- `Theme.css` updated with resolved `#00aa55`
- the published bundle rolled forward to:
  - `e6144b652673637620070207751784e6 version 45`
- after reverting, it rolled forward again to:
  - `3b1d509725c0cc919623b55928033563 version 46`

This follow-up matters because it shows the fresh baseline does not reproduce the contaminated site's "AI save always breaks the theme" behavior. On the clean site, the AI path updates files and advances ClientDependency as expected.

