from __future__ import annotations
from pathlib import Path
import math
import re
import shutil
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pyproj import CRS, Transformer

NS='http://openorienteering.org/apps/mapper/xml/v2'
ET.register_namespace('', NS)

TEMPLATE_PRIORITY=[
    ('ortofoto_current','ORTOFOTO RGB',1.0),
    ('ortofoto_cir','ORTOFOTO CIR',1.0),
    ('buildings','RUIAN BUILDINGS',1.0),
    ('hillshade','HILLSHADE',1.0),
    ('hillshade_multidirectional','MULTIDIRECTIONAL HILLSHADE',1.0),
    ('slope_oom','SLOPE DISPLAY',1.0),
    ('vegetation_height_oom','VEGETATION HEIGHT',1.0),
    ('surface_height_raw_oom','SURFACE HEIGHT DISPLAY',1.0),
    ('dem_oom','DEM DISPLAY',1.0),
    ('contours_5m','CONTOURS 5 M',1.0),
    ('contours_1m','CONTOURS 1 M',1.0),
    ('contours_25m','CONTOURS 25 M',1.0),
]

class OmapBuilderError(RuntimeError):
    pass

def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]

def symbol_set_path(map_type: str|None, map_scale: int) -> Path:
    if map_type == 'sprint' or map_scale <= 5000:
        return repo_root()/'resources'/'symbol_sets'/'4000'/'ISSprOM 2019_4000.omap'
    if map_scale >= 15000:
        return repo_root()/'resources'/'symbol_sets'/'15000'/'ISOM 2017-2_15000.omap'
    return repo_root()/'resources'/'symbol_sets'/'10000'/'ISOM 2017-2_10000.omap'

def symbol_set_name(path: Path) -> str:
    return path.stem

def _ns(tag: str) -> str:
    return f'{{{NS}}}{tag}'

def _files_by_role(manifest: dict) -> dict[str, Path]:
    out={}
    for f in manifest.get('files',[]):
        role=f.get('role'); path=f.get('path')
        if role and path:
            out[role]=Path(path)
    return out

def _relative_to_project(path: Path, project_root: Path) -> str:
    resolved=path.resolve()
    root=project_root.resolve()
    try:
        rel=resolved.relative_to(root)
    except ValueError as e:
        raise OmapBuilderError(f'Template outside project root: {path}') from e
    if any(part in ('..','') for part in rel.parts):
        raise OmapBuilderError(f'Unsafe relative path: {rel}')
    return rel.as_posix()

def _template_year_label(role: str, manifest: dict) -> str:
    sources=manifest.get('sources') or []
    if role in ('ortofoto_current','ortofoto_cir'):
        for src in sources:
            acq=src.get('acquisition') or {}
            year=acq.get('acquisition_year') or acq.get('year')
            month=acq.get('acquisition_month') or acq.get('month')
            if year:
                return f'{year}-{int(month):02d}' if month else str(year)
        # CIR manifests usually record the chosen WMS layer year in cir_qa/source metadata.
        for key in ('cir_qa','ortho_metadata','ortocir','cir_orthophoto'):
            node=manifest.get(key) or {}
            year=node.get('imagery_year') or node.get('year') or node.get('layer_year') or (node.get('selected') or {}).get('year')
            month=node.get('month') or node.get('acquisition_month')
            if year:
                return f'{year}-{int(month):02d}' if month else str(year)
    if role in ('dem','dem_oom','hillshade','hillshade_multidirectional','slope','slope_oom') or role.startswith('contours_'):
        return 'DMR5G 2009-2013'
    if role in ('dmp_ok','dmp_ok_oom','dmp_ok_aligned_to_dem','dmp_ok_aligned_to_dem_oom'):
        return 'DMP OK'
    if role in ('vegetation_height','vegetation_height_oom','vegetation_height_classified','surface_height_raw','surface_height_raw_oom'):
        for src in sources:
            name=(src.get('dataset') or '').lower()
            if 'dmp' in name:
                acq=src.get('acquisition') or src.get('metadata_summary') or {}
                year=acq.get('acquisition_year') or acq.get('year') or acq.get('creation_year')
                if year:
                    return f'DMP {year}'
        return 'DMP OK'
    if role == 'buildings':
        return 'RUIAN'
    return ''

