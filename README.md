# orienteering-map-prep

Headless GIS pipeline for preparing OpenOrienteering Mapper base layers from GPX-defined areas. It is **optimized for orienteering mapping in the Czech Republic**: default CRS is S-JTSK / Krovak (`EPSG:5514`) and the implemented data sources are official Czech ČÚZK services (DMR 5G, DMP OK, Ortofoto/CIR, RÚIAN buildings).

## Current status

Implemented and tested on this server:

- GPX boundary validation and polygon creation
- CRS validation through GDAL/PROJ
- default target CRS `EPSG:5514`
- ČÚZK DMR 5G DEM retrieval through the official ArcGIS ImageServer `exportImage` service
- shared tile/cache directory under `~/.cache/orienteering-map-prep/` by default
- DEM clipping/reprojection
- optional single-direction hillshade and default multidirectional hillshade
- configurable contour intervals
- current RGB ortofoto through official ČÚZK WMS/WMTS service
- ČÚZK Ortofoto CIR through official WMS-ORTOCIR yearly layers
- RÚIAN `StavebniObjekt` building polygons through ČÚZK ArcGIS REST, output `05_buildings/buildings.gpkg`
- ČÚZK DMP OK / digital surface model from image correlation
- relative surface-height and vegetation-height helper rasters from `DMP - DEM`
- OOM-compatible `*_oom.tif` Byte RGBA display rasters for analytical Float rasters
- per-project `OOM_SETUP.md` / `OOM_SETUP.txt` start package for OpenOrienteering Mapper
- optional deterministic `project.omap` builder using official OOM symbol-set `.omap` templates
- optional user-facing output tiling/splitting for tablet/mobile use (`--tile-grid`, `--tile-parts`, `--tile-max-side-m`, `--tile-max-mb`) with `_A1`, `_B2` suffixes
- magnetic declination lookup via BGS WMM2025 web service
- QA checks for rasters/vectors/ZIP
- `manifest.json`, `README.txt`, `pipeline.log`, ZIP package
- local outputs by default under `~/orimap-projects/<project-id>/`
- optional upload to Google Drive folder `OB podklady/<job-folder>/` only when requested (`drive` / `Google Drive` / `--drive-upload`)
- 10-day cache pruning script for `~/.cache/orienteering-map-prep/`

The implementation deliberately avoids QGIS GUI. It uses `/usr/bin/python3`, GDAL/OGR CLI tools and Python GDAL bindings (`osgeo`).

## Default job config

```json
{
  "target_crs": "EPSG:5514",
  "map_scale": 10000,
  "map_type": "forest",
  "map_standard": null,
  "contours_m": [1, 5, 25],
  "map_contour_interval": 5,
  "products": ["dem", "hillshade", "hillshade_multidirectional", "contours", "slope", "ortho", "cir_orthophoto", "buildings", "dmp", "surface_height", "vegetation_height"],
  "calculate_declination": true,
  "generate_oom_setup": true,
  "generate_omap": false,
  "buffer_m": 100,
  "dem_pixel_size_m": 1.0
}
```

## Command examples

```bash
cd /path/to/orienteering-map-prep
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /path/to/area.gpx \
  --project-id brdy-test \
  --prompt "Připrav podklady pro OB, EPSG:5514, vrstevnice 1/5/25 m" \
  --json
```

Only DEM + hillshade:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /path/to/area.gpx \
  --project-id brdy-dem \
  --products dem,hillshade \
  --json
```

With ortofoto and slope:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /path/to/area.gpx \
  --project-id brdy-ortho \
  --contours 2.5,5 \
  --products dem,hillshade_multidirectional,contours,slope,ortho \
  --json
```

With RGB ortofoto and CIR ortofoto:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /path/to/area.gpx \
  --project-id brdy-cir \
  --products dem,hillshade_multidirectional,contours,ortho,cir_orthophoto \
  --json
