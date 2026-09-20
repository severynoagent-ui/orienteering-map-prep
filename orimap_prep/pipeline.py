from __future__ import annotations
from pathlib import Path
import json, shutil, time, zipfile, subprocess
from .config import JobConfig, contour_token
from .util import ensure_dir, run, sha256, write_json, disk_free_bytes
from .logging_utils import Logger
from .gpx import write_polygon_outputs, layer_extent, layer_area
from .crs import validate_crs, is_projected_metre
from .sources import download_dmr5g_tiles, build_dem_from_tiles, download_dmpok_tiles, build_dmp_from_tiles, service_metadata, download_ortho_wms, estimate_current_orthophoto_acquisition, download_ortocir_wms
from .vegetation import align_raster_to_reference, make_surface_height_products, raster_grid_info
from .qa import assert_raster_ok, assert_vector_ok, assert_zip_ok, compare_raster_georef
from .drive_upload import upload_project_tree
from .oom_compat import create_oom_display_rasters
from .oom_setup import generate_oom_setup
from .omap_builder import generate_omap_project, apply_dated_template_filenames
from .buildings import download_ruian_buildings, RUIAN_BUILDINGS_SERVICE, RUIAN_BUILDINGS_LAYER_ID
from .tiling import tile_manifest_files

class PipelineError(RuntimeError): pass

def project_paths(cfg: JobConfig):
    root = cfg.project_root / cfg.project_id
    return {
        'root': root,
        'area': root/'00_oblast',
        'elev': root/'01_elevation',
        'elev_src': root/'01_elevation'/'source',
        'relief': root/'02_relief',
        'contours': root/'03_contours',
        'ortho': root/'04_ortofoto',
        'buildings': root/'05_buildings',
        'veg': root/'06_vegetation',
        'logs': root/'logs',
        'tmp': root/'tmp',
    }

def setup_project(cfg: JobConfig):
    p=project_paths(cfg)
    for d in p.values(): ensure_dir(d)
    return p

def generate_relief(dem: Path, relief_dir: Path, products: list[str], logger: Logger):
    outputs={}
    hill=relief_dir/'hillshade.tif'
    if 'hillshade' in products:
        logger.log('[6/8] Generuji hillshade')
        run(['gdaldem','hillshade',str(dem),str(hill),'-compute_edges','-of','GTiff','-co','TILED=YES','-co','COMPRESS=DEFLATE'])
        outputs['hillshade']=hill
    if 'hillshade_multidirectional' in products:
        try:
            mh=relief_dir/'hillshade_multidirectional.tif'
            logger.log('[6/8] Generuji multidirectional hillshade')
            run(['gdaldem','hillshade',str(dem),str(mh),'-multidirectional','-compute_edges','-of','GTiff','-co','TILED=YES','-co','COMPRESS=DEFLATE'])
            outputs['hillshade_multidirectional']=mh
        except Exception as e:
            logger.log(f'WARN multidirectional hillshade failed: {e}')
    if 'slope' in products:
        sl=relief_dir/'slope.tif'
        logger.log('[6/8] Generuji slope')
        run(['gdaldem','slope',str(dem),str(sl),'-compute_edges','-of','GTiff','-co','TILED=YES','-co','COMPRESS=DEFLATE'])
        outputs['slope']=sl
    return outputs

def generate_contours(dem: Path, contour_dir: Path, intervals: list[float], logger: Logger):
    outputs={}
    logger.log('[7/8] Generuji vrstevnice')
    for interval in intervals:
        tok=contour_token(interval)
        out=contour_dir/f'contours_{tok}.gpkg'
        if out.exists(): out.unlink()
        run(['gdal_contour','-a','elev','-i',str(interval),'-f','GPKG','-nln',f'contours_{tok}',str(dem),str(out)])
        outputs[f'contours_{tok}']=out
    return outputs

