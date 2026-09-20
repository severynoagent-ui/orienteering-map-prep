from __future__ import annotations
from pathlib import Path
from datetime import date
import json, math, requests
from osgeo import ogr, osr
from pyproj import CRS, Proj
from .util import write_json

OOM_DOCS = {
    'templates': 'https://www.openorienteering.org/mapper-manual/pages/templates.html',
    'georeferencing': 'https://www.openorienteering.org/mapper-manual/pages/georeferencing.html',
}
BGS_WMM_URL = 'https://geomag.bgs.ac.uk/web_service/GMModels/wmm/2025/'

def _fmt_float(v, nd=3):
    if v is None: return 'nezjištěno'
    return f"{float(v):.{nd}f}"

def area_centroid_lonlat(area_geojson: Path) -> tuple[float, float]:
    ds=ogr.Open(str(area_geojson)); lyr=ds.GetLayer(0)
    geom=None
    for f in lyr:
        geom=f.GetGeometryRef().Clone(); break
    srs=lyr.GetSpatialRef(); ds=None
    if geom is None:
        raise RuntimeError('No AOI geometry')
    c=geom.Centroid()
    x=float(c.GetX()); y=float(c.GetY())
    # GeoJSON CRS84 and most GPX-derived files are already lon/lat. Avoid an
    # unnecessary EPSG:4326 transform because modern axis-order rules may swap
    # longitude/latitude.
    if -180.0 <= x <= 180.0 and -90.0 <= y <= 90.0 and (srs is None or srs.IsGeographic()):
        return x, y
    dst=osr.SpatialReference(); dst.ImportFromEPSG(4326)
    if hasattr(dst, 'SetAxisMappingStrategy'):
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    if srs is not None and hasattr(srs, 'SetAxisMappingStrategy'):
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    if srs is not None and not srs.IsSame(dst):
        c.Transform(osr.CoordinateTransformation(srs,dst))
    return float(c.GetX()), float(c.GetY())

def declination_bgs_wmm2025(lat: float, lon: float, project_date: str) -> dict:
    params={'latitude':lat,'longitude':lon,'altitude':0,'date':project_date,'format':'json'}
    r=requests.get(BGS_WMM_URL,params=params,timeout=30,headers={'User-Agent':'HermesAgent orimap-prep'})
    r.raise_for_status()
    data=r.json()['geomagnetic-field-model-result']
    dec=float(data['field-value']['declination']['value'])
    return {
        'declination_deg_east_positive': dec,
        # BGS/WMM JSON is signed east-positive; OOM stores the opposite sign convention.
        'declination_deg_oom': -dec,
        'direction': 'E' if dec >= 0 else 'W',
        'abs_degrees': abs(dec),
        'date': data['date']['value'],
        'latitude': data['coordinates']['latitude']['value'],
        'longitude': data['coordinates']['longitude']['value'],
        'altitude_km': data['coordinates']['altitude']['value'],
        'model': f"{data.get('model','wmm').upper()}{data.get('model_revision','2025')}",
        'source': BGS_WMM_URL,
        'raw': data,
    }

def grid_convergence(crs_code: str, lon: float, lat: float) -> dict:
    try:
        p=Proj(crs_code)
        f=p.get_factors(lon, lat)
        return {'meridian_convergence_deg': float(f.meridian_convergence), 'method':'pyproj.Proj.get_factors at AOI centroid', 'note':'Reported for orientation only; in OOM enter magnetic declination separately and let OOM combine it with grid convergence/grivation when georeferencing is configured.'}
    except Exception as e:
        return {'error':repr(e)}

def standard_recommendation(map_type: str | None, map_scale: int, explicit: str | None) -> dict:
    if explicit:
        return {'map_standard': explicit, 'source':'user_explicit'}
    if map_type == 'sprint' or map_scale <= 5000:
        return {'map_standard':'ISSprOM 2019-2 (verify in OOM symbol set list)', 'source':'recommended_default', 'symbol_set_hint':'Sprint orienteering map'}
    if map_type == 'mtbo':
        return {'map_standard':'ISMTBOM / current IOF MTBO specification (verify exact symbol set in OOM)', 'source':'recommended_option', 'symbol_set_hint':'MTBO'}
    return {'map_standard':'ISOM 2017-2 (verify in OOM symbol set list)', 'source':'recommended_default', 'symbol_set_hint':'Forest/foot orienteering map'}

def epsg_code(crs_code: str | None) -> str:
    if not crs_code:
        return 'nezjištěno'
    try:
        c=CRS.from_user_input(crs_code)
        auth=c.to_authority()
        if auth and auth[0].upper() == 'EPSG':
            return auth[1]
    except Exception:
        pass
    if str(crs_code).upper().startswith('EPSG:'):
        return str(crs_code).split(':',1)[1]
    return str(crs_code)

