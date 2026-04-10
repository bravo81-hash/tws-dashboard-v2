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

    def test_get_builder_profile_call_credit_spread_metrics(self):
        response = self.client.post(
            "/get_builder_profile",
            json={
                "undPrice": 455.0,
                "ivShift": 0.0,
                "tPlusDays": 0,
                "commission": 0.65,
                "offset": 0.0,
                "legs": [
                    {
                        "side": "SELL",
                        "qty": 1,
                        "right": "C",
                        "strike": 455.0,
                        "expiry": "20260619",
                        "iv": 0.18,
                        "price": 2.40,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                    {
                        "side": "BUY",
                        "qty": 1,
                        "right": "C",
                        "strike": 460.0,
                        "expiry": "20260619",
                        "iv": 0.18,
                        "price": 1.10,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        metrics = payload["metrics"]

        # Credit spread net credit after commissions:
        # (2.40 - 1.10) * 100 - (2 * 0.65) = 128.70
        self.assertAlmostEqual(metrics["netCost"], -128.70, places=2)
        self.assertAlmostEqual(metrics["maxProfit"], 128.70, places=2)
        self.assertAlmostEqual(metrics["maxLoss"], -371.30, places=2)
        self.assertEqual(len(metrics["breakevens"]), 1)
        self.assertAlmostEqual(metrics["breakevens"][0], 456.29, places=2)

    def test_get_builder_profile_iron_condor_metrics(self):
        response = self.client.post(
            "/get_builder_profile",
            json={
                "undPrice": 450.0,
                "ivShift": 0.0,
                "tPlusDays": 0,
                "commission": 0.65,
                "offset": 0.0,
                "legs": [
                    {
                        "side": "SELL",
                        "qty": 1,
                        "right": "P",
                        "strike": 430.0,
                        "expiry": "20260619",
                        "iv": 0.19,
                        "price": 3.20,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                    {
                        "side": "BUY",
                        "qty": 1,
                        "right": "P",
                        "strike": 425.0,
                        "expiry": "20260619",
                        "iv": 0.19,
                        "price": 1.40,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                    {
                        "side": "SELL",
                        "qty": 1,
                        "right": "C",
                        "strike": 470.0,
                        "expiry": "20260619",
                        "iv": 0.19,
                        "price": 3.10,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                    {
                        "side": "BUY",
                        "qty": 1,
                        "right": "C",
                        "strike": 475.0,
                        "expiry": "20260619",
                        "iv": 0.19,
                        "price": 1.20,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        metrics = payload["metrics"]

        # Iron condor net credit after commissions:
        # (3.20 - 1.40 + 3.10 - 1.20) * 100 - (4 * 0.65) = 367.40
        self.assertAlmostEqual(metrics["netCost"], -367.40, places=2)
        self.assertAlmostEqual(metrics["maxProfit"], 367.40, places=2)
        self.assertAlmostEqual(metrics["maxLoss"], -132.60, places=2)
        self.assertEqual(len(metrics["breakevens"]), 2)
        self.assertAlmostEqual(metrics["breakevens"][0], 426.33, places=2)
        self.assertAlmostEqual(metrics["breakevens"][1], 473.67, places=2)

    def test_get_builder_profile_put_ratio_backspread_has_finite_loss(self):
        response = self.client.post(
            "/get_builder_profile",
            json={
                "undPrice": 450.0,
                "ivShift": 0.0,
                "tPlusDays": 0,
                "commission": 0.65,
                "offset": 0.0,
                "legs": [
                    {
                        "side": "SELL",
                        "qty": 1,
                        "right": "P",
                        "strike": 450.0,
                        "expiry": "20260619",
                        "iv": 0.2,
                        "price": 9.80,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                    {
                        "side": "BUY",
                        "qty": 2,
                        "right": "P",
                        "strike": 440.0,
                        "expiry": "20260619",
                        "iv": 0.2,
                        "price": 6.10,
                        "multiplier": 100.0,
                        "secType": "OPT",
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        metrics = payload["metrics"]

        # Put ratio backspread has finite downside loss for non-negative underlyings.
        self.assertAlmostEqual(metrics["netCost"], 241.95, places=2)
        self.assertAlmostEqual(metrics["maxLoss"], -1241.95, places=2)
        self.assertAlmostEqual(metrics["maxProfit"], 6758.05, places=2)
        self.assertEqual(len(metrics["breakevens"]), 1)
        self.assertAlmostEqual(metrics["breakevens"][0], 427.58, places=2)


if __name__ == "__main__":
    unittest.main()
