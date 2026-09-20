from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
import os
import re

DEFAULT_CRS = "EPSG:5514"
DEFAULT_CONTOURS = [1.0, 5.0, 25.0]
DEFAULT_PRODUCTS = ["dem", "hillshade", "hillshade_multidirectional", "contours", "slope", "ortho", "cir_orthophoto", "buildings", "dmp", "surface_height", "vegetation_height"]
DEFAULT_MAP_TYPE = "forest"
DEFAULT_MAP_SCALE = 10000
DEFAULT_PROJECT_ROOT = Path(os.environ.get("ORIMAP_PROJECT_ROOT", Path.home() / "orimap-projects"))
DEFAULT_CACHE_ROOT = Path(os.environ.get("ORIMAP_CACHE_ROOT", Path.home() / ".cache" / "orienteering-map-prep"))

@dataclass
class JobConfig:
    input_gpx: Path
    project_id: str
    project_root: Path = DEFAULT_PROJECT_ROOT
    cache_root: Path = DEFAULT_CACHE_ROOT
    target_crs: str = DEFAULT_CRS
    contours_m: list[float] = field(default_factory=lambda: DEFAULT_CONTOURS.copy())
    products: list[str] = field(default_factory=lambda: DEFAULT_PRODUCTS.copy())
    buffer_m: float = 100.0
    dem_pixel_size_m: float = 1.0
    dmp_pixel_size_m: float = 0.5
    close_open: bool = False
    max_export_px: int = 1800
    source_dmr: str = "cuzk_dmr5g_imageserver"
    add_ortho: bool = False
    drive_upload: bool = False
    drive_root_folder: str = "OB podklady"
    drive_job_folder_name: str | None = None
    cleanup_local_after_drive: bool = False
    map_scale: int = DEFAULT_MAP_SCALE
    map_type: str | None = DEFAULT_MAP_TYPE
    map_standard: str | None = None
    map_contour_interval: float | None = None
    project_date: str | None = None
    calculate_declination: bool = True
    generate_oom_setup: bool = True
    generate_omap: bool = False
    tiling: dict | None = None

    def to_dict(self):
        d = asdict(self)
        for k in ["input_gpx", "project_root", "cache_root"]:
            d[k] = str(d[k])
        return d

def contour_token(v: float) -> str:
    if abs(v - int(v)) < 1e-9:
        return f"{int(v)}m"
    return (str(v).replace('.', '_').replace(',', '_') + "m")

def parse_number_list(text: str) -> list[float]:
    """Parse Czech/CLI contour lists safely.

    Treat ``5,25`` as two list items (5 and 25), but allow decimal comma
    when it is unambiguous, e.g. ``2,5 a 5`` -> [2.5, 5]. Prefer decimal
    dot in scripts/CLI when possible.
    """
    s = text.lower().strip()
    s = re.sub(r'(?<=\d),(?=\d(?:\s|$|\s*a\s|\s*/))', '.', s)  # 2,5 a 5 -> 2.5 a 5
    s = re.sub(r'\s+a\s+|/|;|\s+', ',', s)
    parts = []
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r'\d+(?:\.\d+)?', part):
            parts.append(float(part))
        else:
            parts.extend(float(x) for x in re.findall(r'\d+(?:\.\d+)?', part))
    return parts

def parse_contours(text: str) -> list[float] | None:
    t = text.lower()
    m = re.search(r'vrstevnic\w*\s*(?:po\s*)?([0-9.,/; a]+)\s*m', t)
    if not m:
        return None
    nums = parse_number_list(m.group(1))
    return nums if nums else None

def parse_crs(text: str) -> str | None:
    m = re.search(r'epsg\s*:?\s*(\d{3,6})', text, re.I)
    return f"EPSG:{m.group(1)}" if m else None

def parse_map_scale(text: str) -> int | None:
    t = text.lower().replace('\u00a0',' ')
    m = re.search(r'1\s*[:/]\s*([0-9][0-9 .]*)', t)
    if m:
        return int(re.sub(r'\D','',m.group(1)))
    m = re.search(r'měřítk\w*\s+([0-9][0-9 .]*)', t)
    if m:
        return int(re.sub(r'\D','',m.group(1)))
    return None

def default_map_scale(map_type: str | None) -> int:
    return 4000 if map_type == 'sprint' else DEFAULT_MAP_SCALE

def parse_drive_upload(text: str) -> bool:
    t=text.lower()
    return any(w in t for w in ['google drive','gdrive','drive','na disk google','na google'])

def parse_area_name(text: str) -> str | None:
    patterns = [
        r'(?:název|nazev)\s+(?:oblasti|mapy)\s*[:\-]\s*([^.;\n]+)',
        r'(?:oblast|mapa)\s+(?:se\s+jmenuje\s*)?["„“]?([^"„“.;\n]+)["„“]?',
    ]
    for pat in patterns:
        m=re.search(pat, text, re.I)
        if m:
            name=m.group(1).strip(' "„“')
            if name and not re.search(r'\b(gpx|podklady|mapy?|ob)\b$', name, re.I):
                return name
    return None

