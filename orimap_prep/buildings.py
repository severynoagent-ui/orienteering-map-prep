from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from osgeo import ogr

from .util import run

RUIAN_BUILDINGS_SERVICE = "https://ags.cuzk.cz/arcgis/rest/services/RUIAN/Prohlizeci_sluzba_nad_daty_RUIAN/MapServer"
RUIAN_BUILDINGS_LAYER_ID = 3  # StavebniObjekt, esriGeometryPolygon, EPSG:5514


def _envelope_geometry(extent_5514: dict) -> str:
    geom = {
        "xmin": float(extent_5514["minx"]),
        "ymin": float(extent_5514["miny"]),
        "xmax": float(extent_5514["maxx"]),
        "ymax": float(extent_5514["maxy"]),
        "spatialReference": {"wkid": 5514},
    }
    return json.dumps(geom, separators=(",", ":"))


def ruian_buildings_query_url(extent_5514: dict) -> str:
    params = {
        "f": "geojson",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "geometry": _envelope_geometry(extent_5514),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "5514",
        "outSR": "5514",
        "spatialRel": "esriSpatialRelIntersects",
    }
    return f"{RUIAN_BUILDINGS_SERVICE}/{RUIAN_BUILDINGS_LAYER_ID}/query?{urllib.parse.urlencode(params)}"


def _feature_count(path: Path) -> int:
    ds = ogr.Open(str(path))
    if ds is None:
        return 0
    lyr = ds.GetLayer(0)
    count = int(lyr.GetFeatureCount()) if lyr is not None else 0
    ds = None
    return count


def download_ruian_buildings(extent_5514: dict, clip_gpkg: Path, output_gpkg: Path, tmp_dir: Path, target_crs: str, *, logger=None) -> dict:
    """Download RÚIAN StavebniObjekt polygons via ČÚZK ArcGIS REST and clip to AOI."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    raw = tmp_dir / "ruian_buildings_raw.geojson"
    url = ruian_buildings_query_url(extent_5514)
    if logger:
        logger.log("[buildings] Stahuji RÚIAN StavebniObjekt přes ČÚZK REST layer 3")
    with urllib.request.urlopen(url, timeout=120) as response:
        raw.write_bytes(response.read())
    raw_count = _feature_count(raw)
    if output_gpkg.exists():
        output_gpkg.unlink()
    run([
        "ogr2ogr", "-f", "GPKG", str(output_gpkg), str(raw),
        "-nln", "buildings", "-t_srs", target_crs, "-s_srs", "EPSG:5514",
        "-clipsrc", str(clip_gpkg),
    ])
    clipped_count = _feature_count(output_gpkg)
    return {
        "source": "ČÚZK RÚIAN ArcGIS REST",
        "service": RUIAN_BUILDINGS_SERVICE,
        "layer_id": RUIAN_BUILDINGS_LAYER_ID,
        "layer_name": "StavebniObjekt",
        "query_url": url,
        "raw_feature_count": raw_count,
        "clipped_feature_count": clipped_count,
        "output": str(output_gpkg),
        "fallback": "VFR/GDAL-VFR import by municipality is documented as fallback, not used when REST succeeds.",
    }
