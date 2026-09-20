from __future__ import annotations
from pathlib import Path
from osgeo import gdal
import numpy as np
from .util import ensure_dir, sha256

FLOAT_TYPES = {gdal.GDT_Float32, gdal.GDT_Float64, gdal.GDT_CFloat32, gdal.GDT_CFloat64}
OOM_SAFE_BYTE_TYPES = {gdal.GDT_Byte}
NODATA_ALPHA = 0
OPAQUE = 255

class OOMCompatError(RuntimeError):
    pass

def raster_summary(path: Path) -> dict:
    ds = gdal.Open(str(path))
    if ds is None:
        raise OOMCompatError(f"Cannot open raster {path}")
    gt = ds.GetGeoTransform()
    bands=[]
    for i in range(1, ds.RasterCount+1):
        b=ds.GetRasterBand(i)
        bands.append({
            'band': i,
            'data_type': gdal.GetDataTypeName(b.DataType),
            'color_interp': gdal.GetColorInterpretationName(b.GetColorInterpretation()),
            'nodata': b.GetNoDataValue(),
        })
    return {
        'path': str(path),
        'xsize': ds.RasterXSize,
        'ysize': ds.RasterYSize,
        'band_count': ds.RasterCount,
        'bands': bands,
        'geotransform': list(gt),
        'pixel_size': [abs(gt[1]), abs(gt[5])],
        'extent': {'minx':gt[0], 'maxy':gt[3], 'maxx':gt[0]+gt[1]*ds.RasterXSize, 'miny':gt[3]+gt[5]*ds.RasterYSize},
        'projection_wkt': ds.GetProjection()[:2000],
    }

def is_probably_oom_safe_raster(path: Path) -> tuple[bool, str]:
    ds = gdal.Open(str(path))
    if ds is None:
        return False, 'cannot_open'
    if ds.RasterCount in (3,4) and all(ds.GetRasterBand(i).DataType == gdal.GDT_Byte for i in range(1, ds.RasterCount+1)):
        return True, 'byte_rgb_or_rgba'
    if ds.RasterCount == 1 and ds.GetRasterBand(1).DataType == gdal.GDT_Byte:
        return True, 'byte_gray_or_palette'
    return False, f"{ds.RasterCount} bands / {gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)}"

def _valid_mask(arr, nodata):
    m = np.isfinite(arr)
    if nodata is not None:
        m &= arr != nodata
    return m

def _percentile_scale(values, lo=2, hi=98):
    if values.size == 0:
        return 0.0, 1.0
    a,b=np.percentile(values.astype('float64'), [lo,hi])
    if not np.isfinite(a) or not np.isfinite(b) or abs(b-a) < 1e-9:
        a=float(np.nanmin(values)); b=float(np.nanmax(values))
    if abs(b-a) < 1e-9:
        b=a+1.0
    return float(a), float(b)

def _rgba_from_continuous(arr, valid, *, low=None, high=None, cmap='gray'):
    vals=arr[valid]
    if low is None or high is None:
        low, high = _percentile_scale(vals)
    t=np.zeros(arr.shape, dtype='float32')
    t[valid]=np.clip((arr[valid]-low)/(high-low),0,1)
    r=np.zeros(arr.shape,dtype='uint8'); g=np.zeros_like(r); b=np.zeros_like(r); a=np.zeros_like(r)
    a[valid]=OPAQUE
    if cmap == 'surface_diverging':
        # blue for negative, pale ground near zero, green->dark for positive heights
        neg=valid & (arr < 0)
        pos=valid & (arr >= 0)
        # negatives scaled -5..0
        nt=np.clip((arr+5)/5,0,1)
        r[neg]=(80 + 120*nt[neg]).astype('uint8'); g[neg]=(120 + 100*nt[neg]).astype('uint8'); b[neg]=255
        pt=np.clip(arr/30,0,1)
        r[pos]=(235*(1-pt[pos]) + 20*pt[pos]).astype('uint8')
        g[pos]=(245*(1-pt[pos]) + 110*pt[pos]).astype('uint8')
        b[pos]=(210*(1-pt[pos]) + 35*pt[pos]).astype('uint8')
    else:
        v=(t*255).astype('uint8')
        r[valid]=v[valid]; g[valid]=v[valid]; b[valid]=v[valid]
    return r,g,b,a, {'low':low,'high':high,'colormap':cmap}

