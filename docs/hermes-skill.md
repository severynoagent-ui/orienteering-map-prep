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

## Requirements for the full workflow

A clean Hermes Agent can use this repository, but to reproduce the full end-to-end workflow it must also have:

| Requirement | Needed for |
|---|---|
| Python with GDAL bindings | `/usr/bin/python3` or equivalent must be able to `import osgeo` |
| GDAL/OGR command-line tools | `gdalwarp`, `gdal_translate`, `gdalinfo`, `ogr2ogr`, `ogrinfo` |
| Internet access | ČÚZK data downloads and BGS WMM2025 magnetic-declination lookup |
| Sufficient disk space | intermediate rasters, tiled outputs and ZIP packages |
| Hermes terminal/file tools | cloning the repo, reading files, running commands, verifying outputs |
| Google Drive upload setup | optional; configure a compatible helper through `ORIMAP_GOOGLE_API` for Drive uploads |
| Telegram/WhatsApp or other gateway attachments | optional; needed only when receiving GPX files through messaging platforms |
| This skill/instruction file installed | recommended so the agent maps natural-language Czech OB requests to the right CLI flags |

If Drive upload is not configured, produce and report the local ZIP instead of claiming an upload. If the skill is not installed, the CLI still works but the agent may require explicit command-line instructions.

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