def _slug(s: str) -> str:
    s=s.lower()
    s=s.replace('č','c').replace('ú','u').replace('ů','u').replace('ž','z').replace('š','s').replace('ř','r').replace('ď','d').replace('ť','t').replace('ň','n').replace('á','a').replace('é','e').replace('ě','e').replace('í','i').replace('ý','y').replace('ó','o')
    s=re.sub(r'[^a-z0-9-]+','_',s).strip('_-')
    return re.sub(r'_+','_',s)

def _file_suffix_for_role(role: str, manifest: dict) -> str|None:
    project_date=(manifest.get('config') or {}).get('project_date') or (manifest.get('created_at','')[:10] or 'unknown_date')
    year=_template_year_label(role, manifest)
    if role == 'ortofoto_current':
        return _slug(f'cuzk ortofoto rgb {year}')
    if role == 'ortofoto_cir':
        return _slug(f'cuzk ortofoto cir {year}')
    if role in ('dem','dem_oom'):
        return _slug(f'cuzk {year}')
    if role in ('hillshade','hillshade_multidirectional','slope','slope_oom'):
        return _slug(f'derived from cuzk {year}')
    if role.startswith('contours_'):
        return _slug(f'derived from cuzk {year}')
    if role in ('dmp_ok','dmp_ok_oom','dmp_ok_aligned_to_dem','dmp_ok_aligned_to_dem_oom'):
        return _slug(f'cuzk dmp ok {project_date}')
    if role in ('surface_height_raw','surface_height_raw_oom','vegetation_height','vegetation_height_oom','vegetation_height_classified'):
        return _slug(f'derived {project_date} from cuzk dmp ok and cuzk dmr5g 2009-2013')
    if role == 'buildings':
        return _slug(f'cuzk ruian stavebni objekt {project_date}')
    return None

def _unique_target(path: Path, suffix: str) -> Path:
    marker=f'__{suffix}'
    if path.stem.endswith(marker):
        return path
    target=path.with_name(f'{path.stem}{marker}{path.suffix}')
    if not target.exists() or target.resolve() == path.resolve():
        return target
    i=2
    while True:
        candidate=path.with_name(f'{path.stem}{marker}_{i}{path.suffix}')
        if not candidate.exists():
            return candidate
        i += 1

def _rename_sidecars(old: Path, new: Path):
    sidecars=[old.with_name(old.name + '.aux.xml')]
    if old.suffix.lower() in ('.tif','.tiff'):
        sidecars.append(old.with_suffix('.wms.xml'))
    for side in sidecars:
        if side.exists():
            side_target=new.with_name(new.name + '.aux.xml') if side.name.endswith('.aux.xml') else new.with_suffix(side.suffix)
            side.rename(side_target)

def apply_dated_template_filenames(project_root: Path, manifest: dict, *, logger=None) -> list[dict]:
    """Rename geospatial layer files used as OOM podklady to include source/date.

    Mutates manifest['files'] and manifest['oom_display_rasters'] path fields so
    downstream OOM_SETUP, project.omap, ZIP, and Drive upload use the new names.
    """
    project_root=Path(project_root)
    renames=[]
    path_updates={}
    for f in manifest.get('files',[]):
        role=f.get('role'); raw=f.get('path')
        suffix=_file_suffix_for_role(role or '', manifest)
        if not role or not raw or not suffix:
            continue
        old=Path(raw)
        if not old.exists() or old.parent == project_root:
            continue
        new=_unique_target(old, suffix)
        if new == old:
            f['path']=str(new)
            continue
        old.rename(new)
        _rename_sidecars(old, new)
        path_updates[str(old)]=str(new)
        f['path']=str(new)
        f['size']=new.stat().st_size if new.exists() else f.get('size')
        if new.exists() and new.is_file():
            try:
                from .util import sha256
                f['sha256']=sha256(new)
            except Exception:
                pass
        renames.append({'role':role,'old':str(old),'new':str(new)})
        if logger:
            logger.log(f'[OOM] Renamed podklad {old.name} -> {new.name}')
    for rec in manifest.get('oom_display_rasters',[]) or []:
        for key in ('source','display'):
            if rec.get(key) in path_updates:
                rec[key]=path_updates[rec[key]]
        for key in ('source_summary','display_summary'):
            if isinstance(rec.get(key), dict) and rec[key].get('path') in path_updates:
                rec[key]['path']=path_updates[rec[key]['path']]
    if renames:
        manifest['dated_layer_renames']=renames
    return renames

