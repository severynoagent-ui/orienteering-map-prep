from __future__ import annotations
import argparse, json, time
from pathlib import Path
from .config import JobConfig, DEFAULT_CONTOURS, DEFAULT_PRODUCTS, DEFAULT_MAP_TYPE, DEFAULT_PROJECT_ROOT, DEFAULT_CACHE_ROOT, parse_crs, parse_contours, parse_products, parse_number_list, parse_map_scale, default_map_scale, parse_map_type, parse_map_standard, parse_map_contour_interval, default_map_contour_interval, parse_generate_omap, parse_drive_upload, parse_area_name, parse_tiling
from .util import safe_name
from .pipeline import run_pipeline

def parse_args(argv=None):
    p=argparse.ArgumentParser(description='Prepare headless GIS base layers for orienteering mapping from GPX')
    p.add_argument('--input-gpx', required=True, type=Path)
    p.add_argument('--project-id', default=None)
    p.add_argument('--area-name', default=None, help='Human map/area name used for project folder and .omap filename')
    p.add_argument('--target-crs', default=None)
    p.add_argument('--contours', default=None, help='comma/slash separated metres, e.g. 1,5,25 or 2.5/5')
    p.add_argument('--products', default=None, help='comma separated: dem,hillshade,hillshade_multidirectional,contours,slope,ortho/rgb_orthophoto,cir_orthophoto,buildings,dmp,surface_height,vegetation_height')
    p.add_argument('--prompt', default='', help='Natural language request; explicit CLI args win')
    p.add_argument('--project-root', default=DEFAULT_PROJECT_ROOT, type=Path)
    p.add_argument('--cache-root', default=DEFAULT_CACHE_ROOT, type=Path)
    p.add_argument('--buffer-m', default=100.0, type=float)
    p.add_argument('--dem-pixel-size-m', default=1.0, type=float)
    p.add_argument('--dmp-pixel-size-m', default=0.5, type=float)
    p.add_argument('--close-open', action='store_true')
    p.add_argument('--drive-folder-name', default=None, help='Google Drive job folder name under "OB podklady"')
    p.add_argument('--drive-root-folder', default='OB podklady', help='Google Drive root folder for uploaded outputs')
    p.add_argument('--drive-upload', action='store_true', help='Upload outputs to Google Drive')
    p.add_argument('--no-drive-upload', action='store_true', help='Do not upload outputs to Google Drive')
    p.add_argument('--cleanup-local-after-drive', action='store_true', help='Delete local project folder and ZIP after successful Drive upload')
    p.add_argument('--keep-local', action='store_true', help='Deprecated/no-op: local outputs are kept by default')
    p.add_argument('--map-scale', default=None, type=int, help='Map scale denominator, e.g. 10000 for 1:10 000')
    p.add_argument('--map-type', default=None, choices=['forest','sprint','mtbo'], help='Map type for OOM setup recommendations')
    p.add_argument('--map-standard', default=None, help='Explicit map standard/symbol set note, e.g. ISOM 2017-2')
    p.add_argument('--map-contour-interval', default=None, type=float, help='Final cartographic contour interval in metres')
    p.add_argument('--project-date', default=None, help='Project date for magnetic declination, YYYY-MM-DD')
    p.add_argument('--no-declination', action='store_true', help='Skip online magnetic declination lookup')
    p.add_argument('--no-oom-setup', action='store_true', help='Skip OOM_SETUP.md/txt generation')
    p.add_argument('--generate-omap', action='store_true', help='Generate optional OpenOrienteering Mapper project.omap')
    p.add_argument('--tile-grid', default=None, help='Split outputs into COLSxROWS grid, e.g. 2x3')
    p.add_argument('--tile-parts', default=None, type=int, help='Split outputs into approximately N parts')
    p.add_argument('--tile-max-side-m', default=None, type=float, help='Split outputs so tile side is at most this many metres')
    p.add_argument('--tile-max-mb', default=None, type=float, help='Choose a grid aiming for at most this many MB per tile')
    p.add_argument('--json', action='store_true')
    return p.parse_args(argv)

def main(argv=None):
    a=parse_args(argv)
    prompt=a.prompt or ''
    crs=a.target_crs or parse_crs(prompt) or 'EPSG:5514'
    contours=parse_number_list(a.contours) if a.contours else (parse_contours(prompt) or DEFAULT_CONTOURS.copy())
    if a.products:
        products=[x.strip().lower() for x in a.products.split(',') if x.strip()]
    else:
        products=parse_products(prompt) or DEFAULT_PRODUCTS.copy()
    products=[('ortho' if x in ('rgb_orthophoto','orthophoto_rgb','ortofoto_rgb') else 'hillshade_multidirectional' if x in ('multidirectional_hillshade','multi_hillshade') else x) for x in products]
    if 'vegetation_height' in products and 'surface_height' not in products:
        products.append('surface_height')
    if 'surface_height' in products and 'dmp' not in products:
        products.append('dmp')
    if any(x in products for x in ['surface_height','vegetation_height']) and 'dem' not in products:
        products.append('dem')
    if 'ortho' in products and 'dem' not in products and not any(x in products for x in ['hillshade','contours','slope']):
        pass
    map_type=a.map_type or parse_map_type(prompt) or DEFAULT_MAP_TYPE
    area_name=a.area_name or parse_area_name(prompt)
    pid=a.project_id or safe_name(((area_name or a.input_gpx.stem) + '-' + time.strftime('%Y%m%d-%H%M%S')))
    map_scale=a.map_scale or parse_map_scale(prompt) or default_map_scale(map_type)
    map_standard=a.map_standard or parse_map_standard(prompt)
    map_contour_interval=a.map_contour_interval or parse_map_contour_interval(prompt) or default_map_contour_interval(map_type, map_scale)
    tiling=parse_tiling(prompt)
    if a.tile_grid:
        cols, rows = [int(x) for x in a.tile_grid.lower().replace('×','x').split('x', 1)]
        tiling={'cols':cols,'rows':rows}
    elif a.tile_parts:
        tiling={'parts':a.tile_parts}
    elif a.tile_max_side_m:
        tiling={'max_side_m':a.tile_max_side_m}
    elif a.tile_max_mb:
        tiling={'max_tile_mb':a.tile_max_mb}
    cfg=JobConfig(input_gpx=a.input_gpx, project_id=pid, project_root=a.project_root, cache_root=a.cache_root,
                  target_crs=crs, contours_m=contours, products=products, buffer_m=a.buffer_m,
                  dem_pixel_size_m=a.dem_pixel_size_m, dmp_pixel_size_m=a.dmp_pixel_size_m, close_open=a.close_open,
                  drive_upload=(False if a.no_drive_upload else (a.drive_upload or parse_drive_upload(prompt))), drive_root_folder=a.drive_root_folder,
                  drive_job_folder_name=a.drive_folder_name,
                  cleanup_local_after_drive=a.cleanup_local_after_drive,
                  map_scale=map_scale, map_type=map_type, map_standard=map_standard,
                  map_contour_interval=map_contour_interval, project_date=a.project_date,
                  calculate_declination=not a.no_declination, generate_oom_setup=not a.no_oom_setup,
                  generate_omap=a.generate_omap or parse_generate_omap(prompt), tiling=tiling)
    res=run_pipeline(cfg)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print('PROJECT_ROOT',res['project_root'])
        print('ZIP',res['zip'])
        print('MANIFEST',res['manifest'])
        if res.get('warnings'):
            print('WARNINGS', '; '.join(res['warnings']))

if __name__ == '__main__':
    main()
