from __future__ import annotations
from pathlib import Path
import math, xml.etree.ElementTree as ET
from osgeo import ogr, osr
from .crs import srs_from

NS = {'g':'http://www.topografix.com/GPX/1/1'}

def _pts(root, tag):
    out=[]
    for el in root.findall('.//g:'+tag, NS) + root.findall('.//'+tag):
        try: out.append((float(el.attrib['lon']), float(el.attrib['lat'])))
        except Exception: pass
    return out

def haversine_m(a,b):
    lon1,lat1=map(math.radians,a); lon2,lat2=map(math.radians,b)
    dlon=lon2-lon1; dlat=lat2-lat1
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))

def ring_area_lonlat(points):
    # rough planar shoelace in degrees only for sanity / orientation, not metric area
    return 0.5*sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points)))

def read_boundary_points(gpx_path: Path, close_open=False):
    root=ET.parse(gpx_path).getroot()
    candidates=[]
    for tag in ['trkpt','rtept']:
        pts=_pts(root, tag)
        if len(pts)>=3: candidates.append((tag,pts))
    if not candidates:
        wpts=_pts(root,'wpt')
        if len(wpts)>=3: candidates.append(('wpt',wpts))
    if not candidates:
        raise ValueError('GPX contains no track/route/waypoints usable as an area boundary')
    kind, pts=max(candidates, key=lambda kv: len(kv[1]))
    if pts[0] != pts[-1]:
        enddist=haversine_m(pts[0], pts[-1])
        per=sum(haversine_m(pts[i],pts[i+1]) for i in range(len(pts)-1))
        if close_open or enddist <= max(50.0, per*0.03):
            pts=pts+[pts[0]]
        else:
            raise ValueError(f'GPX {kind} is not closed (endpoints {enddist:.1f} m apart). Provide closed GPX boundary or use --close-open if intentional.')
    if len(pts)<4:
        raise ValueError('Boundary polygon needs at least 3 distinct points')
    return kind, pts

def write_polygon_outputs(gpx_path: Path, out_geojson: Path, out_gpkg_target: Path, out_gpkg_5514: Path, target_crs: str, close_open=False):
    kind, pts = read_boundary_points(gpx_path, close_open=close_open)
    # GeoJSON EPSG:4326
    drv=ogr.GetDriverByName('GeoJSON')
    if out_geojson.exists(): drv.DeleteDataSource(str(out_geojson))
    ds=drv.CreateDataSource(str(out_geojson)); srs4326=srs_from('EPSG:4326')
    lyr=ds.CreateLayer('area', srs4326, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('source', ogr.OFTString))
    ring=ogr.Geometry(ogr.wkbLinearRing)
    for lon,lat in pts: ring.AddPoint(lon,lat)
    poly=ogr.Geometry(ogr.wkbPolygon); poly.AddGeometry(ring)
    feat=ogr.Feature(lyr.GetLayerDefn()); feat.SetField('source', kind); feat.SetGeometry(poly); lyr.CreateFeature(feat)
    ds=None
    # transform outputs
    def transform(src, dst, crs):
        drv=ogr.GetDriverByName('GPKG')
        if dst.exists(): drv.DeleteDataSource(str(dst))
        src_ds=ogr.Open(str(src)); src_lyr=src_ds.GetLayer(0)
        dst_srs=srs_from(crs); dst_ds=drv.CreateDataSource(str(dst)); dst_lyr=dst_ds.CreateLayer('area', dst_srs, ogr.wkbPolygon)
        for fld_i in range(src_lyr.GetLayerDefn().GetFieldCount()): dst_lyr.CreateField(src_lyr.GetLayerDefn().GetFieldDefn(fld_i))
        tx=osr.CoordinateTransformation(src_lyr.GetSpatialRef(), dst_srs)
        for f in src_lyr:
            g=f.GetGeometryRef().Clone(); g.Transform(tx)
            nf=ogr.Feature(dst_lyr.GetLayerDefn()); nf.SetFrom(f); nf.SetGeometry(g); dst_lyr.CreateFeature(nf)
        dst_ds=None; src_ds=None
    transform(out_geojson, out_gpkg_target, target_crs)
    transform(out_geojson, out_gpkg_5514, 'EPSG:5514')
    return {'source_layer': kind, 'point_count': len(pts), 'closed': True}

def layer_extent(path: Path):
    ds=ogr.Open(str(path)); lyr=ds.GetLayer(0); ext=lyr.GetExtent(); ds=None
    return {'minx':ext[0], 'maxx':ext[1], 'miny':ext[2], 'maxy':ext[3]}

def layer_area(path: Path) -> float:
    ds=ogr.Open(str(path)); lyr=ds.GetLayer(0); area=0.0
    for f in lyr: area += f.GetGeometryRef().GetArea()
    ds=None; return area
