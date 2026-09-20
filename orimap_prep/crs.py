from __future__ import annotations
from osgeo import osr

class CrsError(ValueError):
    pass

def validate_crs(crs: str) -> str:
    srs = osr.SpatialReference()
    code = crs.upper().replace('EPSG:', '')
    if not code.isdigit():
        raise CrsError(f"CRS must be EPSG:<number>, got {crs!r}")
    err = srs.ImportFromEPSG(int(code))
    if err != 0:
        raise CrsError(f"PROJ/GDAL cannot import {crs}")
    return f"EPSG:{int(code)}"

def srs_from(crs: str) -> osr.SpatialReference:
    validate_crs(crs)
    s = osr.SpatialReference(); s.ImportFromEPSG(int(crs.split(':')[1])); s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s

def transform_points(points, src_crs='EPSG:4326', dst_crs='EPSG:5514'):
    src=srs_from(src_crs); dst=srs_from(dst_crs)
    tx=osr.CoordinateTransformation(src,dst)
    return [(tx.TransformPoint(x,y)[0], tx.TransformPoint(x,y)[1]) for x,y in points]

def is_projected_metre(crs: str) -> bool:
    s=srs_from(crs)
    return bool(s.IsProjected()) and abs(s.GetLinearUnits()-1.0) < 1e-9
