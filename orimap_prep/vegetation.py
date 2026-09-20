from __future__ import annotations
from pathlib import Path
from osgeo import gdal, osr
import numpy as np
import math
from .util import ensure_dir, run

RAW_NODATA = -9999.0
CLASS_NODATA = 255
DEFAULT_CLASSES = [
    (0.0, 0.5, 1, "0-0.5 m / near ground"),
    (0.5, 2.0, 2, "0.5-2 m / low"),
    (2.0, 5.0, 3, "2-5 m / medium"),
    (5.0, 15.0, 4, "5-15 m / high"),
    (15.0, 1000.0, 5, ">15 m / very high"),
]

class VegetationError(RuntimeError):
    pass

def raster_grid_info(path: Path) -> dict:
    ds = gdal.Open(str(path))
    if ds is None:
        raise VegetationError(f"Cannot open raster {path}")
    gt = ds.GetGeoTransform()
    srs = osr.SpatialReference(wkt=ds.GetProjection())
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    return {
        "path": str(path),
        "xsize": ds.RasterXSize,
        "ysize": ds.RasterYSize,
        "geotransform": list(gt),
        "projection_wkt": ds.GetProjection()[:2000],
        "epsg": srs.GetAuthorityCode(None),
        "pixel_size": [abs(gt[1]), abs(gt[5])],
        "extent": {
            "minx": gt[0],
            "maxy": gt[3],
            "maxx": gt[0] + gt[1] * ds.RasterXSize,
            "miny": gt[3] + gt[5] * ds.RasterYSize,
        },
        "nodata": nodata,
    }

def grids_equal(a: dict, b: dict, tol: float = 1e-7) -> bool:
    if a["xsize"] != b["xsize"] or a["ysize"] != b["ysize"]:
        return False
    for x, y in zip(a["geotransform"], b["geotransform"]):
        if abs(x - y) > tol:
            return False
    return (a.get("epsg") == b.get("epsg")) or (a.get("projection_wkt") == b.get("projection_wkt"))

def align_raster_to_reference(src: Path, ref: Path, out: Path, *, resampling: str = "bilinear", logger=None) -> dict:
    ensure_dir(out.parent)
    ref_info = raster_grid_info(ref)
    e = ref_info["extent"]
    original = raster_grid_info(src)
    cmd = [
        "gdalwarp", "-overwrite",
        "-t_srs", ref_info["projection_wkt"],
        "-te", str(e["minx"]), str(e["miny"]), str(e["maxx"]), str(e["maxy"]),
        "-ts", str(ref_info["xsize"]), str(ref_info["ysize"]),
        "-r", resampling,
        "-srcnodata", str(original.get("nodata") if original.get("nodata") is not None else RAW_NODATA),
        "-dstnodata", str(RAW_NODATA),
        "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
        str(src), str(out),
    ]
    if logger:
        logger.log(f"[vegetation] Align DMP to DEM grid with {resampling} resampling")
    run(cmd)
    aligned = raster_grid_info(out)
    if not grids_equal(ref_info, aligned, tol=1e-5):
        raise VegetationError("Aligned DMP grid still does not match DEM grid")
    return {
        "source": str(src),
        "reference": str(ref),
        "output": str(out),
        "resampling": resampling,
        "original_grid": original,
        "target_grid": ref_info,
        "aligned_grid": aligned,
        "reason": "DMP and DEM must share CRS, extent, dimensions, pixel size and pixel grid before DMP-DEM raster calculation.",
    }

def _read_array(path: Path):
    ds = gdal.Open(str(path))
    if ds is None:
        raise VegetationError(f"Cannot open raster {path}")
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype("float32")
    nodata = band.GetNoDataValue()
    return ds, arr, nodata

def _write_like(ref_ds, path: Path, arr, nodata, dtype=gdal.GDT_Float32, color_table=None):
    ensure_dir(path.parent)
    drv = gdal.GetDriverByName("GTiff")
    opts = ["TILED=YES", "COMPRESS=DEFLATE"]
    if dtype == gdal.GDT_Float32:
        opts.append("PREDICTOR=3")
    out = drv.Create(str(path), ref_ds.RasterXSize, ref_ds.RasterYSize, 1, dtype, opts)
    out.SetGeoTransform(ref_ds.GetGeoTransform())
    out.SetProjection(ref_ds.GetProjection())
    b = out.GetRasterBand(1)
    b.WriteArray(arr)
    b.SetNoDataValue(nodata)
    if color_table is not None:
        b.SetRasterColorTable(color_table)
        b.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    b.FlushCache(); out.FlushCache(); out = None