def collect_templates(project_root: Path, manifest: dict) -> list[dict]:
    files=_files_by_role(manifest)
    templates=[]
    for role,label,opacity in TEMPLATE_PRIORITY:
        p=files.get(role)
        if p and p.exists():
            rel=_relative_to_project(p, project_root)
            dated=_template_year_label(role, manifest)
            display_label=f'{label} {dated}'.strip()
            templates.append({'role':role,'label':display_label,'path':rel,'name':display_label,'file_name':Path(rel).name,'opacity':opacity})
    # Add all contour roles not covered by common intervals.
    seen={t['role'] for t in templates}
    for role,p in sorted(files.items()):
        if role.startswith('contours_') and role not in seen and p.exists():
            rel=_relative_to_project(p, project_root)
            templates.append({'role':role,'label':role.upper(), 'path':rel, 'name':role.upper(), 'file_name':Path(rel).name, 'opacity':1.0})
            seen.add(role)
    # Add tiled outputs after the base templates. These keep source_role metadata
    # so one .omap can contain the whole tablet/mobile grid when requested.
    priority={role:(label, opacity) for role,label,opacity in TEMPLATE_PRIORITY}
    for rec in manifest.get('files',[]) or []:
        role=rec.get('role')
        if not rec.get('tile') or not role or role in seen:
            continue
        source_role=rec.get('source_role') or role.rsplit('_',1)[0]
        p=Path(rec.get('path') or '')
        if not p.exists():
            continue
        if source_role in priority:
            label, opacity=priority[source_role]
        elif source_role.startswith('contours_'):
            label, opacity=(source_role.upper(), 1.0)
        else:
            continue
        rel=_relative_to_project(p, project_root)
        name=f'{label} {rec.get("tile")}'.strip()
        templates.append({'role':role,'label':name, 'path':rel, 'name':name, 'file_name':Path(rel).name, 'opacity':opacity})
        seen.add(role)
    return templates

def _text_child(parent, tag, text, **attrs):
    el=ET.SubElement(parent, _ns(tag), {k:str(v) for k,v in attrs.items()})
    el.text=text
    return el

def _epsg_code(crs_code: str|None) -> str|None:
    if not crs_code:
        return None
    m=re.fullmatch(r'(?i)EPSG\s*:?\s*(\d+)', str(crs_code).strip())
    return m.group(1) if m else None

def _proj4(crs_code: str) -> str:
    epsg=_epsg_code(crs_code)
    if epsg:
        # This is the native CRS template used by OOM's "by EPSG code" selector.
        return f'+init=epsg:{epsg}'
    crs=CRS.from_user_input(crs_code)
    return crs.to_proj4(version=4)

def _center_projected(manifest: dict) -> tuple[float,float]:
    ext=manifest.get('area',{}).get('target_info',{}).get('extent') or manifest.get('area',{}).get('extent_5514')
    if isinstance(ext, dict):
        return (float(ext['minx']+ext['maxx'])/2, float(ext['miny']+ext['maxy'])/2)
    if ext and len(ext)>=4:
        # OGR extent convention: minx, maxx, miny, maxy.
        return ((float(ext[0])+float(ext[1]))/2, (float(ext[2])+float(ext[3]))/2)
    return (0.0,0.0)

def _extent_dict(manifest: dict) -> dict|None:
    ext=manifest.get('area',{}).get('target_info',{}).get('extent') or manifest.get('area',{}).get('extent_5514')
    if isinstance(ext, dict):
        return {k: float(ext[k]) for k in ('minx','maxx','miny','maxy')}
    if ext and len(ext)>=4:
        return {'minx':float(ext[0]), 'maxx':float(ext[1]), 'miny':float(ext[2]), 'maxy':float(ext[3])}
    return None

def _projected_to_wgs84(target_crs: str, x: float, y: float) -> tuple[float,float]:
    lon,lat=Transformer.from_crs(target_crs, 'EPSG:4326', always_xy=True).transform(x,y)
    return float(lat), float(lon)

