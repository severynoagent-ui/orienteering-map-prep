# ČÚZK source notes

## dmr5g
- URL: https://ags.cuzk.cz/arcgis2/rest/services/dmr5g/ImageServer?f=pjson
- HTTP: 200
- Content-Type: text/plain; charset=UTF-8
- Description: Digitální model reliefu České republiky 5. generace (DMR 5G) představuje zobrazení přirozeného nebo lidskou činností upraveného zemského povrchu v digitálním tvaru ve formě výšek diskrétních bodů v nepravidelné trojúhelníkové síti (TIN) bodů o souřadnicích X,Y,H, kde H reprezentuje nadmořskou výšku ve výškovém referenčním systému Balt po vyrovnání (Bpv) s úplnou střední chybou výšky 0,18 m v odkrytém terénu a 0,3 m v zalesněném terénu. Model vznikl z dat pořízených metodou leteckého laserového s
- Pixel size: 2 x 2
- Spatial reference: `{'latestVcsWkid': 8357, 'latestWkid': 5514, 'wkid': 102067, 'vcsWkid': 8357}`

## ortofoto_wmts
- URL: https://ags.cuzk.cz/arcgis1/rest/services/ORTOFOTO/MapServer/WMTS/1.0.0/WMTSCapabilities.xml
- HTTP: 200
- Content-Type: text/xml; charset=utf-8
- First advertised layers/identifiers: ORTOFOTO, default, default028mm, 0, 1, 2, 3, 4, 5, 6

## ortofoto_wms
- URL: https://ags.cuzk.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer?SERVICE=WMS&REQUEST=GetCapabilities
- HTTP: 200
- Content-Type: text/xml
- First advertised layers/identifiers: 0, default

## ortoarchiv_wms
- URL: https://geoportal.cuzk.cz/WMS_ORTOFOTO_ARCHIV/WMService.aspx?SERVICE=WMS&REQUEST=GetCapabilities
- HTTP: 200
- Content-Type: text/xml
- First advertised layers/identifiers: WMS, 1998, default, 1999, default, 2000, default, 2001, default, 2002

## dmr5g_atom_metadata
- URL: https://geoportal.cuzk.cz/Default.aspx?mode=TextMeta&metadataXSL=full&side=WFS.ATOM_OSTATNI&metadataID=CZ-CUZK-ATOM-DMR5G-SJTSK
- HTTP: 200
- Content-Type: text/html; charset=utf-8

MVP uses the official ČÚZK DMR 5G ArcGIS ImageServer `exportImage` endpoint to retrieve only the project bbox+buffer as GeoTIFF in EPSG:5514. ATOM/LAZ support is documented as a future backend; the pipeline has cache/source module boundaries for adding it without changing the CLI. Ortofoto phase uses official ČÚZK WMS/WMTS endpoints and GDAL WMS for small clipped rasters.

## ortofoto_cir_wms
- URL: https://geoportal.cuzk.cz/WMS_ORTOFOTO_CIR/WMService.aspx?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0
- HTTP: 200
- Content-Type: text/xml
- Service title: Prohlížecí služba WMS – Ortofoto CIR
- Public WMS yearly layers currently advertised: 2010–2025
- Supported CRS includes EPSG:5514.
- Implemented backend: select newest yearly layer whose `EX_GeographicBoundingBox` intersects the AOI lon/lat extent, download bbox through GDAL WMS as RGB GeoTIFF, cache it under `~/.cache/orienteering-map-prep/cuzk/ortofoto_cir_wms/`, then `gdalwarp -cutline -crop_to_cutline -dstalpha` to `04_ortofoto/ortofoto_cir.tif`.
- Product metadata page: https://geoportal.cuzk.gov.cz/Default.aspx?mode=TextMeta&side=ortofoto&metadataID=CZ-CUZK-ORTOCIR-R&productid=63416&menu=235
- Product metadata verified 2026-09-19: name `Ortofoto CIR`, free of charge, distribution unit SM5 ~2.5×2 km, format JP2, CRS S-JTSK / Krovak East North, source pixel since 2018 approx. 0.20 m, last product update 2026-06-01 / information revision 2026-09-14.
- Public direct JP2/ATOM endpoint for CIR was not verified; product page exposes data via request (`žádost`). Do not invent a JP2 URL.