def make_readme(cfg: JobConfig, manifest: dict, path: Path):
    lines=[]
    lines.append(f"Projekt: {cfg.project_id}\n")
    lines.append(f"CRS: {cfg.target_crs}\n")
    lines.append("\nVýstupy:\n")
    for f in manifest.get('files',[]):
        lines.append(f"- {f['role']}: {f['path']}\n")
    lines.append("\nDoporučení pro OpenOrienteering Mapper:\n")
    lines.append("- Načti DEM/hillshade jako rastrový podklad.\n")
    lines.append("- Načti požadované contours_*.gpkg jako vektorové vrstevnice.\n")
    if 'ortho' in cfg.products:
        ortho_meta = manifest.get('ortho_acquisition') or {}
        yr = ortho_meta.get('acquisition_year') or ortho_meta.get('official_product_years')
        conf = ortho_meta.get('confidence')
        lines.append(f"- RGB ortofoto je pomocný rastrový podklad z ČÚZK; rok snímkování: {yr} ({conf}). Ověř licenci/atribuci podle ČÚZK.\n")
    if 'cir_orthophoto' in cfg.products:
        cir_meta = manifest.get('cir_orthophoto') or {}
        yr = cir_meta.get('imagery_year') or 'nezjištěno'
        lines.append(f"- CIR ortofoto je doplňkový podklad z ČÚZK WMS-ORTOCIR pro interpretaci spektrálních vlastností vegetace; vrstva/rok: {yr}. CIR není mapa průběžnosti ani rychlosti běhu.\n")
    if 'buildings' in cfg.products:
        b_meta = manifest.get('buildings') or {}
        count = b_meta.get('clipped_feature_count', 'nezjištěno')
        lines.append(f"- Budovy jsou RÚIAN StavebniObjekt z ČÚZK REST, ořezané na AOI; počet polygonů: {count}.\n")
    if manifest.get('tiling'):
        t = manifest['tiling']
        lines.append(f"- Výstupy jsou rozdělené na dlaždice: {t.get('n_cols')} sloupců × {t.get('n_rows')} řádků; suffixy `_A1`, `_B2` atd.; detaily viz manifest.json -> tiling.\n")
    if any(p in cfg.products for p in ['dmp','surface_height','vegetation_height']):
        lines.append("\nDMP / výška vegetace:\n")
        lines.append("- DMP = digitální model povrchu: terén + vegetace + budovy + jiné objekty.\n")
        lines.append("- DEM/DMR = digitální model reliéfu/terénu.\n")
        lines.append("- surface_height_raw.tif = DMP - DMR/DEM, tedy relativní výška povrchu nad terénem v metrech.\n")
        lines.append("- vegetation_height.tif a vegetation_height_classified.tif jsou pomocné mapovací/vizualizační vrstvy; nejsou automatickou mapou průběžnosti lesa a neodstraňují spolehlivě budovy.\n")
    lines.append("\nZdroj výškopisu: ČÚZK DMR 5G ImageServer, oficiální veřejná služba.\n")
    lines.append("Upozornění: interval vrstevnic není tvrzením o vertikální přesnosti zdrojových dat.\n")
    path.write_text(''.join(lines), encoding='utf-8')

def add_file_manifest(files, role, path: Path):
    files.append({'role':role,'path':str(path),'size':path.stat().st_size if path.exists() else None,'sha256':sha256(path) if path.exists() and path.is_file() else None})

def package_project(root: Path, zip_path: Path):
    if zip_path.exists(): zip_path.unlink()
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
        for p in root.rglob('*'):
            if p.is_file() and p != zip_path and '/tmp/' not in str(p):
                z.write(p, p.relative_to(root.parent))
    return zip_path

def _safe_cleanup_local_outputs(project_root: Path, zip_path: Path, allowed_root: Path, logger: Logger):
    """Remove local output project after successful Drive upload.

    Guard hard against deleting outside the configured project root.
    """
    allowed = allowed_root.resolve()
    root = project_root.resolve()
    z = zip_path.resolve()
    if allowed not in [root, *root.parents]:
        raise PipelineError(f'Refusing cleanup outside project root: {root} not under {allowed}')
    if root.name in ('', '.', '..') or len(root.name) < 3:
        raise PipelineError(f'Refusing cleanup suspicious project directory: {root}')
    if z.parent != allowed or not z.name.startswith(root.name):
        raise PipelineError(f'Refusing cleanup suspicious zip path: {z}')
    if z.exists():
        logger.log(f'[cleanup] Mazání lokálního ZIP po Drive uploadu: {z}')
        z.unlink()
    if root.exists():
        logger.log(f'[cleanup] Mazání lokální projektové složky po Drive uploadu: {root}')
        shutil.rmtree(root)