def _files_by_role(manifest):
    return {f['role']:f for f in manifest.get('files',[]) if 'role' in f}

def _rel(project_root: Path, p: str):
    try: return str(Path(p).relative_to(project_root))
    except Exception: return p

def template_entries(manifest: dict, project_root: Path) -> list[dict]:
    files=_files_by_role(manifest)
    displays={d.get('source_role'):d for d in manifest.get('oom_display_rasters',[]) if d.get('display')}
    def path_for(role):
        if role in displays: return displays[role]['display'], displays[role]['display_role']
        if role in files: return files[role]['path'], role
        return None, None
    order=[
        ('ortofoto_current','ORTOFOTO RGB','základní vizuální interpretace terénu, cest, budov a hranic vegetace',70),
        ('ortofoto_cir','ORTOFOTO CIR','doplňková spektrální interpretace vegetace; není to průběžnost ani rychlost běhu',65),
        ('hillshade','HILLSHADE','interpretace tvarů terénu',45),
        ('hillshade_multidirectional','MULTIDIRECTIONAL HILLSHADE','alternativní stínování reliéfu',35),
        ('contours_5m','CONTOURS 5 M','základní orientace v reliéfu; ne automaticky finální OB kresba',100),
        ('contours_1m','CONTOURS 1 M','detailní pomocný výškopis; ne automaticky finální vrstevnice',60),
        ('vegetation_height','VEGETATION HEIGHT','pomocná interpretace výšky povrchu/vegetace; není průběžnost',55),
        ('surface_height_raw','SURFACE HEIGHT RAW','kontrolní vizualizace surového DMP−DEM rozdílu',45),
        ('slope','SLOPE','pomocná interpretace sklonu terénu',35),
        ('dem','DEM DISPLAY','vizualizace modelu terénu; analytický DEM je Float raster',30),
        ('dmp_ok','DMP DISPLAY','vizualizace modelu povrchu; analytický DMP je Float raster',30),
    ]
    entries=[]
    for role,label,use,opacity in order:
        p, actual_role = path_for(role)
        if p:
            entries.append({'role':actual_role,'source_role':role,'label':label,'path':_rel(project_root,p),'use':use,'opacity_start_percent':opacity})
    return entries

def template_presets(entries):
    labels={e['label']:e for e in entries}
    def has(substr): return [e for e in entries if substr in e['label']]
    presets=[]
    relief=[]
    for key in ['HILLSHADE','CONTOURS 5 M','CONTOURS 1 M']:
        if key in labels: relief.append(labels[key]['path'])
    if relief: presets.append({'name':'RELIÉF','templates':relief})
    ortho=[]
    for key in ['ORTOFOTO RGB','CONTOURS 5 M']:
        if key in labels: ortho.append(labels[key]['path'])
    if ortho: presets.append({'name':'ORTOFOTO','templates':ortho})
    veg=[]
    for key in ['ORTOFOTO RGB','ORTOFOTO CIR','VEGETATION HEIGHT','CONTOURS 5 M']:
        if key in labels: veg.append(labels[key]['path'])
    if veg: presets.append({'name':'VEGETACE','templates':veg})
    obj=[]
    for key in ['ORTOFOTO RGB']:
        if key in labels: obj.append(labels[key]['path'])
    if obj: presets.append({'name':'OBJEKTY','templates':obj, 'note':'Budovy/cesty budou přidány až po budoucí implementaci vektorových vrstev.'})
    return presets

def data_currency(manifest):
    rows=[]
    for s in manifest.get('sources',[]):
        ds=s.get('dataset','zdroj')
        if 'DMR 5G' in ds:
            rows.append(('DMR 5G','ČÚZK ImageServer','pořízení LLS 2009–2013 podle metadata služby','staženo při jobu'))
        elif 'DMP OK' in ds:
            rows.append(('DMP OK','ČÚZK ImageServer','DMP OK z LMS/Ortofoto cyklu; konkrétní rok podle oblasti není per-pixel ověřen v pipeline','staženo při jobu'))
        elif 'Ortofoto CIR' in ds or 'ORTOCIR' in ds:
            continue
        elif 'Ortofoto' in ds:
            ac=s.get('acquisition') or manifest.get('ortho_acquisition') or {}
            yr=ac.get('acquisition_year') or ac.get('official_product_years') or 'nezjištěno'
            rows.append(('Ortofoto','ČÚZK WMS/WMTS',str(yr),'staženo při jobu'))
    cir=manifest.get('cir_orthophoto') or {}
    if cir:
        rows.append(('Ortofoto CIR','ČÚZK WMS-ORTOCIR',str(cir.get('imagery_year') or 'nezjištěno'),str(cir.get('download_date') or 'staženo při jobu')))
    return rows

