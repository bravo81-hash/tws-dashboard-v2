import unittest
from copy import deepcopy

from dashboard import app, portfolio_data, portfolio_lock


class RiskProfileEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with portfolio_lock:
            self._original_portfolio = deepcopy(portfolio_data)
            portfolio_data.clear()

    def tearDown(self):
        with portfolio_lock:
            portfolio_data.clear()
            portfolio_data.update(self._original_portfolio)

    def test_modeled_leg_falls_back_when_portfolio_leg_is_not_live(self):
        with portfolio_lock:
            portfolio_data[123456] = {
                "conId": 123456,
                "status": "Queued",
                "account": "DU12345",
                "contract": {
                    "secType": "OPT",
                    "symbol": "SPX",
                    "right": "C",
                    "strike": 5000.0,
                    "expiry": "20260619",
                    "multiplier": 100,
                },
                "greeks": {
                    "iv": 0.18,
                    "undPrice": 5200.0,
                },
            }

        response = self.client.post(
            "/get_risk_profile",
            json={
                "legs": [
                    {
                        "conId": 123456,
                        "qty": 1,
                        "costBasis": -125.0,
                        "secType": "OPT",
                        "symbol": "SPX",
                        "right": "C",
                        "strike": 5000.0,
                        "expiry": "20260619",
                        "iv": 0.2,
                        "multiplier": 100,
                        "undPrice": 5200.0,
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("price_range", payload)
        self.assertIn("metrics", payload)
        self.assertTrue(payload["price_range"])


if __name__ == "__main__":
    unittest.main()