def _rgba_from_vegetation(arr, valid):
    classes=[
        (0.0,0.5,(235,245,210,255),'0-0.5 m'),
        (0.5,2.0,(185,225,130,255),'0.5-2 m'),
        (2.0,5.0,(105,190,85,255),'2-5 m'),
        (5.0,10.0,(45,150,55,255),'5-10 m'),
        (10.0,20.0,(10,105,35,255),'10-20 m'),
        (20.0,1000.0,(0,60,20,255),'20+ m'),
    ]
    r=np.zeros(arr.shape,dtype='uint8'); g=np.zeros_like(r); b=np.zeros_like(r); a=np.zeros_like(r)
    a[valid]=OPAQUE
    counts={}
    for lo,hi,color,label in classes:
        m=valid & (arr >= lo) & (arr < hi)
        r[m],g[m],b[m],a[m]=color
        counts[label]=int(m.sum())
    counts['transparent_nodata']=int((~valid).sum())
    return r,g,b,a, {'classes':[{'min_m':lo,'max_m':hi,'rgba':color,'label':label} for lo,hi,color,label in classes], 'class_counts':counts, 'colormap':'vegetation_height_classes'}

def write_rgba_like(src_ds, out_path: Path, rgba):
    ensure_dir(out_path.parent)
    drv=gdal.GetDriverByName('GTiff')
    out=drv.Create(str(out_path), src_ds.RasterXSize, src_ds.RasterYSize, 4, gdal.GDT_Byte, ['TILED=YES','COMPRESS=DEFLATE','ALPHA=YES'])
    out.SetGeoTransform(src_ds.GetGeoTransform())
    out.SetProjection(src_ds.GetProjection())
    names=['Red','Green','Blue','Alpha']
    interps=[gdal.GCI_RedBand,gdal.GCI_GreenBand,gdal.GCI_BlueBand,gdal.GCI_AlphaBand]
    for i,arr in enumerate(rgba, start=1):
        band=out.GetRasterBand(i); band.WriteArray(arr); band.SetColorInterpretation(interps[i-1]); band.SetDescription(names[i-1])
    out.FlushCache(); out=None

def create_oom_display_raster(src_path: Path, role: str, *, logger=None) -> dict | None:
    safe, reason = is_probably_oom_safe_raster(src_path)
    if safe:
        return None
    ds=gdal.Open(str(src_path))
    if ds is None or ds.RasterCount < 1:
        return None
    b=ds.GetRasterBand(1)
    arr=b.ReadAsArray().astype('float32')
    nodata=b.GetNoDataValue()
    valid=_valid_mask(arr,nodata)
    out_path=src_path.with_name(src_path.stem + '_oom.tif')
    if role in ('vegetation_height','vegetation_height_classified') or 'vegetation' in src_path.stem:
        r, g, b, a, viz = _rgba_from_vegetation(arr, valid & (arr >= 0) & (arr < 1000))
    elif role in ('surface_height_raw',):
        r, g, b, a, viz = _rgba_from_continuous(arr, valid, cmap='surface_diverging')
    else:
        r, g, b, a, viz = _rgba_from_continuous(arr, valid, cmap='gray')
    if logger:
        logger.log(f"[OOM] Creating display raster {out_path.name} from {src_path.name}: {reason}")
    write_rgba_like(ds, out_path, (r, g, b, a))
    src_summary=raster_summary(src_path)
    display_summary=raster_summary(out_path)
    return {
        'source_role': role,
        'source': str(src_path),
        'display_role': role + '_oom',
        'display': str(out_path),
        'reason': reason,
        'visualization': viz,
        'source_summary': src_summary,
        'display_summary': display_summary,
        'sha256': sha256(out_path),
    }

def create_oom_display_rasters(files: list[dict], *, logger=None) -> list[dict]:
    results=[]
    for f in list(files):
        p=Path(f.get('path',''))
        if not p.exists() or p.suffix.lower() not in ('.tif','.tiff'):
            continue
        try:
            res=create_oom_display_raster(p, f.get('role','raster'), logger=logger)
            if res:
                results.append(res)
        except Exception as e:
            if logger: logger.log(f"WARN OOM display raster failed for {p}: {e}")
            results.append({'source_role':f.get('role'),'source':str(p),'error':repr(e)})
    return results
