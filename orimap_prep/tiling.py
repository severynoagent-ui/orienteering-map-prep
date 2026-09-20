from __future__ import annotations

import math
from pathlib import Path

from .util import run, sha256


def _column_label(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    if index < 0:
        raise ValueError("column index must be non-negative")
    label = ""
    n = index
    while True:
        label = chr(ord('A') + (n % 26)) + label
        n = n // 26 - 1
        if n < 0:
            return label


def tile_suffix(col_index: int, row_index: int) -> str:
    return f"{_column_label(col_index)}{row_index + 1}"


def _grid_shape(extent: dict, cfg: dict) -> tuple[int, int]:
    width = max(0.0, float(extent['maxx']) - float(extent['minx']))
    height = max(0.0, float(extent['maxy']) - float(extent['miny']))
    if cfg.get('cols') and cfg.get('rows'):
        return max(1, int(cfg['cols'])), max(1, int(cfg['rows']))
    if cfg.get('max_side_m'):
        side = max(1.0, float(cfg['max_side_m']))
        return max(1, math.ceil(width / side)), max(1, math.ceil(height / side))
    parts = max(1, int(cfg.get('parts') or 4))
    # Prefer a near-square grid adjusted for AOI aspect ratio.
    aspect = width / height if height else 1.0
    cols = max(1, math.ceil(math.sqrt(parts * aspect)))
    rows = max(1, math.ceil(parts / cols))
    while cols * rows < parts:
        rows += 1
    return cols, rows


def build_tile_grid(extent: dict, cfg: dict) -> list[dict]:
    cols, rows = _grid_shape(extent, cfg)
    minx, maxx = float(extent['minx']), float(extent['maxx'])
    miny, maxy = float(extent['miny']), float(extent['maxy'])
    dx = (maxx - minx) / cols
    dy = (maxy - miny) / rows
    out=[]
    for r in range(rows):  # north to south
        tile_maxy = maxy - r * dy
        tile_miny = maxy - (r + 1) * dy
        for c in range(cols):  # west to east
            tile_minx = minx + c * dx
            tile_maxx = minx + (c + 1) * dx
            out.append({
                'suffix': tile_suffix(c, r),
                'col': _column_label(c),
                'row': r + 1,
                'extent': {'minx': tile_minx, 'maxx': tile_maxx, 'miny': tile_miny, 'maxy': tile_maxy},
            })
    return out


DATA_EXTENSIONS = {'.tif', '.tiff', '.gpkg'}
SKIP_ROLES = {
    'input_gpx', 'area_geojson', 'area_target', 'area_5514', 'manifest', 'readme',
    'oom_setup_md', 'oom_setup_txt', 'oom_setup_meta', 'project_omap',
}


def _is_tileable_record(rec: dict) -> bool:
    if rec.get('tile') or rec.get('role') in SKIP_ROLES:
        return False
    path = Path(rec.get('path') or '')
    return path.suffix.lower() in DATA_EXTENSIONS and path.exists() and path.is_file()


def _remove_existing_tile(path: Path) -> None:
    if path.exists():
        path.unlink()
    for sidecar in path.parent.glob(path.name + '.*'):
        if sidecar.is_file():
            sidecar.unlink()


def _tile_raster(src: Path, dst: Path, extent: dict) -> None:
    _remove_existing_tile(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        'gdal_translate', '-q', '-of', 'GTiff',
        '-co', 'TILED=YES', '-co', 'COMPRESS=DEFLATE',
        '-projwin', str(extent['minx']), str(extent['maxy']), str(extent['maxx']), str(extent['miny']),
        str(src), str(dst),
    ])


def _tile_vector(src: Path, dst: Path, extent: dict) -> None:
    _remove_existing_tile(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        'ogr2ogr', '-f', 'GPKG', str(dst), str(src),
        '-spat', str(extent['minx']), str(extent['miny']), str(extent['maxx']), str(extent['maxy']),
        '-clipsrc', str(extent['minx']), str(extent['miny']), str(extent['maxx']), str(extent['maxy']),
    ])


