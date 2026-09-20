from __future__ import annotations
from pathlib import Path
import math, requests, json, hashlib, time
import xml.etree.ElementTree as ET
from .util import ensure_dir, run, write_json, sha256

DMR5G_IMAGE_URL = 'https://ags.cuzk.cz/arcgis2/rest/services/dmr5g/ImageServer/exportImage'
DMR5G_META_URL = 'https://ags.cuzk.cz/arcgis2/rest/services/dmr5g/ImageServer?f=pjson'
DMPOK_IMAGE_URL = 'https://ags.cuzk.gov.cz/arcgis2/rest/services/dmp_obrazova_korelace/ImageServer/exportImage'
DMPOK_META_URL = 'https://ags.cuzk.gov.cz/arcgis2/rest/services/dmp_obrazova_korelace/ImageServer?f=pjson'
ORTOFOTO_WMTS = 'https://ags.cuzk.cz/arcgis1/rest/services/ORTOFOTO/MapServer/WMTS/1.0.0/WMTSCapabilities.xml'
ORTOFOTO_WMS = 'https://ags.cuzk.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer?SERVICE=WMS&REQUEST=GetCapabilities'
ORTOARCHIV_WMS = 'https://geoportal.cuzk.cz/WMS_ORTOFOTO_ARCHIV/WMService.aspx?SERVICE=WMS&REQUEST=GetCapabilities'
ORTOCIR_WMS_BASE = 'https://geoportal.cuzk.cz/WMS_ORTOFOTO_CIR/WMService.aspx?'
ORTOCIR_WMS = ORTOCIR_WMS_BASE + 'SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0'

class SourceError(RuntimeError): pass

def fetch_json(url: str):
    r=requests.get(url,timeout=30,headers={'User-Agent':'HermesAgent orimap-prep'})
    r.raise_for_status(); return r.json()

def service_metadata():
    return {
        'dmr5g_imageserver': fetch_json(DMR5G_META_URL),
        'dmpok_imageserver': fetch_json(DMPOK_META_URL),
        'ortofoto_wmts_url': ORTOFOTO_WMTS,
        'ortofoto_wms_url': ORTOFOTO_WMS,
        'ortoarchiv_wms_url': ORTOARCHIV_WMS,
        'ortocir_wms_url': ORTOCIR_WMS,
    }

def _intersects(a: dict, b: dict) -> bool:
    return not (a['maxx'] < b['minx'] or a['minx'] > b['maxx'] or a['maxy'] < b['miny'] or a['miny'] > b['maxy'])

def _layer_bbox_lonlat(layer_el, ns: dict) -> dict | None:
    ex=layer_el.find('wms:EX_GeographicBoundingBox', ns)
    if ex is not None:
        try:
            return {
                'minx': float(ex.findtext('wms:westBoundLongitude', namespaces=ns)),
                'maxx': float(ex.findtext('wms:eastBoundLongitude', namespaces=ns)),
                'miny': float(ex.findtext('wms:southBoundLatitude', namespaces=ns)),
                'maxy': float(ex.findtext('wms:northBoundLatitude', namespaces=ns)),
            }
        except Exception:
            return None
    return None

def ortocir_capabilities() -> dict:
    r=requests.get(ORTOCIR_WMS,timeout=40,headers={'User-Agent':'HermesAgent orimap-prep'})
    r.raise_for_status()
    root=ET.fromstring(r.content)
    ns={'wms':'http://www.opengis.net/wms'}
    layers=[]
    for el in root.findall('.//wms:Layer', ns):
        name=el.findtext('wms:Name', namespaces=ns)
        title=el.findtext('wms:Title', namespaces=ns)
        if name and name.isdigit():
            bbox=_layer_bbox_lonlat(el, ns)
            layers.append({'name':name,'year':int(name),'title':title,'bbox_lonlat':bbox})
    return {
        'url': ORTOCIR_WMS,
        'service_title': root.findtext('wms:Service/wms:Title', namespaces=ns),
        'abstract': root.findtext('wms:Service/wms:Abstract', namespaces=ns),
        'layers': sorted(layers, key=lambda x: x['year']),
    }

def select_ortocir_layer(extent_lonlat: dict) -> dict:
    caps=ortocir_capabilities()
    hits=[l for l in caps['layers'] if l.get('bbox_lonlat') and _intersects(extent_lonlat, l['bbox_lonlat'])]
    if not hits:
        raise SourceError(f'No ČÚZK Ortofoto CIR WMS yearly layer intersects AOI lon/lat extent {extent_lonlat}')
    selected=max(hits, key=lambda x: x['year'])
    return {'selected':selected,'intersecting_layers':hits,'capabilities':{'url':caps['url'],'service_title':caps.get('service_title'),'layer_years':[l['year'] for l in caps['layers']]}}

