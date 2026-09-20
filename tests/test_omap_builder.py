import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from pyproj import Transformer

from orimap_prep.config import parse_generate_omap
from orimap_prep.omap_builder import generate_omap_project, validate_omap_project, _declination_values


def _touch(path: Path, content: bytes = b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class OmapBuilderTests(unittest.TestCase):
    def test_parse_generate_omap_only_explicit_requests(self):
        self.assertFalse(parse_generate_omap("Připrav podklady pro OB."))
        self.assertTrue(parse_generate_omap("Připrav podklady a vytvoř i OOM projekt."))
        self.assertTrue(parse_generate_omap("chci .omap"))
        self.assertTrue(parse_generate_omap("rovnou Mapper projekt 1:10 000"))

    def test_declination_fallback_uses_signed_model_direction_not_abs(self):
        manifest = {"oom_setup": {"declination": {"declination_deg_east_positive": 4.81, "abs_degrees": 4.81}}}
        decl, _griv, _conv = _declination_values(manifest, "EPSG:5514", 49.9, 13.0)
        self.assertEqual(decl, "-4.81")

    def test_generate_omap_project_uses_relative_existing_structured_paths(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            # Preserve the package/Drive folder structure instead of flattening to templates/.
            _touch(tmp_path / "04_ortofoto" / "ortofoto_current.tif")
            _touch(tmp_path / "04_ortofoto" / "ortofoto_cir.tif")
            _touch(tmp_path / "02_relief" / "hillshade.tif")
            _touch(tmp_path / "06_vegetation" / "vegetation_height_oom.tif")
            _touch(tmp_path / "03_contours" / "contours_5m.gpkg")
            manifest = {
                "project_id": "unit-test",
                "created_at": "2026-09-20T00:00:00+0000",
                "config": {"target_crs": "EPSG:5514", "map_scale": 10000, "map_type": "forest", "project_date": "2026-09-20"},
                "oom_setup": {"declination": {"declination_deg": 4.8}, "grid_convergence": {"meridian_convergence_deg": -9.1}},
                "sources": [
                    {"dataset": "ČÚZK Ortofoto", "acquisition": {"acquisition_year": 2025, "acquisition_month": 6}},
                    {"dataset": "ČÚZK DMP OK ImageServer", "metadata_summary": {"creation_year": 2024}},
                ],
                "files": [
                    {"role": "ortofoto_current", "path": str(tmp_path / "04_ortofoto" / "ortofoto_current.tif")},
                    {"role": "ortofoto_cir", "path": str(tmp_path / "04_ortofoto" / "ortofoto_cir.tif")},
                    {"role": "hillshade", "path": str(tmp_path / "02_relief" / "hillshade.tif")},
                    {"role": "vegetation_height_oom", "path": str(tmp_path / "06_vegetation" / "vegetation_height_oom.tif")},
                    {"role": "contours_5m", "path": str(tmp_path / "03_contours" / "contours_5m.gpkg")},
                ],
            }

            result = generate_omap_project(tmp_path, manifest)

            project = Path(result["project_omap"])
            self.assertTrue(project.exists())
            self.assertEqual(project.name, "unit-test.omap")
            text = project.read_text(encoding="utf-8")
            self.assertNotIn("/home/", text)
            self.assertNotIn(str(tmp_path), text)
            self.assertIn("04_ortofoto/ortofoto_current__cuzk_ortofoto_rgb_2025-06.tif", text)
            self.assertIn("04_ortofoto/ortofoto_cir__cuzk_ortofoto_cir_2025-06.tif", text)
            self.assertIn("06_vegetation/vegetation_height_oom__derived_2026-09-20_from_cuzk_dmp_ok_and_cuzk_dmr5g_2009-2013.tif", text)
            self.assertNotIn("04_ortofoto/ortofoto_current.tif", text)
            self.assertNotIn("06_vegetation/vegetation_height_oom.tif", text)
            self.assertIn('name="ORTOFOTO RGB 2025-06"', text)
            self.assertIn('name="VEGETATION HEIGHT DMP 2024"', text)
            self.assertIn('name="HILLSHADE DMR5G 2009-2013"', text)
            self.assertFalse((tmp_path / "04_ortofoto" / "ortofoto_current.tif").exists())
            self.assertTrue((tmp_path / "04_ortofoto" / "ortofoto_current__cuzk_ortofoto_rgb_2025-06.tif").exists())
            root = ET.parse(project).getroot()
            self.assertTrue(root.tag.endswith("map"))
            georef = root.find("{http://openorienteering.org/apps/mapper/xml/v2}georeferencing")
            self.assertIsNotNone(georef)
            self.assertEqual(georef.attrib["scale"], "10000")
            validation = validate_omap_project(project, tmp_path)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["absolute_path_count"], 0)
            self.assertEqual(validation["missing_template_count"], 0)
            ns = "{http://openorienteering.org/apps/mapper/xml/v2}"
            barrier = root.find(ns + "barrier")
            content_parent = barrier if barrier is not None else root
            refs = content_parent.find(ns + "view").find(ns + "map_view").find(ns + "templates")
            self.assertGreater(len(refs.findall(ns + "ref")), 0)
            self.assertEqual({r.attrib.get("opacity") for r in refs.findall(ns + "ref")}, {"1"})
    def test_generate_omap_project_preserves_epsg_identity_geographic_reference_and_empty_map(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _touch(tmp_path / "04_ortofoto" / "ortofoto_current.tif")
            _touch(tmp_path / "02_relief" / "hillshade.tif")
            # Matches the OGR extent convention used by pipeline manifests: minx, maxx, miny, maxy.
            extent = {"minx": -849000.0, "maxx": -848000.0, "miny": -1045700.0, "maxy": -1044700.0}
            center_x = (extent["minx"] + extent["maxx"]) / 2
            center_y = (extent["miny"] + extent["maxy"]) / 2
            lon, lat = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True).transform(center_x, center_y)
            manifest = {
                "project_id": "unit-test-epsg",
                "config": {"target_crs": "EPSG:5514", "map_scale": 10000, "map_type": "forest"},
                "area": {"target_info": {"extent": extent}},
                "oom_setup": {
                    # OOM stores declination with its own sign convention; use a fixed known value here.
                    "declination": {"declination_deg_oom": -3.26, "declination_deg_east_positive": 3.26},
                    "grid_convergence": {"meridian_convergence_deg": -8.95},
                },
                "files": [
                    {"role": "ortofoto_current", "path": str(tmp_path / "04_ortofoto" / "ortofoto_current.tif")},
                    {"role": "hillshade", "path": str(tmp_path / "02_relief" / "hillshade.tif")},
                ],
            }

            result = generate_omap_project(tmp_path, manifest)
            project = Path(result["project_omap"])
            root = ET.parse(project).getroot()
            ns = "{http://openorienteering.org/apps/mapper/xml/v2}"
            georef = root.find(ns + "georeferencing")
            self.assertIsNotNone(georef)
            self.assertEqual(georef.attrib["scale"], "10000")
            self.assertAlmostEqual(float(georef.attrib["declination"]), -3.26, places=6)
            self.assertAlmostEqual(float(georef.attrib["grivation"]), 5.69, places=6)

            projected = georef.find(ns + "projected_crs")
            self.assertIsNotNone(projected)
            self.assertEqual(projected.attrib.get("id"), "EPSG")
            self.assertEqual([p.text for p in projected.findall(ns + "parameter")], ["5514"])
            spec = projected.find(ns + "spec")
            self.assertIsNotNone(spec)
            self.assertEqual(spec.text, "+init=epsg:5514")
            self.assertNotEqual(projected.attrib.get("id"), "PROJ.4")
            self.assertNotEqual(projected.attrib.get("id"), "EPSG:5514")

            projected_ref = projected.find(ns + "ref_point")
            self.assertIsNotNone(projected_ref)
            self.assertAlmostEqual(float(projected_ref.attrib["x"]), center_x, places=6)
            self.assertAlmostEqual(float(projected_ref.attrib["y"]), center_y, places=6)

            geographic = georef.find(ns + "geographic_crs")
            self.assertIsNotNone(geographic)
            self.assertEqual(geographic.attrib.get("id"), "Geographic coordinates")
            geo_ref = geographic.find(ns + "ref_point_deg")
            self.assertIsNotNone(geo_ref)
            self.assertNotAlmostEqual(float(geo_ref.attrib["lat"]), 0.0, places=7)
            self.assertNotAlmostEqual(float(geo_ref.attrib["lon"]), 0.0, places=7)
            self.assertAlmostEqual(float(geo_ref.attrib["lat"]), lat, places=7)
            self.assertAlmostEqual(float(geo_ref.attrib["lon"]), lon, places=7)

            barrier = root.find(ns + "barrier")
            content_parent = barrier if barrier is not None else root
            parts = content_parent.find(ns + "parts")
            self.assertIsNotNone(parts)
            objects = parts.find(ns + "part").find(ns + "objects")
            self.assertIsNotNone(objects)
            self.assertEqual(objects.attrib.get("count"), "0")
            self.assertEqual(len(objects.findall(ns + "object")), 0)
            symbols = content_parent.find(ns + "symbols")
            self.assertIsNotNone(symbols)
            self.assertGreater(len(symbols.findall(ns + "symbol")), 0)
            self.assertGreater(int(content_parent.find(ns + "templates").attrib["count"]), 0)

            validation = validate_omap_project(project, tmp_path)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["object_count"], 0)
            self.assertGreater(validation["symbol_count"], 0)


if __name__ == "__main__":
    unittest.main()
