# OpenOrienteering Mapper setup package and raster compatibility

Last verified: 2026-09-19.

## Official OOM documentation checked

- Templates: https://www.openorienteering.org/mapper-manual/pages/templates.html
- Georeferencing: https://www.openorienteering.org/mapper-manual/pages/georeferencing.html
- App feature page: https://www.openorienteering.org/apps/mapper/

Key verified points:

- Templates are managed through `Templates > Template Setup Window`.
- OOM supports raster images including GDAL-backed formats, world files and GeoTIFF.
- Georeferencing is configured through `Map > Georeferencing…`.
- OOM supports EPSG coordinate reference systems and uses PROJ.
- In OOM georeferencing, `Declination` is the angle between true north and magnetic north.
- OOM documentation describes `Grivation` as a rotation composed of magnetic declination and grid convergence.
- Therefore this pipeline reports magnetic declination and grid convergence separately, and tells the user not to manually add grid convergence to declination.

## IOF / symbol set information checked

Official/current references checked:

- IOF O-Map Wiki specifications: https://omapwiki.orienteering.sport/
- ISOM 2017-2: https://omapwiki.orienteering.sport/specifications/isom/
- ISSprOM 2019-2: https://omapwiki.orienteering.sport/specifications/issprom/
- IOF mapping page: https://orienteering.sport/iof/mapping/
- OOM feature page: https://www.openorienteering.org/apps/mapper/

Observed current defaults:

- Forest/foot orienteering: ISOM 2017-2.
- Sprint: ISSprOM 2019-2.
- MTBO: ISMTBOM 2022 / current OOM MTBO symbol set.

The generator marks symbol sets as recommendations unless the user explicitly provides `map_standard`.

## Magnetic declination source

Implemented source:

```text
https://geomag.bgs.ac.uk/web_service/GMModels/wmm/2025/
```

This is the British Geological Survey World Magnetic Model 2025 web service. WMM is jointly developed by NOAA/NCEI and BGS. NOAA's public calculator endpoint currently requires an API key, so the pipeline uses the BGS JSON web service.

Parameters:

- latitude: AOI centroid WGS84 latitude
- longitude: AOI centroid WGS84 longitude
- altitude: `0 km`
- date: project date (`project_date`) or job date
- model revision: WMM2025

The pipeline stores:

- east-positive declination in degrees,
- E/W display direction,
- date,
- calculation coordinates,
- source/model,
- raw service response.

## OOM-compatible display rasters

OpenOrienteering Mapper may reject working rasters such as Float32 single-band GeoTIFFs with an error like:

```text
Unsupported raster data: GrayFloat32
Cannot read image data
```

The pipeline now keeps both forms:

1. Analytical raster, e.g. `vegetation_height.tif`
   - Float32
   - true values in metres
   - for GIS analysis and further calculations
2. OOM display raster, e.g. `vegetation_height_oom.tif`
   - Byte RGBA GeoTIFF
   - intended for direct use as an OOM image template
   - same CRS, geotransform, pixel size, dimensions and extent as the source raster

The compatibility check runs for generated `.tif` outputs. If a raster is not already Byte gray/RGB/RGBA, an `*_oom.tif` display raster is created and the relationship is recorded in `manifest.json -> oom_display_rasters`.

## Vegetation height visualization

`vegetation_height.tif` remains the authoritative analytical raster. `vegetation_height_oom.tif` is a classified visualization:

| Height interval | RGBA |
|---|---|
| 0–0.5 m | `[235,245,210,255]` |
| 0.5–2 m | `[185,225,130,255]` |
| 2–5 m | `[105,190,85,255]` |
| 5–10 m | `[45,150,55,255]` |
| 10–20 m | `[10,105,35,255]` |
| 20+ m | `[0,60,20,255]` |
| NoData / invalid | transparent alpha 0 |

The classes are deliberately semantic, not a simple 0–255 stretch.

## Generated OOM files

For each project, unless disabled with `--no-oom-setup`, the pipeline writes:

```text
OOM_SETUP.md
OOM_SETUP.txt
oom_setup_meta.json
```

The setup file contains:

- project profile,
- CRS / EPSG recommendation,
- map scale,
- map type and symbol set recommendation,
- distinction between GIS contours and final cartographic contour interval,
- magnetic declination from WMM2025,
- grid convergence note,
- actual template list using only files that exist,
- template order and opacity starting points,
- template presets,
- data currency table,
- physical map-size estimate,
- checklist.

## .omap automation status

The pipeline does not currently generate `project.omap`.

Reason: OOM `.omap` is a map file format and can technically store georeferencing/templates, but a stable, official headless CLI/API for creating a full project with selected symbol set, template positioning, visibility and map north settings was not confirmed. Generating `.omap` by editing internal XML directly would be brittle. Keep `OOM_SETUP.md` as the reliable output until a dedicated `.omap` implementation is tested against the target OOM version.