```

Standard OB package plus DMP OK and relative surface/vegetation-height helpers:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /path/to/area.gpx \
  --project-id brdy-veg \
  --drive-folder-name "Brdy vegetace" \
  --products dem,hillshade_multidirectional,contours,ortho,dmp,surface_height,vegetation_height \
  --json
```

Full package with optional OpenOrienteering Mapper project:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx /path/to/area.gpx \
  --project-id brdy-oom \
  --products dem,hillshade_multidirectional,contours,slope,ortho,cir_orthophoto,buildings,dmp,surface_height,vegetation_height \
  --contours 1,5,25 \
  --map-scale 10000 \
  --map-type forest \
  --project-date 2026-09-19 \
  --generate-omap \
  --json
```

Natural-language prompt examples also work:

```text
Přidej výšku vegetace.
Připrav kompletní podklady včetně DMP a výšky vegetace.
Přidej CIR.
Připrav podklady včetně CIR ortofota.
Připrav CIR pro tuto oblast.
Připrav podklady a vytvoř i OOM projekt.
Chci .omap / rovnou Mapper projekt.
Připrav podklady pro lesní mapu 1:10 000.
Připrav sprint 1:4 000.
Vrstevnice podkladů 1, 2.5 a 5 m.
```

## Output layout

Projects are written under:

```text
~/orimap-projects/<project-id>/
```

Typical structure:

```text
00_oblast/input.gpx
00_oblast/area.geojson
00_oblast/area_EPSG5514.gpkg
01_elevation/dem.tif
01_elevation/dem_oom.tif                # display version if DEM is Float
02_relief/hillshade.tif
02_relief/hillshade_multidirectional.tif
02_relief/slope.tif
02_relief/slope_oom.tif                 # if requested and Float
03_contours/contours_1m.gpkg
03_contours/contours_5m.gpkg
03_contours/contours_25m.gpkg
04_ortofoto/ortofoto_current.tif     # RGB ortofoto, if requested
04_ortofoto/ortofoto_cir.tif         # CIR ortofoto, if requested
05_buildings/buildings.gpkg          # RÚIAN StavebniObjekt polygons, if requested
06_vegetation/dmp_ok.tif             # if requested
06_vegetation/dmp_ok_oom.tif
06_vegetation/dmp_ok_aligned_to_dem.tif
06_vegetation/surface_height_raw.tif
06_vegetation/surface_height_raw_oom.tif
06_vegetation/vegetation_height.tif
06_vegetation/vegetation_height_oom.tif
06_vegetation/vegetation_height_classified.tif
OOM_SETUP.md
OOM_SETUP.txt
oom_setup_meta.json
project.omap                              # if --generate-omap or explicit prompt request
logs/pipeline.log
README.txt
manifest.json
```

When tiling is requested, tile copies are written under per-product `tiles/` subfolders, for example:

```text
01_elevation/tiles/dem_A1.tif
02_relief/tiles/hillshade_B2.tif
03_contours/tiles/contours_5m_A1.gpkg
05_buildings/tiles/buildings_C4.gpkg
```

Tile columns run west→east as `A`, `B`, `C`, ... and rows run north→south as `1`, `2`, `3`, ... . The same grid is applied across tileable requested products and recorded in `manifest.json -> tiling`.

Analytical Float rasters are preserved for GIS work. If OOM is likely to reject a Float raster such as `GrayFloat32`, the pipeline creates a separate Byte RGBA `*_oom.tif` display raster with the same georeference.

## OpenOrienteering Mapper setup package

Every job generates `OOM_SETUP.md` and `OOM_SETUP.txt` by default. The file is specific to the project and includes CRS/EPSG values, scale, map type, symbol set recommendation, WMM2025 magnetic declination, grid convergence note, actual template order, opacity starting points, contour/ekvidistance distinction, data currency, map-size estimate and checklist.

Use `--generate-omap` or an explicit prompt such as `vytvoř i OOM projekt` / `chci .omap` to create an optional `<project-id>.omap`. This is not the default. If the prompt supplies a map/area name (`název mapy: ...`, `název oblasti: ...`), that name is used in the safe project folder name and `.omap` filename. The builder copies an official bundled OOM symbol-set `.omap` file, keeps its symbols/colors, clears all example map objects, and deterministically rewrites georeferencing and template references. For `EPSG:5514`, it writes OOM's native EPSG representation (`projected_crs id="EPSG"`, `parameter=5514`, WGS84 `ref_point_deg`) instead of anonymous Custom PROJ.4. Template paths are relative and keep the same structured package layout (`04_ortofoto/...`, `02_relief/...`, `06_vegetation/...`), so the ZIP can be moved to Windows without server paths. Template display names **and the physical template filenames** include available data-currency/source labels such as ČÚZK orthophoto year/month, DMR5G 2009-2013, DMP OK, or derived job date. Tiled outputs can also be included as templates with their `_A1`/`_B2` suffixes. OOM template visibility/opacity is always written as 100% (`opacity="1"`) for every layer.

Generated `.omap` validation checks XML parse, georeferencing/EPSG identity, projected/WGS84 reference point, zero map objects, symbol definitions, missing template links and absence of absolute/path-traversal references. If `project.omap` generation fails, the GIS package remains usable and the pipeline records a warning instead of failing the whole job.

Details and verified sources: `docs/oom_setup_and_compatibility.md` and `docs/oom_project_builder.md`.

A ZIP is created next to the project directory. By default, results stay local in `~/orimap-projects/<project-id>/` and the ZIP next to it. Upload to Google Drive only when the user asks for `drive` / `Google Drive` or when `--drive-upload` is set. Local outputs are kept by default even after Drive upload; delete them only with `--cleanup-local-after-drive`.

## Google Drive output

Drive upload is opt-in and intentionally adapter-based. Public users must provide a compatible helper through `ORIMAP_GOOGLE_API`; otherwise keep runs local and upload the generated ZIP manually.

When Drive upload is requested:

1. Find or create root folder `OB podklady` in My Drive.
2. Always create a new child folder for the job.
3. Upload the project tree (`00_oblast`, `01_elevation`, `02_relief`, `03_contours`, `04_ortofoto`, `05_buildings`, `06_vegetation`, `README.txt`, `manifest.json`, logs) and the ZIP.
4. Upload `drive_upload.json` with Drive IDs/links.
5. Keep local project directory and ZIP unless `--cleanup-local-after-drive` is set.

Control flags:

```bash
--drive-folder-name "Brdy sever 2026"   # human folder name under OB podklady
--drive-root-folder "OB podklady"       # default root folder
--drive-upload                          # upload to Drive
--cleanup-local-after-drive             # optional: delete local outputs after successful Drive upload
--no-drive-upload                       # force local-only run/test
```

Cache/source downloads under `~/.cache/orienteering-map-prep/` are not deleted immediately; prune them with `scripts/prune_gis_cache.py`.

## Data sources

See `docs/cuzk_sources.md` for verified endpoint notes.

MVP terrain source:

- ČÚZK DMR 5G ArcGIS ImageServer
- Endpoint: `https://ags.cuzk.cz/arcgis2/rest/services/dmr5g/ImageServer`
- Export operation: `exportImage`
- Retrieved as GeoTIFF, EPSG:5514, Float32 elevation

