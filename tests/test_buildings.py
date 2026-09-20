import unittest
from pathlib import Path

from orimap_prep.buildings import RUIAN_BUILDINGS_LAYER_ID, RUIAN_BUILDINGS_SERVICE, ruian_buildings_query_url
from orimap_prep.config import DEFAULT_PROJECT_ROOT, JobConfig
from orimap_prep.pipeline import project_paths


class BuildingsTests(unittest.TestCase):
    def test_buildings_output_folder_is_05_buildings(self):
        cfg = JobConfig(input_gpx=Path("input.gpx"), project_id="test")
        self.assertEqual(project_paths(cfg)["buildings"], DEFAULT_PROJECT_ROOT / "test" / "05_buildings")

    def test_ruian_buildings_query_uses_verified_layer_3_and_epsg5514(self):
        url = ruian_buildings_query_url({"minx": -850000, "miny": -1050000, "maxx": -849000, "maxy": -1049000})
        self.assertIn(f"/{RUIAN_BUILDINGS_LAYER_ID}/query", url)
        self.assertEqual(RUIAN_BUILDINGS_LAYER_ID, 3)
        self.assertTrue(RUIAN_BUILDINGS_SERVICE.endswith("/RUIAN/Prohlizeci_sluzba_nad_daty_RUIAN/MapServer"))
        self.assertIn("outSR=5514", url)
        self.assertIn("f=geojson", url)


if __name__ == "__main__":
    unittest.main()