def _wgs84_to_projected(target_crs: str, lat: float, lon: float) -> tuple[float,float]:
    x,y=Transformer.from_crs('EPSG:4326', target_crs, always_xy=True).transform(lon,lat)
    return float(x), float(y)

def _oom_grid_convergence(target_crs: str, lat: float, lon: float, delta: float=1000.0) -> float:
    # Port of OOM Georeferencing::updateGridCompensation(): build a local
    # stereographic CRS around the geographic reference point, sample 1 km
    # W/E and S/N baselines, then compare their projected-coordinate axes.
    local=f'+proj=sterea +lat_0={lat:f} +lon_0={lon:f} +ellps=WGS84 +units=m'
    to_geo=Transformer.from_crs(CRS.from_proj4(local), 'EPSG:4326', always_xy=True)
    points={}
    for key,(lx,ly) in {
        'east':(delta/2,0), 'west':(-delta/2,0), 'north':(0,delta/2), 'south':(0,-delta/2)
    }.items():
        plon,plat=to_geo.transform(lx,ly)
        px,py=_wgs84_to_projected(target_crs, plat, plon)
        points[key]=(px,py)
    d_northing_dy=(points['north'][1]-points['south'][1])/delta
    d_easting_dy=(points['north'][0]-points['south'][0])/delta
    d_northing_dx=(points['east'][1]-points['west'][1])/delta
    d_easting_dx=(points['east'][0]-points['west'][0])/delta
    determinant=d_easting_dx*d_northing_dy-d_northing_dx*d_easting_dy
    if determinant < 1e-11:
        return 0.0
    return math.degrees(math.atan2(d_northing_dx-d_easting_dy, d_easting_dx+d_northing_dy))

def _oom_round_declination(value: float) -> float:
    # Exact OOM implementation: floor(value*100+0.5)/100.0
    return math.floor(value*100.0+0.5)/100.0

def _declination_values(manifest: dict, target_crs: str, lat: float|None=None, lon: float|None=None) -> tuple[str|None, str|None, float|None]:
    setup=manifest.get('oom_setup') or {}
    decl=setup.get('declination') or {}
    d=decl.get('declination_deg_oom')
    east_positive=decl.get('declination_deg_east_positive')
    if d is None and east_positive is not None:
        # BGS/WMM returns signed east-positive declination; OOM stores the opposite sign.
        d=-float(east_positive)
    if d is None:
        # Legacy signed value only; do not fall back to abs_degrees.
        d=decl.get('declination_deg')
    if d is None:
        return None, None, None
    try:
        conv=_oom_grid_convergence(target_crs, lat, lon) if lat is not None and lon is not None else None
    except Exception:
        conv=None
    if conv is None:
        conv=(setup.get('grid_convergence') or {}).get('meridian_convergence_deg')
    try:
        declination=_oom_round_declination(float(d))
        convergence=float(conv) if conv is not None else 0.0
        gr=_oom_round_declination(declination-convergence)  # OOM: convergence = declination - grivation.
        return f'{declination:.2f}', f'{gr:.2f}', convergence
    except Exception:
        return str(d), None, None

def _content_parent(root):
    return root.find(_ns('barrier')) or root