def array_stats(arr, valid_mask) -> dict:
    total = int(arr.size)
    valid_count = int(valid_mask.sum())
    nodata_count = total - valid_count
    if valid_count == 0:
        return {"total_pixels": total, "valid_pixels": 0, "nodata_pixels": nodata_count, "nodata_ratio": 1.0}
    v = arr[valid_mask].astype("float64")
    qs = np.percentile(v, [1, 5, 25, 50, 75, 95, 99])
    return {
        "total_pixels": total,
        "valid_pixels": valid_count,
        "nodata_pixels": nodata_count,
        "nodata_ratio": nodata_count / total,
        "min": float(np.min(v)),
        "max": float(np.max(v)),
        "mean": float(np.mean(v)),
        "std": float(np.std(v)),
        "p01": float(qs[0]),
        "p05": float(qs[1]),
        "p25": float(qs[2]),
        "p50": float(qs[3]),
        "p75": float(qs[4]),
        "p95": float(qs[5]),
        "p99": float(qs[6]),
        "negative_pixels": int((v < 0).sum()),
        "negative_ratio_valid": float((v < 0).sum() / valid_count),
        "near_zero_0_0_5m_ratio_valid": float(((v >= 0) & (v < 0.5)).sum() / valid_count),
        "above_2m_ratio_valid": float((v >= 2).sum() / valid_count),
        "above_5m_ratio_valid": float((v >= 5).sum() / valid_count),
        "above_15m_ratio_valid": float((v >= 15).sum() / valid_count),
        "above_40m_ratio_valid": float((v >= 40).sum() / valid_count),
    }

def make_surface_height_products(dmp_aligned: Path, dem: Path, out_dir: Path, *, logger=None, classes=None) -> dict:
    ensure_dir(out_dir)
    classes = classes or DEFAULT_CLASSES
    ref_ds, dmp_arr, dmp_nodata = _read_array(dmp_aligned)
    dem_ds, dem_arr, dem_nodata = _read_array(dem)
    if ref_ds.RasterXSize != dem_ds.RasterXSize or ref_ds.RasterYSize != dem_ds.RasterYSize:
        raise VegetationError("DMP and DEM dimensions differ after alignment")
    valid = np.isfinite(dmp_arr) & np.isfinite(dem_arr)
    if dmp_nodata is not None:
        valid &= dmp_arr != dmp_nodata
    if dem_nodata is not None:
        valid &= dem_arr != dem_nodata
    raw = np.full(dmp_arr.shape, RAW_NODATA, dtype="float32")
    raw[valid] = dmp_arr[valid] - dem_arr[valid]
    raw_path = out_dir / "surface_height_raw.tif"
    _write_like(ref_ds, raw_path, raw, RAW_NODATA, gdal.GDT_Float32)

    raw_valid = raw != RAW_NODATA
    stats = array_stats(raw, raw_valid)
    warnings = []
    if stats.get("valid_pixels", 0) == 0:
        warnings.append("surface_height_raw has no valid pixels")
    else:
        if stats.get("negative_ratio_valid", 0) > 0.25:
            warnings.append("More than 25% of valid DMP-DEM pixels are negative; check temporal/alignment differences")
        if stats.get("p99", 0) > 80 or stats.get("max", 0) > 150:
            warnings.append("Very high DMP-DEM values found; inspect buildings/outliers/data alignment")
        if stats.get("nodata_ratio", 0) > 0.5:
            warnings.append("More than 50% NoData in surface height raster")

    veg = np.full(raw.shape, RAW_NODATA, dtype="float32")
    # Mapping-oriented continuous helper: preserve raw separately, but for display
    # clamp negative values to 0 and mask extreme implausible values. This does
    # not remove buildings; README/manifest warn explicitly.
    veg_valid = raw_valid & (raw < 80)
    veg[veg_valid] = np.maximum(raw[veg_valid], 0)
    veg_path = out_dir / "vegetation_height.tif"
    _write_like(ref_ds, veg_path, veg, RAW_NODATA, gdal.GDT_Float32)

    cls = np.full(raw.shape, CLASS_NODATA, dtype="uint8")
    cls_valid = veg != RAW_NODATA
    for lo, hi, code, _label in classes:
        cls[cls_valid & (veg >= lo) & (veg < hi)] = code
    ct = gdal.ColorTable()
    ct.SetColorEntry(0, (0, 0, 0, 0))
    ct.SetColorEntry(1, (235, 245, 210, 255))
    ct.SetColorEntry(2, (170, 220, 120, 255))
    ct.SetColorEntry(3, (80, 180, 80, 255))
    ct.SetColorEntry(4, (20, 120, 40, 255))
    ct.SetColorEntry(5, (0, 70, 25, 255))
    class_path = out_dir / "vegetation_height_classified.tif"
    _write_like(ref_ds, class_path, cls, CLASS_NODATA, gdal.GDT_Byte, color_table=ct)

    class_counts = {}
    for lo, hi, code, label in classes:
        class_counts[str(code)] = {"range_m": [lo, hi], "label": label, "pixels": int((cls == code).sum())}
    class_counts["nodata"] = {"pixels": int((cls == CLASS_NODATA).sum())}
    return {
        "files": {
            "surface_height_raw": raw_path,
            "vegetation_height": veg_path,
            "vegetation_height_classified": class_path,
        },
        "expression": "surface_height_raw = aligned_DMP_OK - DEM_DMR5G",
        "vegetation_height_processing": "visual/helper raster only: negative values clamped to 0, values >=80 m masked as NoData; buildings/objects are not removed",
        "classes": [{"min_m": lo, "max_m": hi, "code": code, "label": label} for lo, hi, code, label in classes],
        "class_counts": class_counts,
        "statistics": stats,
        "warnings": warnings,
    }