def run_pipeline(cfg: JobConfig):
    cfg.target_crs=validate_crs(cfg.target_crs)
    paths=setup_project(cfg)
    logger=Logger(paths['logs']/ 'pipeline.log')
    warnings=[]; files=[]; source_records=[]
    start=time.strftime('%Y-%m-%dT%H:%M:%S%z')
    try:
        logger.log(f"Oblast: z GPX {cfg.input_gpx}; CRS: {cfg.target_crs}; výstupy: {cfg.products}; vrstevnice: {cfg.contours_m}")
        if disk_free_bytes(paths['root']) < 5*1024**3:
            raise PipelineError('Nedostatek místa: požaduji alespoň 5 GB volného prostoru')
        if not is_projected_metre(cfg.target_crs):
            warnings.append(f'{cfg.target_crs} is not a projected metre CRS; hillshade/contours may be unsuitable')
        # [1-2] GPX
        logger.log('[1/8] Validuji GPX')
        input_copy=paths['area']/'input.gpx'; shutil.copy2(cfg.input_gpx,input_copy)
        area_geojson=paths['area']/'area.geojson'
        area_target=paths['area']/f"area_{cfg.target_crs.replace(':','')}.gpkg"
        area_5514=paths['area']/'area_EPSG5514.gpkg'
        logger.log('[2/8] Připravuji polygon a CRS')
        gpx_meta=write_polygon_outputs(input_copy, area_geojson, area_target, area_5514, cfg.target_crs, close_open=cfg.close_open)
        area_info=assert_vector_ok(area_target); area_info_5514=assert_vector_ok(area_5514)
        area_lonlat_extent=layer_extent(area_geojson)
        area_m2=layer_area(area_target)
        add_file_manifest(files,'input_gpx',input_copy); add_file_manifest(files,'area_geojson',area_geojson); add_file_manifest(files,'area_target',area_target); add_file_manifest(files,'area_5514',area_5514)
        # [3-5] DMR DEM
        dem=paths['elev']/'dem.tif'
        dmr_meta=[]
        needs_dem = any(x in cfg.products for x in ['dem','hillshade','hillshade_multidirectional','contours','slope','surface_height','vegetation_height'])
        if needs_dem:
            logger.log('[3/8] Zjišťuji DMR 5G tiles/službu')
            svc=service_metadata(); source_records.append({'dataset':'ČÚZK DMR 5G ImageServer','url':'https://ags.cuzk.cz/arcgis2/rest/services/dmr5g/ImageServer','metadata_summary':{k:svc['dmr5g_imageserver'].get(k) for k in ['name','description','pixelSizeX','pixelSizeY','bandCount','copyrightText']}})
            ext5514=layer_extent(area_5514)
            # buffer in EPSG:5514 metres
            ext5514={'minx':ext5514['minx']-cfg.buffer_m,'maxx':ext5514['maxx']+cfg.buffer_m,'miny':ext5514['miny']-cfg.buffer_m,'maxy':ext5514['maxy']+cfg.buffer_m}
            logger.log('[4/8] Stahuji/cache DMR 5G data')
            tiles, dmr_meta=download_dmr5g_tiles(ext5514, cfg.cache_root, cfg.dem_pixel_size_m, cfg.max_export_px, logger=logger)
            logger.log('[5/8] Generuji DEM')
            build_dem_from_tiles(tiles, area_target, cfg.target_crs, dem, paths['tmp'], logger=logger)
            dem_info=assert_raster_ok(dem)
            add_file_manifest(files,'dem',dem)
        # relief/contours
        relief_outputs={}
        if any(x in cfg.products for x in ['hillshade','hillshade_multidirectional','slope']):
            relief_outputs=generate_relief(dem, paths['relief'], cfg.products, logger)
            for role,p in relief_outputs.items(): assert_raster_ok(p); add_file_manifest(files,role,p)
        contour_outputs={}
        if 'contours' in cfg.products:
            contour_outputs=generate_contours(dem, paths['contours'], cfg.contours_m, logger)
            for role,p in contour_outputs.items(): assert_vector_ok(p); add_file_manifest(files,role,p)
        dmp_meta=[]
        vegetation_report=None
        if any(x in cfg.products for x in ['dmp','surface_height','vegetation_height']):
            logger.log('[dmp] Zjišťuji a stahuji ČÚZK DMP OK')
            svc=service_metadata()
            dmp_svc=svc['dmpok_imageserver']
            source_records.append({'dataset':'ČÚZK DMP OK ImageServer','url':'https://ags.cuzk.gov.cz/arcgis2/rest/services/dmp_obrazova_korelace/ImageServer','metadata_summary':{k:dmp_svc.get(k) for k in ['name','description','pixelSizeX','pixelSizeY','meanPixelSize','heightModelInfo','bandCount','copyrightText','capabilities']}})
            ext5514=layer_extent(area_5514)
            ext5514={'minx':ext5514['minx']-cfg.buffer_m,'maxx':ext5514['maxx']+cfg.buffer_m,'miny':ext5514['miny']-cfg.buffer_m,'maxy':ext5514['maxy']+cfg.buffer_m}
            dmp_tiles, dmp_meta=download_dmpok_tiles(ext5514, cfg.cache_root, cfg.dmp_pixel_size_m, cfg.max_export_px, logger=logger)
            dmp=paths['veg']/'dmp_ok.tif'
            build_dmp_from_tiles(dmp_tiles, area_target, cfg.target_crs, dmp, paths['tmp'], logger=logger)
            assert_raster_ok(dmp); add_file_manifest(files,'dmp_ok',dmp)
            if any(x in cfg.products for x in ['surface_height','vegetation_height']):
                logger.log('[vegetation] Zarovnávám DMP na DEM grid a počítám DMP - DMR')
                dmp_aligned=paths['veg']/'dmp_ok_aligned_to_dem.tif'
                alignment=align_raster_to_reference(dmp, dem, dmp_aligned, resampling='bilinear', logger=logger)
                assert_raster_ok(dmp_aligned); add_file_manifest(files,'dmp_ok_aligned_to_dem',dmp_aligned)
                veg_products=make_surface_height_products(dmp_aligned, dem, paths['veg'], logger=logger)
                vegetation_report={
                    'dmp_source': 'ČÚZK DMP OK ImageServer',
                    'dmp_tiles': dmp_meta,
                    'alignment': alignment,
                    'dem_used': str(dem),
                    **{k:v for k,v in veg_products.items() if k != 'files'},
                }
                warnings.extend(veg_products.get('warnings', []))
                if 'surface_height' in cfg.products or 'vegetation_height' in cfg.products:
                    add_file_manifest(files,'surface_height_raw',veg_products['files']['surface_height_raw'])
                if 'vegetation_height' in cfg.products:
                    add_file_manifest(files,'vegetation_height',veg_products['files']['vegetation_height'])
                    add_file_manifest(files,'vegetation_height_classified',veg_products['files']['vegetation_height_classified'])
        ortho_acquisition=None
        cir_orthophoto=None
        ortho_path=None
        cir_path=None
        if 'ortho' in cfg.products:
            logger.log('[ortho] Stahuji aktuální ortofoto přes oficiální ČÚZK WMS')
            ortho_acquisition = estimate_current_orthophoto_acquisition(area_lonlat_extent)
            source_records.append({'dataset':'ČÚZK Ortofoto WMS/WMTS','wms': 'https://ags.cuzk.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer?', 'wmts':'https://ags.cuzk.cz/arcgis1/rest/services/ORTOFOTO/MapServer/WMTS', 'acquisition': ortho_acquisition})
            ext=layer_extent(area_target)
            ortho=paths['ortho']/'ortofoto_current.tif'
            download_ortho_wms(ext, cfg.target_crs, ortho, logger=logger)
            assert_raster_ok(ortho); add_file_manifest(files,'ortofoto_current',ortho)
            ortho_path=ortho
        if 'cir_orthophoto' in cfg.products:
            logger.log('[cir] Stahuji CIR ortofoto přes oficiální ČÚZK WMS-ORTOCIR')
            ext=layer_extent(area_target)
            cir=paths['ortho']/'ortofoto_cir.tif'
            cir, cir_orthophoto = download_ortocir_wms(ext, area_lonlat_extent, area_target, cfg.target_crs, cir, cfg.cache_root, logger=logger)
            assert_raster_ok(cir); add_file_manifest(files,'ortofoto_cir',cir)
            cir_path=cir
            source_records.append({'dataset':'ČÚZK Ortofoto CIR WMS-ORTOCIR','wms':'https://geoportal.cuzk.cz/WMS_ORTOFOTO_CIR/WMService.aspx?', 'metadata':'https://geoportal.cuzk.gov.cz/Default.aspx?mode=TextMeta&side=ortofoto&metadataID=CZ-CUZK-ORTOCIR-R&productid=63416&menu=235', 'acquisition':cir_orthophoto})
        buildings_report=None
        if 'buildings' in cfg.products:
            ext5514=layer_extent(area_5514)
            ext5514={'minx':ext5514['minx']-cfg.buffer_m,'maxx':ext5514['maxx']+cfg.buffer_m,'miny':ext5514['miny']-cfg.buffer_m,'maxy':ext5514['maxy']+cfg.buffer_m}
            buildings=paths['buildings']/'buildings.gpkg'
            buildings_report=download_ruian_buildings(ext5514, area_target, buildings, paths['tmp'], cfg.target_crs, logger=logger)
            assert_vector_ok(buildings, 'buildings')
            add_file_manifest(files,'buildings',buildings)
            source_records.append({'dataset':'ČÚZK RÚIAN StavebniObjekt','url':RUIAN_BUILDINGS_SERVICE,'layer_id':RUIAN_BUILDINGS_LAYER_ID,'method':'ArcGIS REST query, clipped to AOI'})
        cir_qa=None
        if cir_path:
            cir_qa={'cir_info':assert_raster_ok(cir_path)}
            if ortho_path:
                cir_qa['overlap_with_rgb_orthophoto']=compare_raster_georef(cir_path, ortho_path)
            if dem.exists():
                cir_qa['overlap_with_dem']=compare_raster_georef(cir_path, dem)
        # OOM-compatible display rasters are an overlay on top of the GIS pipeline.
        oom_display_rasters=[]
        try:
            logger.log('[OOM] Kontroluji kompatibilitu rastrových template výstupů')
            oom_display_rasters=create_oom_display_rasters(files, logger=logger)
            for rec in oom_display_rasters:
                if rec.get('display'):
                    p=Path(rec['display'])
                    assert_raster_ok(p)
                    add_file_manifest(files, rec.get('display_role') or (rec.get('source_role','raster')+'_oom'), p)
                elif rec.get('error'):
                    warnings.append(f"OOM display raster failed for {rec.get('source')}: {rec.get('error')}")
        except Exception as e:
            warnings.append(f'OOM compatibility check failed: {e!r}')
            logger.log(f'WARN OOM compatibility check failed: {e!r}')

        tiling_report=None
        if cfg.tiling:
            try:
                logger.log(f'[tiling] Rozděluji výstupy na dlaždice: {cfg.tiling}')
                tiling_extent=layer_extent(area_target)
                tiling_report=tile_manifest_files(paths['root'], files, cfg.tiling, tiling_extent, logger=logger)
                warnings.extend(tiling_report.get('warnings') or [])
            except Exception as e:
                raise PipelineError(f'Tiling requested but failed: {e!r}') from e

        # manifest/readme/zip
        logger.log('[8/8] QA + manifest + balení')
        versions={}
        for cmd in ['gdalinfo','pdal','proj','qgis_process']:
            try: versions[cmd]=run([cmd,'--version'],check=False).stdout.strip()[:500]
            except Exception as e: versions[cmd]=repr(e)
        manifest={
            'project_id':cfg.project_id,'created_at':start,'config':cfg.to_dict(),'gpx':gpx_meta,
            'area':{'target_info':area_info,'area_m2':area_m2,'area_km2':area_m2/1e6,'extent_5514':area_info_5514.get('extent')},
            'input_crs':'EPSG:4326 (GPX lon/lat)','working_crs':'EPSG:5514','output_crs':cfg.target_crs,
            'sources':source_records,'dmr_tiles':dmr_meta,'dmp_tiles':dmp_meta,'ortho_acquisition':ortho_acquisition,'cir_orthophoto':cir_orthophoto,'cir_qa':cir_qa,'buildings':buildings_report,'vegetation_height':vegetation_report,'oom_display_rasters':oom_display_rasters,'tiling':tiling_report,'contours_m':cfg.contours_m,'warnings':warnings,'files':files,'tool_versions':versions,
        }
        if cfg.generate_omap:
            apply_dated_template_filenames(paths['root'], manifest, logger=logger)
        manifest_path=paths['root']/'manifest.json'; write_json(manifest_path,manifest); add_file_manifest(files,'manifest',manifest_path)
        readme=paths['root']/'README.txt'; make_readme(cfg,manifest,readme); add_file_manifest(files,'readme',readme)
        if cfg.generate_oom_setup:
            try:
                logger.log('[OOM] Generuji OOM_SETUP.md/txt')
                manifest['files']=files
                oom_setup=generate_oom_setup(paths['root'], manifest, logger=logger)
                manifest['oom_setup']=oom_setup
                add_file_manifest(files,'oom_setup_md',Path(oom_setup['oom_setup_md']))
                add_file_manifest(files,'oom_setup_txt',Path(oom_setup['oom_setup_txt']))
                add_file_manifest(files,'oom_setup_meta',paths['root']/'oom_setup_meta.json')
            except Exception as e:
                warnings.append(f'OOM setup generation failed: {e!r}')
                logger.log(f'WARN OOM setup generation failed: {e!r}')
        if cfg.generate_omap:
            try:
                logger.log('[OOM] Generuji volitelný project.omap')
                manifest['files']=files
                omap_project=generate_omap_project(paths['root'], manifest, logger=logger)
                manifest['omap_project']=omap_project
                add_file_manifest(files,'project_omap',Path(omap_project['project_omap']))
            except Exception as e:
                warnings.append(f'OOM project.omap generation failed: {e!r}')
                logger.log(f'WARN OOM project.omap generation failed: {e!r}')
        # rewrite manifest with self entries included
        manifest['files']=files; write_json(manifest_path,manifest)
        zip_path=paths['root'].with_suffix('.zip')
        package_project(paths['root'],zip_path); assert_zip_ok(zip_path)
        drive_info=None
        if cfg.drive_upload:
            logger.log('[Drive] Nahrávám výstupy na Google Drive')
            drive_info = upload_project_tree(
                paths['root'], zip_path,
                root_folder_name=cfg.drive_root_folder,
                job_folder_name=cfg.drive_job_folder_name or cfg.project_id,
                logger=logger,
            )
            drive_summary_path = paths['root']/'drive_upload.json'
            write_json(drive_summary_path, drive_info)
            # Upload summary after it exists; this gives the Drive folder a machine-readable index of Drive IDs.
            from .drive_upload import upload_file
            summary_meta = upload_file(drive_summary_path, drive_info['job_folder']['id'])
            drive_info['drive_summary_file'] = {'id':summary_meta.get('id'), 'name':summary_meta.get('name'), 'webViewLink':summary_meta.get('webViewLink')}
            logger.log(f"[Drive] Hotovo: {drive_info['job_folder'].get('webViewLink')}")
        logger.log(f'Hotovo: {zip_path}')
        result={'project_root':str(paths['root']),'zip':str(zip_path),'manifest':str(manifest_path),'area_km2':area_m2/1e6,'warnings':warnings,'drive':drive_info,'local_outputs_deleted':False}
        if cfg.drive_upload and cfg.cleanup_local_after_drive:
            _safe_cleanup_local_outputs(paths['root'], zip_path, cfg.project_root, logger)
            result['local_outputs_deleted'] = True
            result['project_root'] = None
            result['zip'] = None
            result['manifest'] = None
        return result
    finally:
        logger.close()