def generate_omap_project(project_root: Path, manifest: dict, *, logger=None) -> dict:
    project_root=Path(project_root)
    cfg=manifest.get('config',{})
    scale=int(cfg.get('map_scale') or 10000)
    target_crs=cfg.get('target_crs') or manifest.get('output_crs') or 'EPSG:5514'
    apply_dated_template_filenames(project_root, manifest, logger=logger)
    templates=collect_templates(project_root, manifest)
    if not templates:
        raise OmapBuilderError('No existing OOM template files found in manifest')
    symbol=symbol_set_path(cfg.get('map_type'), scale)
    if not symbol.exists():
        raise OmapBuilderError(f'Missing bundled OOM symbol set: {symbol}')
    omap_name = re.sub(r'[^A-Za-z0-9._-]+', '-', str(manifest.get('project_id') or project_root.name)).strip('.-_') or 'project'
    out=project_root/f'{omap_name}.omap'
    shutil.copyfile(symbol, out)
    tree=ET.parse(out); root=tree.getroot()
    content_parent=_content_parent(root)
    georef=root.find(_ns('georeferencing'))
    if georef is None:
        georef=ET.Element(_ns('georeferencing'))
        root.insert(1, georef)
    cx,cy=_center_projected(manifest)
    lat,lon=_projected_to_wgs84(target_crs, cx, cy)
    decl, griv, convergence=_declination_values(manifest, target_crs, lat, lon)
    georef.clear(); georef.set('scale', str(scale))
    if decl: georef.set('declination', decl)
    if griv: georef.set('grivation', griv)
    ET.SubElement(georef, _ns('ref_point'), {'x':'0','y':'0'})
    epsg=_epsg_code(target_crs)
    if epsg:
        projected=ET.SubElement(georef, _ns('projected_crs'), {'id':'EPSG'})
        _text_child(projected, 'spec', f'+init=epsg:{epsg}', language='PROJ.4')
        _text_child(projected, 'parameter', epsg)
    else:
        projected=ET.SubElement(georef, _ns('projected_crs'), {'id':'PROJ.4'})
        _text_child(projected, 'spec', _proj4(target_crs), language='PROJ.4')
        _text_child(projected, 'parameter', _proj4(target_crs))
    ET.SubElement(projected, _ns('ref_point'), {'x':f'{cx:.6f}','y':f'{cy:.6f}'})
    geographic=ET.SubElement(georef, _ns('geographic_crs'), {'id':'Geographic coordinates'})
    _text_child(geographic, 'spec', '+proj=latlong +datum=WGS84', language='PROJ.4')
    ET.SubElement(geographic, _ns('ref_point_deg'), {'lat':f'{lat:.8f}','lon':f'{lon:.8f}'})

    parts=content_parent.find(_ns('parts'))
    if parts is None:
        parts=ET.SubElement(content_parent, _ns('parts'), {'count':'1','current':'0'})
        part=ET.SubElement(parts, _ns('part'), {'name':'default layer'})
    else:
        part=parts.find(_ns('part'))
        if part is None:
            part=ET.SubElement(parts, _ns('part'), {'name':'default layer'})
        parts.set('count', str(len(parts.findall(_ns('part')))))
        if 'current' not in parts.attrib:
            parts.set('current','0')
    for part in parts.findall(_ns('part')):
        objects=part.find(_ns('objects'))
        if objects is None:
            objects=ET.SubElement(part, _ns('objects'), {'count':'0'})
        else:
            objects.clear(); objects.set('count','0')

    old=content_parent.find(_ns('templates'))
    if old is not None: content_parent.remove(old)
    templates_el=ET.Element(_ns('templates'), {'count':str(len(templates)), 'first_front_template':str(len(templates))})
    for t in templates:
        tel=ET.SubElement(templates_el, _ns('template'), {'open':'true','name':t['name'],'path':t['path'],'relpath':t['path'],'georef':'true'})
        # Keep each source file's own georeferencing. For georeferenced templates,
        # OOM can read the raster/vector CRS directly; this metadata only states
        # the map CRS for compatibility and does not reposition the source data.
        _text_child(tel, 'crs_spec', _proj4(target_crs))
    ET.SubElement(templates_el, _ns('defaults'), {'use_meters_per_pixel':'true','meters_per_pixel':'0','dpi':'0','scale':'0'})
    # Insert before view/print barrier tail if possible.
    colors=content_parent.find(_ns('colors'))
    if colors is not None and colors in list(content_parent):
        insert_at=list(content_parent).index(colors)+1
    else:
        parts=content_parent.find(_ns('parts'))
        insert_at=list(content_parent).index(parts)+1 if parts is not None and parts in list(content_parent) else len(content_parent)
    content_parent.insert(insert_at, templates_el)

    view=content_parent.find(_ns('view'))
    if view is None:
        view=ET.SubElement(content_parent, _ns('view'))
        ET.SubElement(view, _ns('grid'), {'color':'#646464','display':'0','alignment':'0','additional_rotation':'0','unit':'1','h_spacing':'500','v_spacing':'500','h_offset':'0','v_offset':'0','snapping_enabled':'true'})
        mv=ET.SubElement(view, _ns('map_view'), {'zoom':'1','rotation':'0','position_x':'0','position_y':'0','view_x':'0','view_y':'0','drag_offset_x':'0','drag_offset_y':'0'})
        ET.SubElement(mv, _ns('map'), {'opacity':'1','visible':'true'})
    mv=view.find(_ns('map_view'))
    if mv is None:
        mv=ET.SubElement(view, _ns('map_view'), {'zoom':'1','position_x':'0','position_y':'0'})
        ET.SubElement(mv, _ns('map'), {'opacity':'1','visible':'true'})
    old_refs=mv.find(_ns('templates'))
    if old_refs is not None: mv.remove(old_refs)
    refs=ET.SubElement(mv, _ns('templates'), {'count':str(len(templates))})
    for i,t in enumerate(templates):
        ET.SubElement(refs, _ns('ref'), {'template':str(i),'visible':'true','opacity':f'{t["opacity"]:.2f}'.rstrip('0').rstrip('.')})

    xml=ET.tostring(root, encoding='utf-8')
    pretty=minidom.parseString(xml).toprettyxml(indent='  ', encoding='UTF-8')
    out.write_bytes(pretty)
    validation=validate_omap_project(out, project_root)
    if not validation['ok']:
        raise OmapBuilderError(f'Generated project.omap failed validation: {validation}')
    return {
        'project_omap':str(out),
        'symbol_set':symbol_set_name(symbol),
        'symbol_set_source':str(symbol),
        'templates':templates,
        'validation':validation,
        'method':'deterministic XML builder based on official OpenOrienteering Mapper symbol set .omap files',
    }

