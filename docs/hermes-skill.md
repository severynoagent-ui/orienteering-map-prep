# Hermes skill: orienteering-map-prep

This repository can be wrapped as a Hermes Agent skill for preparing orienteering map source packages from GPX-defined areas.

## Intended public use

Use this skill when a user sends a GPX boundary and asks for base layers for an orienteering map, especially in the Czech Republic.

The workflow is optimized for Czech data sources:

- target CRS `EPSG:5514` by default
- ČÚZK DMR 5G terrain model
- ČÚZK DMP OK surface model
- ČÚZK RGB/CIR orthophoto services
- RÚIAN building polygons
- OpenOrienteering Mapper setup and optional `.omap` project generation

## Minimal skill instructions

```markdown
Use the local repository `orienteering-map-prep` to generate headless GIS packages for OpenOrienteering Mapper.

Default interpretation:
- GPX attachment defines the AOI boundary.
- Default CRS: EPSG:5514.
- Default Czech OB products: DEM, hillshade, multidirectional hillshade, contours, slope, RGB orthophoto, CIR orthophoto, RÚIAN buildings, DMP OK, relative surface/vegetation height.
- Forest maps default to 1:10 000 / ISOM 2017-2.
- Sprint maps default to 1:4 000 / ISSprOM 2019.
- Generate `OOM_SETUP.md` by default.
- Generate `.omap` only when the user explicitly asks for an OOM project / OpenOrienteering Mapper file.
- Upload to Drive only if the user asks and a local Drive helper is configured.
- If tiling is requested, use the same grid across products; columns A.. west-east, rows 1.. north-south, suffixes like `_A1`.

Run:

```bash
cd /path/to/orienteering-map-prep
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /absolute/path/to/input.gpx \
  --project-id <safe-id> \
  --prompt "<user request>" \
  --json
```

Important: do not claim success until the command completes, QA passes, and the ZIP/manifest exist.
```

## Privacy guidance for agents

Do not publish user GPX files, generated map packages, Google tokens, local paths, or account-specific helper paths. Keep generated outputs out of git; publish only source code, docs, small fixtures, and tests.
