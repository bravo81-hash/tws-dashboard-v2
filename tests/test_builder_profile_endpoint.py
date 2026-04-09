import unittest

from dashboard import app


class BuilderProfileEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_get_builder_profile_put_debit_spread_metrics(self):
        response = self.client.post(
            "/get_builder_profile",
            json={
                "undPrice": 6750.0,
                "ivShift": 0.0,
                "tPlusDays": 0,
                "commission": 0.65,
                "offset": 0.0,
                "legs": [
                    {
                        "side": "BUY",
                        "qty": 1,
                        "right": "P",
                        "strike": 6750.0,
                        "expiry": "20260619",
                        "iv": 0.2,
                        "price": 82.10,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                    {
                        "side": "SELL",
                        "qty": 1,
                        "right": "P",
                        "strike": 6745.0,
                        "expiry": "20260619",
                        "iv": 0.2,
                        "price": 80.35,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        metrics = payload["metrics"]

        # Debit spread net cost: (82.10 - 80.35) * 100 + 2 * 0.65 = 176.30
        self.assertAlmostEqual(metrics["netCost"], 176.30, places=2)
        self.assertAlmostEqual(metrics["maxLoss"], -176.30, places=2)
        self.assertAlmostEqual(metrics["maxProfit"], 323.70, places=2)
        self.assertEqual(len(metrics["breakevens"]), 1)
        self.assertAlmostEqual(metrics["breakevens"][0], 6748.24, places=2)


if __name__ == "__main__":
    unittest.main()