def validate_omap_project(project_omap: Path, project_root: Path) -> dict:
    project_omap=Path(project_omap); project_root=Path(project_root)
    errors=[]; absolute=[]; missing=[]
    try:
        tree=ET.parse(project_omap); root=tree.getroot()
    except Exception as e:
        return {'ok':False,'errors':[f'XML parse failed: {e!r}']}
    if not root.tag.endswith('map'): errors.append('root is not map')
    content_parent=_content_parent(root)
    georef=root.find(_ns('georeferencing'))
    epsg_code=None; projected_ref=None; geographic_ref=None; projected_crs_id=None
    if georef is None:
        errors.append('missing georeferencing')
    else:
        projected=georef.find(_ns('projected_crs'))
        if projected is not None:
            projected_crs_id=projected.get('id')
            params=[p.text for p in projected.findall(_ns('parameter'))]
            if projected_crs_id == 'EPSG' and params:
                epsg_code=params[0]
            pref=projected.find(_ns('ref_point'))
            if pref is not None:
                projected_ref=(float(pref.get('x','nan')), float(pref.get('y','nan')))
        geographic=georef.find(_ns('geographic_crs'))
        if geographic is not None:
            gref=geographic.find(_ns('ref_point_deg'))
            if gref is not None:
                geographic_ref=(float(gref.get('lat','nan')), float(gref.get('lon','nan')))
    templates=[]
    tel=content_parent.find(_ns('templates'))
    if tel is not None:
        for t in tel.findall(_ns('template')):
            path=t.get('relpath') or t.get('path') or ''
            templates.append(path)
            if re.match(r'^[A-Za-z]:[\\/]', path) or path.startswith('/') or path.startswith('~') or '..' in Path(path).parts:
                absolute.append(path)
            elif not (project_root/path).exists():
                missing.append(path)
    else:
        errors.append('missing templates')
    parts=content_parent.find(_ns('parts'))
    object_count=0
    object_count_attr=None
    if parts is not None:
        for part in parts.findall(_ns('part')):
            objects=part.find(_ns('objects'))
            if objects is not None:
                object_count += len(objects.findall(_ns('object')))
                object_count_attr = objects.get('count') if object_count_attr is None else object_count_attr
    symbols=content_parent.find(_ns('symbols'))
    symbol_count=len(symbols.findall(_ns('symbol'))) if symbols is not None else 0
    if absolute: errors.append('absolute/unsafe template paths present')
    if missing: errors.append('missing template files')
    return {
        'ok':not errors,
        'errors':errors,
        'template_count':len(templates),
        'templates':templates,
        'absolute_path_count':len(absolute),
        'absolute_paths':absolute,
        'missing_template_count':len(missing),
        'missing_templates':missing,
        'projected_crs_id':projected_crs_id,
        'epsg_code':epsg_code,
        'projected_ref_point':projected_ref,
        'geographic_ref_point':geographic_ref,
        'object_count':object_count,
        'object_count_attr':object_count_attr,
        'symbol_count':symbol_count,
    }