def _tile_ranges(minx,miny,maxx,maxy,pixel_size,max_px):
    width=maxx-minx; height=maxy-miny
    nx=max(1, math.ceil(width/(pixel_size*max_px)))
    ny=max(1, math.ceil(height/(pixel_size*max_px)))
    for ix in range(nx):
        x0=minx+width*ix/nx; x1=minx+width*(ix+1)/nx
        for iy in range(ny):
            y0=miny+height*iy/ny; y1=miny+height*(iy+1)/ny
            yield ix,iy,x0,y0,x1,y1

def _download_imageserver_tiles(dataset_name: str, image_url: str, extent5514: dict, cache_root: Path, pixel_size: float, max_px: int, *, logger=None, interpolation='RSP_BilinearInterpolation'):
    src_dir=ensure_dir(cache_root/'cuzk'/dataset_name)
    minx,maxx=extent5514['minx'],extent5514['maxx']; miny,maxy=extent5514['miny'],extent5514['maxy']
    tiles=[]; meta=[]
    for ix,iy,x0,y0,x1,y1 in _tile_ranges(minx,miny,maxx,maxy,pixel_size,max_px):
        sx=max(1, int(math.ceil((x1-x0)/pixel_size)))
        sy=max(1, int(math.ceil((y1-y0)/pixel_size)))
        key=f"{dataset_name}_5514_{x0:.2f}_{y0:.2f}_{x1:.2f}_{y1:.2f}_{sx}x{sy}.tif".replace('-','m').replace('.','p')
        path=src_dir/key
        if not path.exists() or path.stat().st_size < 1024:
            if logger: logger.log(f"Downloading {dataset_name} tile {ix},{iy} size {sx}x{sy}")
            params={
                'f':'image','format':'tiff','bbox':f'{x0},{y0},{x1},{y1}', 'bboxSR':'5514','imageSR':'5514',
                'size':f'{sx},{sy}','pixelType':'F32','interpolation':interpolation,'noData':'-9999'
            }
            r=requests.get(image_url,params=params,timeout=180,headers={'User-Agent':'HermesAgent orimap-prep'})
            if r.status_code != 200 or not r.content.startswith((b'II*', b'MM\x00*')):
                raise SourceError(f"{dataset_name} export failed HTTP {r.status_code}: {r.text[:500]}")
            path.write_bytes(r.content)
        tiles.append(path)
        meta.append({'path':str(path),'bbox':[x0,y0,x1,y1],'size':[sx,sy],'pixel_size_m':pixel_size,'sha256':sha256(path),'source_url':image_url})
    write_json(src_dir/'cache_manifest.json', {'dataset':dataset_name,'tiles':meta})
    return tiles, meta


def download_dmr5g_tiles(extent5514: dict, cache_root: Path, pixel_size: float=1.0, max_px: int=1800, logger=None):
    return _download_imageserver_tiles('dmr5g_imageserver', DMR5G_IMAGE_URL, extent5514, cache_root, pixel_size, max_px, logger=logger)

def download_dmpok_tiles(extent5514: dict, cache_root: Path, pixel_size: float=0.5, max_px: int=1800, logger=None):
    return _download_imageserver_tiles('dmpok_imageserver', DMPOK_IMAGE_URL, extent5514, cache_root, pixel_size, max_px, logger=logger)

def build_dem_from_tiles(tiles: list[Path], area_target: Path, target_crs: str, out_dem: Path, temp_dir: Path, logger=None):
    return build_raster_from_tiles(tiles, area_target, target_crs, out_dem, temp_dir, logger=logger, label='DEM')

def build_raster_from_tiles(tiles: list[Path], area_target: Path, target_crs: str, out_raster: Path, temp_dir: Path, logger=None, label='raster'):
    ensure_dir(temp_dir); ensure_dir(out_raster.parent)
    if len(tiles)==1:
        src=str(tiles[0])
    else:
        vrt=temp_dir/(label.lower().replace(' ','_') + '_merged.vrt')
        run(['gdalbuildvrt', str(vrt)] + [str(t) for t in tiles])
        src=str(vrt)
    # cutline is in target CRS; let gdalwarp reproject from 5514 to target and crop.
    cmd=['gdalwarp','-overwrite','-s_srs','EPSG:5514','-t_srs',target_crs,
         '-cutline',str(area_target),'-cl','area','-crop_to_cutline','-dstnodata','-9999',
         '-r','bilinear','-of','GTiff','-co','TILED=YES','-co','COMPRESS=DEFLATE','-co','PREDICTOR=3',src,str(out_raster)]
    if logger: logger.log(f'Running gdalwarp for {label} clip/reproject')
    run(cmd)
    return out_raster