def parse_map_type(text: str) -> str | None:
    t=text.lower()
    if any(w in t for w in ['sprint','sprintr']): return 'sprint'
    if any(w in t for w in ['mtbo','bike','cyklo']): return 'mtbo'
    if any(w in t for w in ['lesní','lesni','forest','klasik','middle','long']): return 'forest'
    return None

def parse_map_standard(text: str) -> str | None:
    t=text.lower()
    for key in ['isom 2017-2','isom 2017','issprom 2019-2','issprom 2019','isskiom','ismtbom','mtbo']:
        if key in t: return key.upper()
    return None

def parse_map_contour_interval(text: str) -> float | None:
    t=text.lower()
    m=re.search(r'(?:mapov\w*|kartograf\w*|hlavn\w*)\s+ekvidistanc\w*\s*([0-9]+(?:[,.][0-9]+)?)\s*m', t)
    if not m: m=re.search(r'ekvidistanc\w*\s*([0-9]+(?:[,.][0-9]+)?)\s*m', t)
    if m: return float(m.group(1).replace(',','.'))
    return None

def default_map_contour_interval(map_type: str | None, map_scale: int) -> float:
    if map_type == 'sprint': return 2.0
    if map_type == 'mtbo': return 5.0
    if map_scale >= 15000: return 5.0
    return 5.0

def parse_generate_omap(text: str) -> bool:
    t=text.lower()
    return any(w in t for w in [
        '.omap', 'project.omap', 'oom projekt', 'openorienteering mapper projekt',
        'mapper projekt', 'projekt pro mapper', 'vytvoř oom', 'vytvor oom',
        'vytvoř i oom', 'vytvor i oom', 'rovnou oom', 'oomaper file', 'oomapper file',
    ])

def parse_tiling(text: str) -> dict | None:
    t=text.lower().replace('\u00a0',' ')
    if not any(w in t for w in ['dlažd', 'dlazd', 'rozděl', 'rozdel', 'část', 'cast', 'tablet', 'mobil', 'mb na část', 'mb na cast', 'max strana']):
        return None
    m=re.search(r'(\d+)\s*[x×]\s*(\d+)', t)
    if m:
        return {'cols': int(m.group(1)), 'rows': int(m.group(2))}
    m=re.search(r'(?:rozděl|rozdel)\D{0,20}(\d+)\s*(?:část|cast)', t)
    if m:
        return {'parts': int(m.group(1))}
    m=re.search(r'(?:max(?:im[aá]ln[ií])?\s*)?(?:strana|dlaždice|dlazdice)\D{0,20}(\d+(?:[,.]\d+)?)\s*m\b', t)
    if m:
        return {'max_side_m': float(m.group(1).replace(',','.'))}
    m=re.search(r'(?:max(?:im[aá]ln[ií])?\s*)?(\d+(?:[,.]\d+)?)\s*mb\s*(?:na|/)?\s*(?:část|cast|dlaždici|dlazdici)?', t)
    if m:
        return {'max_tile_mb': float(m.group(1).replace(',','.'))}
    if any(w in t for w in ['dlažd', 'dlazd', 'tablet', 'mobil']):
        return {'parts': 4}
    return None

def parse_products(text: str) -> list[str] | None:
    t = text.lower()
    known = []
    if re.search(r'\bpouze\b|\bjen\b|only', t):
        for key, words in {
            'dem':['dem'], 'hillshade':['hillshade','stínování','stinovani'], 'hillshade_multidirectional':['multidirectional','multi-directional','multidirectional hillshade','hillshade multidirectional'],
            'contours':['vrstevnice'], 'slope':['slope','sklon'], 'ortho':['ortofoto','orthophoto','rgb ortofoto','rgb orthophoto'], 'cir_orthophoto':['cir','cir ortofoto','color infrared','infrared'], 'buildings':['budovy','budova','stavební objekty','stavebni objekty','building','buildings','ruian','rúian'],
            'dmp':['dmp','model povrchu'], 'surface_height':['výšku povrchu','vysku povrchu','surface height','relativní výšku','relativni vysku'],
            'vegetation_height':['výšku vegetace','vysku vegetace','vegetace','vegetaci','vegetation height']
        }.items():
            if any(w in t for w in words): known.append(key)
        return known or None
    products = DEFAULT_PRODUCTS.copy()
    if any(w in t for w in ['slope','sklon']): products.append('slope')
    if any(w in t for w in ['hillshade','stínování','stinovani']) and not any(w in t for w in ['multidirectional','multi-directional']): products.append('hillshade')
    if any(w in t for w in ['ortofoto','orthophoto']) or any(w in t for w in ['kompletní podklady','kompletni podklady','kompletní','kompletni']): products.append('ortho')
    if any(w in t for w in ['cir','cir ortofoto','color infrared','infrared']): products.append('cir_orthophoto')
    if any(w in t for w in ['budovy','budova','stavební objekty','stavebni objekty','building','buildings','ruian','rúian']): products.append('buildings')
    if any(w in t for w in ['dmp','model povrchu','výšku povrchu','vysku povrchu','surface height','výšku vegetace','vysku vegetace','vegetace','vegetaci','vegetation height']):
        products.extend(['dmp','surface_height','vegetation_height'])
    return sorted(set(products), key=products.index)
