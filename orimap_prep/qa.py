from __future__ import annotations
from pathlib import Path
import json, subprocess
from osgeo import gdal, ogr
from .util import run

class QAError(RuntimeError): pass

def gdal_info(path: Path):
    ds=gdal.Open(str(path))
    if ds is None: raise QAError(f'Cannot open raster {path}')
    gt=ds.GetGeoTransform(); proj=ds.GetProjection(); band=ds.GetRasterBand(1)
    stats=band.GetStatistics(True, True)
    nodata=band.GetNoDataValue()
    return {'path':str(path),'xsize':ds.RasterXSize,'ysize':ds.RasterYSize,'geotransform':gt,'projection_wkt':proj[:2000],'band1_stats':stats,'nodata':nodata}

def assert_raster_ok(path: Path, min_pixels=16):
    if not path.exists() or path.stat().st_size == 0: raise QAError(f'Missing/empty raster {path}')
    info=gdal_info(path)
    if info['xsize']*info['ysize'] < min_pixels: raise QAError(f'Raster too small {path}: {info["xsize"]}x{info["ysize"]}')
    stats=info['band1_stats']
    if not stats or stats[0] is None or stats[2] == 0: raise QAError(f'Raster has invalid/all-empty stats {path}: {stats}')
    return info

def assert_vector_ok(path: Path, layer_name=None):
    if not path.exists() or path.stat().st_size == 0: raise QAError(f'Missing/empty vector {path}')
    ds=ogr.Open(str(path));
    if ds is None: raise QAError(f'Cannot open vector {path}')
    lyr=ds.GetLayerByName(layer_name) if layer_name else ds.GetLayer(0)
    if lyr is None: raise QAError(f'Missing layer {layer_name or 0} in {path}')
    count=lyr.GetFeatureCount()
    ext=lyr.GetExtent()
    ds=None
    if count <= 0: raise QAError(f'Vector layer empty {path}')
    return {'path':str(path),'feature_count':count,'extent':ext}

def assert_zip_ok(path: Path):
    if not path.exists() or path.stat().st_size < 1024: raise QAError(f'ZIP missing or too small: {path}')
    return {'path':str(path),'size':path.stat().st_size}

def raster_extent_from_info(info: dict) -> dict:
    gt=info['geotransform']; w=info['xsize']; h=info['ysize']
    return {'minx':gt[0], 'maxx':gt[0]+gt[1]*w, 'maxy':gt[3], 'miny':gt[3]+gt[5]*h}

def compare_raster_georef(a: Path, b: Path) -> dict:
    ia=gdal_info(a); ib=gdal_info(b)
    ea=raster_extent_from_info(ia); eb=raster_extent_from_info(ib)
    ix=max(0.0, min(ea['maxx'], eb['maxx']) - max(ea['minx'], eb['minx']))
    iy=max(0.0, min(ea['maxy'], eb['maxy']) - max(ea['miny'], eb['miny']))
    inter=ix*iy
    aa=max(0.0,(ea['maxx']-ea['minx'])*(ea['maxy']-ea['miny']))
    ab=max(0.0,(eb['maxx']-eb['minx'])*(eb['maxy']-eb['miny']))
    g0=ia['geotransform']; g1=ib['geotransform']
    return {
        'a':str(a),'b':str(b),
        'a_size':[ia['xsize'],ia['ysize']], 'b_size':[ib['xsize'],ib['ysize']],
        'a_extent':ea, 'b_extent':eb,
        'intersection_area_m2':inter,
        'overlap_ratio_a': inter/aa if aa else 0,
        'overlap_ratio_b': inter/ab if ab else 0,
        'pixel_size_a':[abs(g0[1]),abs(g0[5])], 'pixel_size_b':[abs(g1[1]),abs(g1[5])],
        'same_pixel_size': abs(abs(g0[1])-abs(g1[1])) < 1e-6 and abs(abs(g0[5])-abs(g1[5])) < 1e-6,
        'same_projection_wkt_prefix': ia['projection_wkt'][:200] == ib['projection_wkt'][:200],
        'origin_delta_m':[g0[0]-g1[0], g0[3]-g1[3]],
    }
