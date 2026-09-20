import tempfile
import unittest
from pathlib import Path

from orimap_prep.config import parse_tiling
from osgeo import gdal, ogr, osr

from orimap_prep.tiling import build_tile_grid, tile_suffix, tile_manifest_files


class TilingTests(unittest.TestCase):
    def test_parse_tiling_requests(self):
        self.assertIsNone(parse_tiling("Připrav OB podklady."))
        self.assertEqual(parse_tiling("rozděl na 4 části"), {"parts": 4})
        self.assertEqual(parse_tiling("rozděl na 2x3"), {"cols": 2, "rows": 3})
        self.assertEqual(parse_tiling("dlaždice max strana 1000 m"), {"max_side_m": 1000.0})
        self.assertEqual(parse_tiling("max 50 MB na část"), {"max_tile_mb": 50.0})

    def test_build_tile_grid_uses_west_to_east_and_north_to_south_labels(self):
        grid = build_tile_grid({"minx": 0, "maxx": 300, "miny": 0, "maxy": 200}, {"cols": 3, "rows": 2})
        self.assertEqual([t["suffix"] for t in grid], ["A1", "B1", "C1", "A2", "B2", "C2"])
        self.assertEqual(grid[0]["extent"], {"minx": 0, "maxx": 100, "miny": 100, "maxy": 200})
        self.assertEqual(grid[-1]["extent"], {"minx": 200, "maxx": 300, "miny": 0, "maxy": 100})
        self.assertEqual(tile_suffix(26, 0), "AA1")

    def test_build_tile_grid_from_parts_and_max_side(self):
        self.assertEqual((build_tile_grid({"minx": 0, "maxx": 400, "miny": 0, "maxy": 400}, {"parts": 4})[-1]["suffix"]), "B2")
        self.assertEqual((build_tile_grid({"minx": 0, "maxx": 2500, "miny": 0, "maxy": 1200}, {"max_side_m": 1000})[-1]["suffix"]), "C2")

    def test_tile_manifest_files_cuts_rasters_and_vectors_with_consistent_suffixes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            srs = osr.SpatialReference(); srs.ImportFromEPSG(5514)
            raster = root / "02_relief" / "hillshade.tif"
            raster.parent.mkdir(parents=True)
            ds = gdal.GetDriverByName("GTiff").Create(str(raster), 20, 20, 1, gdal.GDT_Byte)
            ds.SetGeoTransform((0, 10, 0, 200, 0, -10))
            ds.SetProjection(srs.ExportToWkt())
            ds.GetRasterBand(1).Fill(7)
            ds = None

            vector = root / "05_buildings" / "buildings.gpkg"
            vector.parent.mkdir(parents=True)
            drv = ogr.GetDriverByName("GPKG")
            vds = drv.CreateDataSource(str(vector))
            lyr = vds.CreateLayer("buildings", srs, ogr.wkbPolygon)
            ring = ogr.Geometry(ogr.wkbLinearRing)
            for x, y in [(10, 10), (190, 10), (190, 190), (10, 190), (10, 10)]:
                ring.AddPoint(x, y)
            poly = ogr.Geometry(ogr.wkbPolygon); poly.AddGeometry(ring)
            feat = ogr.Feature(lyr.GetLayerDefn()); feat.SetGeometry(poly); lyr.CreateFeature(feat)
            vds = None

            manifest = {"files": [{"role": "hillshade", "path": str(raster)}, {"role": "buildings", "path": str(vector)}]}
            report = tile_manifest_files(root, manifest["files"], {"cols": 2, "rows": 2}, {"minx": 0, "maxx": 200, "miny": 0, "maxy": 200})

            self.assertEqual([t["suffix"] for t in report["tiles"]], ["A1", "B1", "A2", "B2"])
            tiled_roles = {f["role"] for f in manifest["files"] if f.get("tile")}
            self.assertIn("hillshade_A1", tiled_roles)
            self.assertIn("buildings_B2", tiled_roles)
            self.assertTrue((root / "02_relief" / "tiles" / "hillshade_A1.tif").exists())
            self.assertTrue((root / "05_buildings" / "tiles" / "buildings_B2.gpkg").exists())


if __name__ == "__main__":
    unittest.main()