def _tile_path(src: Path, suffix: str) -> Path:
    return src.parent / 'tiles' / f'{src.stem}_{suffix}{src.suffix}'


def _grid_cfg_with_size_hint(files: list[dict], cfg: dict) -> dict:
    if any(cfg.get(k) for k in ('cols', 'rows', 'parts', 'max_side_m')) or not cfg.get('max_tile_mb'):
        return dict(cfg)
    total = sum(Path(f.get('path') or '').stat().st_size for f in files if _is_tileable_record(f))
    target = max(1.0, float(cfg['max_tile_mb'])) * 1024 * 1024
    out = dict(cfg)
    out['parts'] = max(1, math.ceil(total / target))
    return out


def tile_manifest_files(project_root: Path, files: list[dict], tiling_cfg: dict, extent: dict, *, logger=None) -> dict:
    """Create tiled copies of all tileable product files and append them to manifest files.

    Raster tiles are cut with GDAL `-projwin`; vector tiles are spatially
    filtered/clipped with OGR. Originals are preserved. Tile rows are north to
    south and columns west to east.
    """
    project_root = Path(project_root)
    originals = [f for f in list(files) if _is_tileable_record(f)]
    base_cfg = _grid_cfg_with_size_hint(originals, tiling_cfg)
    max_bytes = float(base_cfg.get('max_tile_mb') or 0) * 1024 * 1024

    final_cfg = dict(base_cfg)
    final_grid=[]; final_created=[]; final_warnings=[]
    attempts = 6 if max_bytes else 1
    for attempt in range(attempts):
        grid = build_tile_grid(extent, final_cfg)
        created=[]; oversize=[]
        for tile in grid:
            suffix = tile['suffix']
            for rec in originals:
                src = Path(rec['path'])
                dst = _tile_path(src, suffix)
                if logger:
                    logger.log(f"[tiling] {rec.get('role')} -> {dst.relative_to(project_root)}")
                if src.suffix.lower() in ('.tif', '.tiff'):
                    _tile_raster(src, dst, tile['extent'])
                elif src.suffix.lower() == '.gpkg':
                    _tile_vector(src, dst, tile['extent'])
                if dst.exists() and dst.stat().st_size > 0:
                    if max_bytes and dst.stat().st_size > max_bytes:
                        oversize.append(dst)
                    created.append({
                        'role': f"{rec.get('role')}_{suffix}",
                        'path': str(dst),
                        'size': dst.stat().st_size,
                        'sha256': sha256(dst),
                        'tile': suffix,
                        'source_role': rec.get('role'),
                        'source_path': rec.get('path'),
                    })
        final_grid, final_created = grid, created
        if not oversize:
            break
        if attempt == attempts - 1:
            final_warnings = [f"Tile {p} is larger than requested max_tile_mb={base_cfg['max_tile_mb']}" for p in oversize]
            break
        # Refine the grid and retry. Remove current tile files first so the final
        # package contains one consistent grid only.
        for rec in created:
            p = Path(rec['path'])
            if p.exists():
                p.unlink()
        final_cfg = dict(final_cfg)
        final_cfg['cols'] = int(final_cfg.get('cols') or len({t['col'] for t in grid})) + 1
        final_cfg['rows'] = int(final_cfg.get('rows') or len({t['row'] for t in grid})) + 1
        final_cfg.pop('parts', None)

    files.extend(final_created)
    return {
        'requested': tiling_cfg,
        'effective': final_cfg,
        'n_source_files': len(originals),
        'n_created_files': len(final_created),
        'tiles': final_grid,
        'n_tiles': len(final_grid),
        'n_cols': len({t['col'] for t in final_grid}),
        'n_rows': len({t['row'] for t in final_grid}),
        'row_order': 'north_to_south',
        'col_order': 'west_to_east',
        'suffix_format': '_<column><row>, e.g. _A1',
        'created_files': final_created,
        'warnings': final_warnings,
    }
