import unittest
from unittest.mock import patch

from orimap_prep.oom_setup import declination_bgs_wmm2025


class _Resp:
    def __init__(self, dec):
        self.dec = dec
    def raise_for_status(self):
        pass
    def json(self):
        return {"geomagnetic-field-model-result": {
            "field-value": {"declination": {"value": self.dec}},
            "date": {"value": "2026-09-20"},
            "coordinates": {"latitude": {"value": 49.9}, "longitude": {"value": 13.0}, "altitude": {"value": 0}},
            "model": "wmm", "model_revision": "2025"
        }}


class DeclinationTests(unittest.TestCase):
    def test_bgs_signed_east_positive_is_converted_to_oom_signed(self):
        with patch("orimap_prep.oom_setup.requests.get", return_value=_Resp(4.81)):
            d = declination_bgs_wmm2025(49.9, 13.0, "2026-09-20")
        self.assertEqual(d["declination_deg_east_positive"], 4.81)
        self.assertEqual(d["direction"], "E")
        self.assertEqual(d["declination_deg_oom"], -4.81)

    def test_west_declination_keeps_model_sign_and_flips_for_oom(self):
        with patch("orimap_prep.oom_setup.requests.get", return_value=_Resp(-2.5)):
            d = declination_bgs_wmm2025(49.9, 13.0, "2026-09-20")
        self.assertEqual(d["declination_deg_east_positive"], -2.5)
        self.assertEqual(d["direction"], "W")
        self.assertEqual(d["declination_deg_oom"], 2.5)


if __name__ == "__main__":
    unittest.main()