Optional current orthophoto:

- ČÚZK Ortofoto WMS/WMTS
- WMS: `https://ags.cuzk.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer?`
- WMTS capabilities: `https://ags.cuzk.cz/arcgis1/rest/services/ORTOFOTO/MapServer/WMTS/1.0.0/WMTSCapabilities.xml`

Optional CIR orthophoto:

- ČÚZK WMS-ORTOCIR / Ortofoto CIR
- WMS capabilities: `https://geoportal.cuzk.cz/WMS_ORTOFOTO_CIR/WMService.aspx?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0`
- Product metadata: `https://geoportal.cuzk.gov.cz/Default.aspx?mode=TextMeta&side=ortofoto&metadataID=CZ-CUZK-ORTOCIR-R&productid=63416&menu=235`
- Public WMS advertises yearly layers `2010`–`2025`; the pipeline selects the newest layer whose geographic bbox intersects the AOI.
- Product metadata advertises JP2/SM5 distribution and approx. 0.20 m source pixels since 2018, but public machine-readable direct JP2/ATOM download for CIR was not verified; the implemented backend uses the official WMS service, caches bbox GeoTIFF exports, and clips to the project polygon.
- Output `04_ortofoto/ortofoto_cir.tif` is Byte RGBA GeoTIFF with alpha outside the cutline and is treated as OOM-compatible directly.

