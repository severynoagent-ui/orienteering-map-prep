---
name: orienteering-map-prep
description: "Prepare OpenOrienteering Mapper base-layer packages from GPX areas, optimized for Czech Republic ČÚZK data sources."
version: 1.0.0
author: orienteering-map-prep contributors
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [orienteering, openorienteering, gis, czech-republic, cuzk, gdal, mapping]
    homepage: https://github.com/severynoagent-ui/orienteering-map-prep
---

# orienteering-map-prep Hermes skill

Use this skill when a user sends a GPX boundary and asks for orienteering map base layers, especially for the Czech Republic.

The workflow is optimized for Czech data sources:

- default target CRS: `EPSG:5514` (S-JTSK / Krovak)
- ČÚZK DMR 5G terrain model
- ČÚZK DMP OK surface model
- ČÚZK RGB/CIR orthophoto services
- RÚIAN building polygons
- BGS WMM2025 magnetic declination lookup
- OpenOrienteering Mapper setup and optional `.omap` project generation

Repository: <https://github.com/severynoagent-ui/orienteering-map-prep>

## Required local repository

This skill is an agent instruction wrapper around a local CLI repository. If the repository is not already present, clone it first:

```bash
git clone https://github.com/severynoagent-ui/orienteering-map-prep.git ~/orienteering-map-prep
cd ~/orienteering-map-prep
```

Use the local repository path in all commands. If the user or environment uses a different clone location, adapt paths accordingly.

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
| This skill installed | recommended so the agent maps natural-language OB requests to the right CLI flags |

If Drive upload is not configured, produce and report the local ZIP instead of claiming an upload. If the skill is not installed, the CLI still works but the agent may require explicit command-line instructions.

## Setup checklist for a new machine/profile

1. Install GDAL/PROJ and Python GDAL bindings, for example on Debian/Ubuntu:

   ```bash
   sudo apt update
   sudo apt install -y git python3 python3-gdal gdal-bin proj-bin zip unzip
   ```

2. Clone and test the repository:

   ```bash
   git clone https://github.com/severynoagent-ui/orienteering-map-prep.git ~/orienteering-map-prep
   cd ~/orienteering-map-prep
   /usr/bin/python3 - <<'PY'
   from osgeo import gdal
   print(gdal.VersionInfo('--version'))
   PY
   command -v gdalwarp gdal_translate gdalinfo ogr2ogr ogrinfo
   ./scripts/test_mvp.sh
   ```

3. For large jobs, optionally move outputs/cache to a bigger disk:

   ```bash
   export ORIMAP_PROJECT_ROOT=/data/orimap-projects
   export ORIMAP_CACHE_ROOT=/data/orimap-cache
   ```

4. For Google Drive upload, configure a user-specific compatible helper instead of hardcoding credentials:

   ```bash
   export ORIMAP_GOOGLE_API=/path/to/google_api.py
   export ORIMAP_GOOGLE_SETUP=/path/to/setup.py   # optional auth check
   export ORIMAP_GOOGLE_PY=/path/to/python        # optional helper Python
   ```

Agents must verify outputs (`manifest.json`, ZIP, QA logs, optional `.omap`) before reporting success. If Drive helper variables are missing, do not use `--drive-upload`; report the local ZIP path instead.

## Default interpretation

When the user asks for OB/orienteering base materials from a GPX:

- GPX attachment defines the AOI boundary.
- Default CRS: `EPSG:5514`.
- Default Czech OB products: DEM, hillshade, multidirectional hillshade, contours, slope, RGB orthophoto, CIR orthophoto, RÚIAN buildings, DMP OK, relative surface/vegetation height.
- Forest maps default to 1:10 000 / ISOM 2017-2.
- Sprint maps default to 1:4 000 / ISSprOM 2019.
- Generate `OOM_SETUP.md` by default.
- Generate `.omap` only when the user explicitly asks for an OOM project / OpenOrienteering Mapper file.
- Upload to Drive only if the user asks and a local Drive helper is configured.
- If tiling is requested, use the same grid across products; columns A.. west-east, rows 1.. north-south, suffixes like `_A1`.
- For tiled jobs with many files, prefer uploading the final ZIP unless the user explicitly wants a fully expanded Drive folder.

## Command pattern

```bash
cd ~/orienteering-map-prep
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /absolute/path/to/input.gpx \
  --project-id <safe-id> \
  --prompt "<user request>" \
  --json
```

For sprint with OOM project:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /absolute/path/to/input.gpx \
  --project-id <safe-id> \
  --map-type sprint \
  --map-scale 4000 \
  --map-standard "ISSprOM 2019" \
  --generate-omap \
  --json
```

For Drive upload, only when configured and requested:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /absolute/path/to/input.gpx \
  --project-id <safe-id> \
  --generate-omap \
  --drive-upload \
  --cleanup-local-after-drive \
  --json
```

## Verification before final response

Do not claim success until the command completes and you have verified:

- `manifest.json` exists
- ZIP exists, or Drive upload metadata/links exist when upload was requested
- QA did not report blocking errors
- requested `.omap` exists when requested
- local outputs were deleted only when `--cleanup-local-after-drive` was requested and upload succeeded

## Privacy guidance

Do not publish user GPX files, generated map packages, Google tokens, local paths, or account-specific helper paths. Keep generated outputs out of git; publish only source code, docs, small fixtures, and tests.