def build_dmp_from_tiles(tiles: list[Path], area_target: Path, target_crs: str, out_dmp: Path, temp_dir: Path, logger=None):
    return build_raster_from_tiles(tiles, area_target, target_crs, out_dmp, temp_dir, logger=logger, label='DMP OK')

def estimate_current_orthophoto_acquisition(extent_lonlat: dict | None = None):
    """Return best available acquisition-year metadata for ČÚZK current ortho.

    ČÚZK current Ortofoto ČR product currently advertises color aerial
    photography from 2024–2025. The public ORTOFOTO MapServer/WMS exposes a
    polygon layer with an `ortofoto` field, but query/identify operations are
    disabled, so this function records the official product range and estimates
    west/east update zone from longitude when a lon/lat extent is available.
    This is explicit metadata, not hidden precision.
    """
    meta = {
        'dataset': 'ČÚZK Ortofoto ČR current',
        'official_product_years': '2024-2025',
        'source': 'https://geoportal.cuzk.cz/Default.aspx?mode=TextMeta&side=ortofoto&metadataID=CZ-CUZK-ORTOFOTO-R&menu=233',
        'method': 'official product years; estimated west/east update zone because public service does not support per-area query/identify',
        'acquisition_year': None,
        'confidence': 'range_only',
    }
    if extent_lonlat:
        mid_lon = (extent_lonlat['minx'] + extent_lonlat['maxx']) / 2.0
        # ČÚZK updates western/eastern halves in alternating years. For the
        # current 2024-2025 product, west is 2025 and east is 2024. The exact
        # boundary is maintained by ČÚZK in the update map; this heuristic is
        # safe for far-west/far-east areas and marked as estimated.
        if mid_lon < 14.6:
            meta.update({'acquisition_year': 2025, 'zone': 'west', 'confidence': 'estimated_from_cuzk_update_zone'})
        elif mid_lon > 15.4:
            meta.update({'acquisition_year': 2024, 'zone': 'east', 'confidence': 'estimated_from_cuzk_update_zone'})
        else:
            meta.update({'zone': 'boundary_uncertain', 'confidence': 'range_only'})
    return meta


def download_ortho_wms(extent_target: dict, target_crs: str, out_path: Path, pixel_size: float=0.5, logger=None):
    # Optional phase-2 helper: use official ČÚZK WMS through GDAL WMS XML, clipped to bbox only.
    ensure_dir(out_path.parent)
    width=max(1,int(math.ceil((extent_target['maxx']-extent_target['minx'])/pixel_size)))
    height=max(1,int(math.ceil((extent_target['maxy']-extent_target['miny'])/pixel_size)))
    width=min(width,5000); height=min(height,5000)
    xml=out_path.with_suffix('.wms.xml')
    xml.write_text(f'''<GDAL_WMS>
  <Service name="WMS">
    <Version>1.3.0</Version>
    <ServerUrl>https://ags.cuzk.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer?</ServerUrl>
    <Layers>0</Layers>
    <CRS>{target_crs}</CRS>
    <ImageFormat>image/png</ImageFormat>
  </Service>
  <DataWindow>
    <UpperLeftX>{extent_target['minx']}</UpperLeftX>
    <UpperLeftY>{extent_target['maxy']}</UpperLeftY>
    <LowerRightX>{extent_target['maxx']}</LowerRightX>
    <LowerRightY>{extent_target['miny']}</LowerRightY>
    <SizeX>{width}</SizeX><SizeY>{height}</SizeY>
  </DataWindow>
  <BandsCount>3</BandsCount>
</GDAL_WMS>''', encoding='utf-8')
    if logger: logger.log('Downloading orthophoto via ČÚZK WMS/GDAL')
    run(['gdal_translate','-of','GTiff','-co','TILED=YES','-co','COMPRESS=JPEG',str(xml),str(out_path)])
    return out_path

