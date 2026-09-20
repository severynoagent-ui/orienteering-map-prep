# OpenOrienteering Mapper project builder

The `.omap` builder is an optional final stage. The normal GIS package remains the primary output; `.omap` is generated only when `generate_omap=true` / `--generate-omap` or the prompt explicitly asks for an OOM/Mapper project.

## Verified format sources

Checked against the official OpenOrienteering Mapper repository/source on 2026-09-20:

- Repository: `https://github.com/OpenOrienteering/mapper`
- XML namespace used by current bundled `.omap` symbol sets: `http://openorienteering.org/apps/mapper/xml/v2`
- Current official symbol-set `.omap` files inspected:
  - `symbol sets/10000/ISOM 2017-2_10000.omap`
  - `symbol sets/15000/ISOM 2017-2_15000.omap`
  - `symbol sets/4000/ISSprOM 2019_4000.omap`
- Example georeferencing structure inspected from `examples/complete map.omap`.
- Exact CRS/georeferencing serialization verified in OOM 0.9.5 source: `src/core/georeferencing.cpp`, `src/core/georeferencing.h`, `src/core/crs_template_implementation.cpp`, and `src/gui/georeferencing_dialog.cpp`.
- Template path structure inspected from OOM test data and course-design symbol-set files.

The implementation does not generate symbols from an LLM prompt. It copies a bundled official symbol-set `.omap` template and deterministically rewrites only:

- `<georeferencing>`
- `<barrier>/<templates>`
- `<barrier>/<view>/<map_view>/<templates>` visibility/opacity references
- `<barrier>/<parts>/<part>/<objects>` content, which is cleared to `count="0"`

## Symbol set selection

Bundled under `resources/symbol_sets/`:

- forest / 1:10 000: `ISOM 2017-2_10000.omap`
- forest / 1:15 000 or larger: `ISOM 2017-2_15000.omap`
- sprint / 1:4 000 or <= 1:5 000: `ISSprOM 2019_4000.omap`

MTBO remains a future extension because the current bundled fallback does not yet include all MTBO scales in the builder selection table.

## Georeferencing

The generated project uses the job's target CRS, usually `EPSG:5514`, and preserves the CRS identity when the job config provides a known EPSG CRS. For `EPSG:5514`, OOM's native XML representation is:

```xml
<projected_crs id="EPSG">
  <spec language="PROJ.4">+init=epsg:5514</spec>
  <parameter>5514</parameter>
  <ref_point x="..." y="..."/>
</projected_crs>
<geographic_crs id="Geographic coordinates">
  <spec language="PROJ.4">+proj=latlong +datum=WGS84</spec>
  <ref_point_deg lat="..." lon="..."/>
</geographic_crs>
```

Do **not** write `id="EPSG:5514"`; OOM treats that as an unknown/custom CRS id. Do not drop the geographic CRS block; otherwise OOM may display `0°, 0°` until it recalculates state.

The projected CRS reference point is the AOI/project extent centre when available. The geographic reference point is computed with PROJ/pyproj from the projected reference point.

Magnetic declination and grivation are written using OOM's sign/rounding rules:

- `declination` = value stored/entered by OOM/BGS lookup, rounded exactly like OOM (`floor(value*100+0.5)/100`)
- `convergence` = OOM-style grid convergence from `Georeferencing::updateGridCompensation()` sampled around the geographic reference point
- `grivation` = `declination - convergence`, rounded exactly like OOM

## Templates

Only files that actually exist in the project tree are added. Relative paths preserve the package/Drive folder layout. When `--generate-omap` is active, geospatial podklad files are physically renamed before `OOM_SETUP`, `manifest.json`, `.omap`, ZIP, and Drive upload are written, so filenames include source/date labels, for example:

```text
04_ortofoto/ortofoto_current__cuzk_ortofoto_rgb_2025.tif
04_ortofoto/ortofoto_cir__cuzk_ortofoto_cir_2025.tif
02_relief/hillshade__derived_from_cuzk_dmr5g_2009-2013.tif
02_relief/hillshade_multidirectional__derived_from_cuzk_dmr5g_2009-2013.tif
02_relief/slope_oom__derived_from_cuzk_dmr5g_2009-2013.tif
06_vegetation/vegetation_height_oom__derived_2026-09-20_from_cuzk_dmp_ok_and_cuzk_dmr5g_2009-2013.tif
06_vegetation/surface_height_raw_oom__derived_2026-09-20_from_cuzk_dmp_ok_and_cuzk_dmr5g_2009-2013.tif
01_elevation/dem_oom__cuzk_dmr5g_2009-2013.tif
03_contours/contours_5m__derived_from_cuzk_dmr5g_2009-2013.gpkg
03_contours/contours_1m__derived_from_cuzk_dmr5g_2009-2013.gpkg
03_contours/contours_25m__derived_from_cuzk_dmr5g_2009-2013.gpkg
```

All OOM template view references are visible and use `opacity="1"` (100%).

Analytical Float rasters are not attached when an OOM-compatible display raster exists. Template references preserve the files' own georeferencing (`georef="true"`); the builder does not manually reposition or override the source rasters/vectors. Template display names include available data currency, e.g. orthophoto year/month, `DMR5G 2009-2013`, or DMP OK year/label.

## Empty-map invariant

Official OOM symbol-set `.omap` files contain example map objects under `<barrier>/<parts>/<part>/<objects>`. The builder must keep `<symbols>` and color definitions, but clear all actual map objects:

```xml
<parts count="1" current="0">
  <part name="default layer">
    <objects count="0"/>
  </part>
</parts>
```

Symbols are definitions; objects are map content. Regression tests require `symbols > 0`, `templates > 0`, and `object_count = 0`.

## Validation

`validate_omap_project()` checks:

- XML parse succeeds
- root element is map
- georeferencing exists
- EPSG CRS identity is preserved as OOM native `projected_crs id="EPSG"` + `<parameter>code</parameter>` when target CRS is EPSG
- projected reference point and WGS84 `ref_point_deg` exist
- template references exist under the project root
- no absolute `/home/...`, `/tmp/...`, `~/...`, Windows drive-letter paths, or path traversal
- symbol definitions remain present
- map object count is zero

If builder generation fails, the GIS package stays valid and the pipeline records a warning instead of failing the whole job.

## Limitations

- Actual GUI round-trip validation could not be performed on this headless server because `openorienteering-mapper` is not installed and `sudo apt install openorienteering-mapper` requires a password.
- The builder is a conservative XML writer using official symbol-set files, but final visual review in the real Windows OOM application is still recommended after opening `project.omap`.
- Vector GPKG contour templates are linked as GDAL-supported templates. If a specific OOM version refuses GPKG as a template, use `OOM_SETUP.md` as fallback and attach the raster layers first.