def generate_oom_setup(project_root: Path, manifest: dict, *, logger=None) -> dict:
    cfg=manifest.get('config',{})
    project_date=(cfg.get('project_date') or manifest.get('created_at','')[:10] or date.today().isoformat())
    files=_files_by_role(manifest)
    area_geojson=Path(files.get('area_geojson',{}).get('path', project_root/'00_oblast/area.geojson'))
    lon=lat=None; decl=None; conv=None; decl_warning=None
    try:
        lon,lat=area_centroid_lonlat(area_geojson)
        if cfg.get('calculate_declination', True):
            decl=declination_bgs_wmm2025(lat,lon,project_date)
        conv=grid_convergence(cfg.get('target_crs','EPSG:5514'), lon, lat)
    except Exception as e:
        decl_warning=f'Deklinaci/střed se nepodařilo spočítat: {e!r}'
        if logger: logger.log('WARN '+decl_warning)
    area=manifest.get('area',{})
    ext=area.get('target_info',{}).get('extent')
    width_m=height_m=None
    if isinstance(ext, dict):
        width_m=float(ext['maxx']-ext['minx']); height_m=float(ext['maxy']-ext['miny'])
    elif ext and len(ext)>=4:
        # OGR extent tuple/list: minx, maxx, miny, maxy
        width_m=float(ext[1]-ext[0]); height_m=float(ext[3]-ext[2])
    scale=int(cfg.get('map_scale') or 10000)
    width_mm=width_m/scale*1000 if width_m else None
    height_mm=height_m/scale*1000 if height_m else None
    entries=template_entries(manifest, project_root)
    presets=template_presets(entries)
    standard=standard_recommendation(cfg.get('map_type'), scale, cfg.get('map_standard'))
    map_interval=cfg.get('map_contour_interval') or 5.0
    dec_text='nezjištěno'
    if decl:
        dec_text=f"{decl['abs_degrees']:.3f}° {decl['direction']} ({decl['declination_deg_east_positive']:+.3f}° east-positive BGS; {decl['declination_deg_oom']:+.3f}° OOM)"
    lines=[]
    lines.append('# OpenOrienteering Mapper – nastavení projektu\n\n')
    if cfg.get('generate_omap'):
        lines.append('## Project.omap\n\n')
        lines.append('Projekt je přednastavený v souboru `project.omap`. Po rozbalení ZIPu otevři `project.omap` v OpenOrienteering Mapperu; template odkazy jsou relativní a zachovávají současnou strukturu složek balíku.\n\n')
        lines.append('Níže uvedené nastavení slouží jako kontrolní checklist a fallback, pokud by aktuální verze OOM některou část automaticky nenačetla.\n\n')
    lines.append('## Projekt\n\n')
    lines.append(f"- Projekt: `{manifest.get('project_id')}`\n")
    lines.append(f"- Datum projektu: `{project_date}`\n")
    lines.append(f"- Rozloha: `{area.get('area_km2','nezjištěno')}` km²\n")
    if ext: lines.append(f"- Bounding box v cílovém CRS: `{ext}`\n")
    if lon is not None: lines.append(f"- Střed oblasti: `{lat:.6f} N`, `{lon:.6f} E`\n")
    lines.append('\n## Doporučené nastavení mapy\n\n')
    lines.append(f"- Měřítko: `1:{scale}`\n")
    lines.append(f"- Typ mapy: `{cfg.get('map_type') or 'nezadáno / forest default'}`\n")
    lines.append(f"- Symbol set / standard: `{standard['map_standard']}` ({standard['source']})\n")
    lines.append(f"- Výsledná mapová ekvidistance: `{map_interval} m`\n")
    lines.append(f"- GIS pomocné vrstevnice vytvořené z DEM: `{manifest.get('contours_m')}` m — nejsou automaticky finální kartografické vrstevnice.\n")
    lines.append('\n## Georeference\n\n')
    lines.append(f"- Výstupní CRS projektu: `{cfg.get('target_crs')}`\n")
    lines.append(f"- V OOM použij `Map > Georeferencing…`, v části `Map coordinate reference system` zvol `EPSG` a zadej kód `{epsg_code(cfg.get('target_crs'))}`.\n")
    lines.append('- Georeferencované GeoTIFF templates používej přes `Templates > Template Setup Window`; u GeoTIFF zvol georeferenced positioning, pokud se OOM zeptá.\n')
    lines.append(f"- OOM dokumentace: {OOM_DOCS['georeferencing']}\n")
    lines.append('\n## Magnetický sever\n\n')
    lines.append(f"- Magnetická deklinace: `{dec_text}`\n")
    if decl:
        lines.append(f"- Platí pro: `{decl['date']}`\n")
        lines.append(f"- Místo výpočtu: `{decl['latitude']:.6f} N`, `{decl['longitude']:.6f} E`\n")
        lines.append(f"- Zdroj/model: `{decl['model']}`, British Geological Survey WMM web service `{decl['source']}`\n")
    if conv: lines.append(f"- Grid convergence / meridian convergence informativně: `{conv}`\n")
    if decl_warning: lines.append(f"- WARNING: {decl_warning}\n")
    lines.append('\n**OOM postup:** v `Map > Georeferencing…` zadej CRS a referenční bod; do pole `Declination` zadej magnetickou deklinaci jako úhel mezi true north a magnetic north. Nepřičítej ručně grid convergence: OOM dokumentace uvádí, že `Grivation` je složeno z magnetické deklinace a grid convergence.\n')
    lines.append('\n## Podklady\n\n')
    for e in entries:
        lines.append(f"- `{e['path']}` — {e['use']} (doporučený start opacity {e['opacity_start_percent']} %)\n")
    lines.append('\n## Doporučené pořadí templates\n\n')
    for i,e in enumerate(entries, start=1): lines.append(f"{i}. `{e['path']}` — {e['label']}\n")
    lines.append('\n## Doporučené template presets\n\n')
    for p in presets:
        lines.append(f"### {p['name']}\n")
        for t in p['templates']: lines.append(f"- `{t}`\n")
        if p.get('note'): lines.append(f"- Poznámka: {p['note']}\n")
    lines.append('\n## Aktuálnost podkladů\n\n')
    lines.append('| Podklad | Zdroj | Datum pořízení / aktualizace dat | Datum stažení |\n|---|---|---|---|\n')
    for row in data_currency(manifest): lines.append('| ' + ' | '.join(row) + ' |\n')
    lines.append('\n## Rozměr mapy\n\n')
    if width_m and height_m:
        lines.append(f"- Rozsah bounding boxu: cca `{width_m/1000:.2f} × {height_m/1000:.2f} km`\n")
        lines.append(f"- Při měřítku `1:{scale}`: cca `{width_mm:.0f} × {height_mm:.0f} mm`\n")
        lines.append('- Jde o bounding-box odhad, ne přesnou tiskovou kompozici.\n')
    else:
        lines.append('- Nezjištěno.\n')
    lines.append('\n## Kontrola před mapováním\n\n')
    for item in ['správné měřítko','správné CRS','podklady se prostorově překrývají','ortofoto sedí vůči ostatním podkladům','magnetická deklinace odpovídá datu projektu','nastavení severu bylo ověřeno','zvolen správný mapový standard','správná výsledná ekvidistance','automatické vrstevnice jsou používány pouze jako podklad','výška vegetace není zaměňována za průběžnost']:
        lines.append(f"- [ ] {item}\n")
    lines.append('\n## Poznámky / warnings\n\n')
    for w in manifest.get('warnings',[]): lines.append(f"- WARNING: {w}\n")
    if not manifest.get('warnings'): lines.append('- Bez warningů z pipeline.\n')
    lines.append('\n## .omap automatizace\n\n')
    lines.append('Zatím negeneruji `project.omap`. OOM `.omap` je interní XML mapový soubor a template/georeference lze technicky číst, ale aktuální bezpečný, oficiálně podporovaný headless CLI/API způsob pro kompletní vytvoření projektu se symbol setem, templates a severem jsem nepotvrdil. Doporučení: zatím používat tento OOM_SETUP; automatické `.omap` přidat až po samostatném ověření proti aktuální verzi OOM.\n')
    md=project_root/'OOM_SETUP.md'; txt=project_root/'OOM_SETUP.txt'
    md.write_text(''.join(lines), encoding='utf-8')
    txt.write_text(''.join(lines), encoding='utf-8')
    meta={'oom_setup_md':str(md),'oom_setup_txt':str(txt),'center_lonlat':{'lon':lon,'lat':lat},'declination':decl,'grid_convergence':conv,'template_entries':entries,'template_presets':presets,'map_physical_size':{'width_m':width_m,'height_m':height_m,'scale':scale,'width_mm':width_mm,'height_mm':height_mm},'docs':OOM_DOCS,'omap_automation':{'status':'not_implemented','reason':'No confirmed stable official headless CLI/API for full project.omap creation; avoid brittle internal-format hack.'}}
    write_json(project_root/'oom_setup_meta.json', meta)
    return meta