def download_ortocir_wms(extent_target: dict, extent_lonlat: dict, area_target: Path, target_crs: str, out_path: Path, cache_root: Path, pixel_size: float=0.5, logger=None):
    """Download ČÚZK Ortofoto CIR from official WMS-ORTOCIR yearly layer.

    ČÚZK product metadata advertises JP2/SM5 distribution, but CIR public file
    distribution is exposed through a request workflow, not a verified public
    ATOM/direct JP2 endpoint. This function uses the official public WMS and
    caches the project bbox export before cutline clipping.
    """
    ensure_dir(out_path.parent)
    sel=select_ortocir_layer(extent_lonlat)
    layer=sel['selected']['name']
    width=max(1,int(math.ceil((extent_target['maxx']-extent_target['minx'])/pixel_size)))
    height=max(1,int(math.ceil((extent_target['maxy']-extent_target['miny'])/pixel_size)))
    width=min(width,7000); height=min(height,7000)
    cache_dir=ensure_dir(cache_root/'cuzk'/'ortofoto_cir_wms')
    key_data={'layer':layer,'target_crs':target_crs,'extent':extent_target,'pixel_size':pixel_size,'size':[width,height]}
    key=hashlib.sha256(json.dumps(key_data,sort_keys=True).encode('utf-8')).hexdigest()[:24]
    cached=cache_dir/f'ortocir_{layer}_{key}.tif'
    xml=cache_dir/f'ortocir_{layer}_{key}.wms.xml'
    if not cached.exists() or cached.stat().st_size < 1024:
        xml.write_text(f'''<GDAL_WMS>
  <Service name="WMS">
    <Version>1.3.0</Version>
    <ServerUrl>{ORTOCIR_WMS_BASE}</ServerUrl>
    <Layers>{layer}</Layers>
    <CRS>{target_crs}</CRS>
    <ImageFormat>image/jpeg</ImageFormat>
  </Service>
  <DataWindow>
    <UpperLeftX>{extent_target['minx']}</UpperLeftX>
    <UpperLeftY>{extent_target['maxy']}</UpperLeftY>
    <LowerRightX>{extent_target['maxx']}</LowerRightX>
    <LowerRightY>{extent_target['miny']}</LowerRightY>
    <SizeX>{width}</SizeX><SizeY>{height}</SizeY>
  </DataWindow>
  <BandsCount>3</BandsCount>
</GDAL_WMS>''', encoding='utf-8')
        if logger: logger.log(f'Downloading ČÚZK CIR ortofoto WMS layer {layer} to cache')
        run(['gdal_translate','-of','GTiff','-co','TILED=YES','-co','COMPRESS=JPEG',str(xml),str(cached)])
    else:
        if logger: logger.log(f'Using cached ČÚZK CIR ortofoto WMS layer {layer}: {cached}')
    if logger: logger.log('Clipping CIR ortofoto to project polygon')
    run(['gdalwarp','-overwrite','-s_srs',target_crs,'-t_srs',target_crs,
         '-cutline',str(area_target),'-cl','area','-crop_to_cutline','-dstalpha',
         '-r','bilinear','-of','GTiff','-co','TILED=YES','-co','COMPRESS=DEFLATE',
         '-co','PHOTOMETRIC=RGB',str(cached),str(out_path)])
    meta={
        'product':'cir_orthophoto',
        'provider':'ČÚZK',
        'source_dataset':'WMS-ORTOCIR / Ortofoto CIR',
        'source_service':ORTOCIR_WMS_BASE,
        'source_layer':layer,
        'source_files':[str(cached)],
        'source_crs':target_crs,
        'target_crs':target_crs,
        'source_resolution':'official CIR source pixel since 2018: approx. 0.20 m; WMS export resampled',
        'output_resolution_m':pixel_size,
        'imagery_year':int(layer),
        'download_date':time.strftime('%Y-%m-%d'),
        'processing':'official WMS GetMap via GDAL WMS -> cached GeoTIFF bbox -> gdalwarp cutline/crop_to_cutline with alpha',
        'output_file':str(out_path),
        'oom_output_file':str(out_path),
        'cache_key':key,
        'cache_size_bytes':cached.stat().st_size if cached.exists() else None,
        'capabilities':sel['capabilities'],
        'intersecting_layers':[{'year':h['year'],'bbox_lonlat':h['bbox_lonlat']} for h in sel['intersecting_layers']],
        'warnings':[],
    }
    write_json(cache_dir/f'ortocir_{layer}_{key}.json', meta)
    return out_path, meta
