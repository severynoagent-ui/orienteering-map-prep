# DMP OK, surface height and future OB base layers

Last verified: 2026-09-19.

## Implemented: DMP OK and relative surface/vegetation height

### Official source

Primary implemented source:

```text
https://ags.cuzk.gov.cz/arcgis2/rest/services/dmp_obrazova_korelace/ImageServer
```

Short alias also exists and returns equivalent service metadata:

```text
https://ags.cuzk.gov.cz/arcgis2/rest/services/dmp/ImageServer
```

Product name from the service description:

> Digitální model povrchu České republiky z obrazové korelace (DMP OK)

ČÚZK technical report:

```text
https://geoportal.cuzk.gov.cz/Dokumenty/TECHNICKA_ZPRAVA_K_DMP_OK.pdf
```

Report title/date extracted from the PDF:

- `Technická zpráva k Digitálnímu modelu povrchu České republiky z obrazové korelace`
- update/date: January 2026 / issued 2026-01-27
- update note: updated after processing DMP OK from LMS 2025

### Service metadata observed from official ImageServer

- CRS: S-JTSK / Krovak East North, EPSG:5514 (`wkid: 102067`, `latestWkid: 5514`)
- Vertical CRS/model: `Baltic_1957_height`, gravity-related height, metres (`vcsWkid: 8357`)
- Pixel size / mean pixel size: `0.5 m`
- Band count: 1
- Capabilities: `Catalog,Image,Metadata`
- Max export: `maxImageWidth=15000`, `maxImageHeight=4100`
- Copyright: `© ČÚZK`
- Image export endpoint used by pipeline: `/exportImage` with GeoTIFF output

### Technical report notes

The report states that DMP OK is a digital surface model produced from aerial measurement imagery via image correlation. It represents terrain plus natural and human-made objects on it, especially vegetation cover and buildings. It is made from aerial images primarily acquired for Ortofoto ČR. Update periodicity and production zones correspond to Ortofoto ČR: west in odd years, east in even years, overlap annually.

The report also states that DMP is published in S-JTSK/Bpv in SM5 map sheet extents and in ETRS89-TM33N/EVRS in 2 km square tiles. The pipeline uses the public ImageServer export in EPSG:5514/Bpv.

## Pipeline implementation

Products:

```text
dmp
surface_height
vegetation_height
```

Natural language examples:

- `Přidej výšku vegetace.`
- `Připrav kompletní podklady včetně DMP a výšky vegetace.`

Processing steps:

1. Build/read existing project AOI in EPSG:5514 and target CRS.
2. Download DMR 5G DEM as before when needed.
3. Download DMP OK only for the AOI + buffer using ImageServer `exportImage`.
4. Build/clipped `06_vegetation/dmp_ok.tif`.
5. Align DMP exactly to DEM grid:
   - same CRS/projection,
   - same extent,
   - same dimensions,
   - same pixel size,
   - same pixel grid.
6. Resampling: bilinear. This is recorded in `manifest.json -> vegetation_height -> alignment` with original and target grids.
7. Calculate:

```text
surface_height_raw = aligned_DMP_OK - DEM_DMR5G
```

8. Preserve raw continuous output.
9. Create display/helper products:
   - `vegetation_height.tif`: negative values clamped to 0, values >=80 m masked as NoData.
   - `vegetation_height_classified.tif`: default classes below.
10. Run QA/statistics and write all metadata into `manifest.json` and `README.txt`.

Default visualization classes:

| code | height range | label |
|---:|---:|---|
| 1 | 0–0.5 m | near ground |
| 2 | 0.5–2 m | low |
| 3 | 2–5 m | medium |
| 4 | 5–15 m | high |
| 5 | >15 m | very high |

Important interpretation rule: the outputs are relative surface-height helpers. Buildings and other objects can appear as positive height. Do not equate high vegetation height with poor runnability or low height with good runnability.

## Generated files

```text
06_vegetation/dmp_ok.tif
06_vegetation/dmp_ok_aligned_to_dem.tif
06_vegetation/surface_height_raw.tif
06_vegetation/vegetation_height.tif
06_vegetation/vegetation_height_classified.tif
```

## QA stored in manifest

`manifest.json -> vegetation_height` contains:

- DMP source and tile cache records
- original DMP grid
- DEM target grid
- aligned DMP grid
- resampling method and reason
- DEM used
- raster calculator expression
- statistics: min, max, mean, std, p01/p05/p25/p50/p75/p95/p99, negative pixel ratio, NoData ratio, height-ratio buckets
- classification classes/counts
- warnings

## Future layers checked but not implemented yet

### 1. Archivní ortofoto

Official source:

```text
https://geoportal.cuzk.cz/WMS_ORTOFOTO_ARCHIV/WMService.aspx?SERVICE=WMS&REQUEST=GetCapabilities
```

WMS capabilities state it serves archive Ortofoto ČR. Each layer contains one calendar year of aerial photography. Years 1998–2001 are black-and-white, from 2003 color; pixel size 50 cm up to 2008 inclusive, 25 cm from 2009.

Recommendation: high value. Implement as `ortho_archive:<year>` product parameter, not as default.

### 2. DMR 4G

Official ImageServer:

```text
https://ags.cuzk.cz/arcgis2/rest/services/dmr4g/ImageServer
```

Observed CRS and vertical model match the other ČÚZK elevation services: EPSG:5514/Bpv. Useful as a coarser alternative, possibly for regional/MTBO contexts, but DMR 5G remains better for detailed OB contours.

Recommendation: medium priority; implement only if user wants coarser/alternative terrain model.

### 3. Buildings / RÚIAN / INSPIRE Buildings

Official WFS checked:

```text
https://services.cuzk.gov.cz/wfs/inspire-bu-wfs.asp?service=WFS&request=GetCapabilities
```

This is an INSPIRE Buildings download service. It can be used for building masks to reduce false interpretation of DMP-DMR as vegetation in settlements.

Recommendation: high for sprint/urban and for cleaning vegetation-height outputs. Implement as optional vector layer and optional building mask, not default for forest-only jobs.

### 4. OSM roads/paths/topographic vectors

Practical source: Overpass API / OSM extracts. For small AOIs, Overpass can fetch highways, tracks, paths, water, buildings, landuse/forest edges. OSM data quality varies and licensing/attribution must be tracked.

Recommendation: high practical value for OB pre-mapping, especially paths/tracks/water/clearings; implement after stable DMP because it requires tag filtering and QA.

### 5. Digitální technická mapa (DTM)

Useful for sprint/urban maps (detailed technical infrastructure, surfaces, curbs, etc.), but availability/API shape differs by national/regional publication and feature category. Needs a separate focused implementation/research pass before coding.

Recommendation: high potential for sprint maps, but do not mix into current raster terrain workflow yet. Build as separate optional vector workflow later.
