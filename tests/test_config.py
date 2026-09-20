import unittest

from orimap_prep.config import DEFAULT_MAP_TYPE, DEFAULT_PRODUCTS, parse_products, parse_contours, parse_area_name, parse_drive_upload, default_map_scale


FULL_DEFAULT = ["dem", "hillshade", "hillshade_multidirectional", "contours", "slope", "ortho", "cir_orthophoto", "buildings", "dmp", "surface_height", "vegetation_height"]


class ConfigDefaultsTests(unittest.TestCase):
    def test_default_products_are_full_base_layers_with_buildings(self):
        self.assertEqual(DEFAULT_PRODUCTS, FULL_DEFAULT)
        self.assertEqual(DEFAULT_MAP_TYPE, "forest")

    def test_basic_request_uses_full_default_products(self):
        self.assertEqual(parse_products("Připrav OB podklady z tohoto GPX."), FULL_DEFAULT)

    def test_explicit_replace_still_wins(self):
        self.assertEqual(parse_products("Chci pouze DEM a ortofoto."), ["dem", "ortho"])
        self.assertEqual(parse_products("Chci jen budovy."), ["buildings"])

    def test_contours_override_without_changing_products(self):
        self.assertEqual(parse_contours("Připrav podklady, vrstevnice 2.5 a 5 m."), [2.5, 5.0])
        self.assertEqual(parse_products("Připrav podklady, vrstevnice 2.5 a 5 m."), FULL_DEFAULT)

    def test_area_name_drive_and_sprint_defaults(self):
        self.assertEqual(parse_area_name("Připrav OB podklady, název mapy: Brdy sever."), "Brdy sever")
        self.assertTrue(parse_drive_upload("Připrav to a dej to na Google Drive."))
        self.assertFalse(parse_drive_upload("Připrav podklady lokálně."))
        self.assertEqual(default_map_scale("forest"), 10000)
        self.assertEqual(default_map_scale("sprint"), 4000)


if __name__ == "__main__":
    unittest.main()