Optional RÚIAN buildings:

- ČÚZK RÚIAN ArcGIS REST MapServer: `https://ags.cuzk.cz/arcgis/rest/services/RUIAN/Prohlizeci_sluzba_nad_daty_RUIAN/MapServer`
- Layer `3` = `StavebniObjekt`, polygon geometry in EPSG:5514, query supports GeoJSON.
- Primary backend queries layer `3` by AOI envelope, clips to the GPX polygon, and writes `05_buildings/buildings.gpkg`.
- Fallback design: municipality VFR download/import through GDAL-VFR, matching the QGIS RÚIAN plugin approach, if REST is unavailable.

Optional DMP OK / surface-height:

- ČÚZK DMP OK ImageServer: `https://ags.cuzk.gov.cz/arcgis2/rest/services/dmp_obrazova_korelace/ImageServer`
- Product: `Digitální model povrchu České republiky z obrazové korelace (DMP OK)`
- CRS/height: EPSG:5514 + Baltic/Bpv heights in metres
- Mean pixel size: 0.5 m
- Derived expression: `surface_height_raw = aligned_DMP_OK - DEM_DMR5G`
- Details: `docs/dmp_vegetation_and_next_layers.md`

Archive orthophoto endpoint is verified in docs but not yet exposed as a CLI product.

Magnetic declination / OOM setup sources:

- BGS WMM2025 JSON service: `https://geomag.bgs.ac.uk/web_service/GMModels/wmm/2025/`
- OOM templates manual: `https://www.openorienteering.org/mapper-manual/pages/templates.html`
- OOM georeferencing manual: `https://www.openorienteering.org/mapper-manual/pages/georeferencing.html`
- OOM app features: `https://www.openorienteering.org/apps/mapper/`
- IOF O-Map Wiki: `https://omapwiki.orienteering.sport/`

## QA

The pipeline checks:

- GPX has usable boundary geometry
- target CRS imports through GDAL/PROJ
- output vectors are non-empty
- output rasters open with GDAL, have dimensions, stats and non-empty values
- contour outputs contain features
- ZIP exists and is not empty

Exit code 0 is not treated as sufficient by itself; QA exceptions fail the job.

## Tested commands

MVP DEM/hillshade/contours:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx tests/fixtures_rajec_tiny.gpx \
  --project-id test-rajec-tiny-v2 \
  --contours 5,25 \
  --products dem,hillshade_multidirectional,contours,ortho \
  --json
```

Optional ortofoto:

```bash
/usr/bin/python3 -m orimap_prep.cli \
  --input-gpx tests/fixtures_rajec_tiny.gpx \
  --project-id test-rajec-ortho-v1 \
  --contours 25 \
  --products dem,hillshade_multidirectional,contours,ortho \
  --json
```

## Known limitations

- GPX boundary must be closed, unless `--close-open` is intentionally supplied.
- DMR 5G ATOM/LAZ backend is not implemented yet; source module boundary is ready for it.
- Current ortofoto is implemented; archive ortofoto is verified but not yet parameterized.
- Large areas can be split/tiled with `--tile-grid COLSxROWS`, `--tile-parts N`, `--tile-max-side-m M`, or `--tile-max-mb MB`; verify `manifest.json -> tiling` for exact grid and any size warnings.
- No QGIS GUI automation is used; QGIS Processing is not required for current MVP.
