import unittest
from copy import deepcopy
from datetime import datetime, timedelta

import dashboard as dashboard_module
from dashboard import (
    account_summary_data,
    account_summary_lock,
    app,
    portfolio_data,
    portfolio_lock,
)


class RiskTableEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with portfolio_lock:
            self._original_portfolio = deepcopy(portfolio_data)
            portfolio_data.clear()
            portfolio_data[101] = {
                "conId": 101,
                "account": "DU12345",
                "position": 2,
                "costBasis": 500.0,
                "marketValue": 600.0,
                "status": "Snapshot",
                "contract": {
                    "secType": "STK",
                    "symbol": "AAPL",
                    "multiplier": 1,
                },
                "greeks": {
                    "undPrice": 300.0,
                },
                "pnl": {
                    "daily": 0.0,
                },
            }
        with account_summary_lock:
            self._original_account_summary = deepcopy(account_summary_data)
            self._original_summary_ts = dashboard_module.account_summary_last_updated_ts
            account_summary_data.clear()
            dashboard_module.account_summary_last_updated_ts = 0.0

    def tearDown(self):
        with portfolio_lock:
            portfolio_data.clear()
            portfolio_data.update(self._original_portfolio)
        with account_summary_lock:
            account_summary_data.clear()
            account_summary_data.update(self._original_account_summary)
            dashboard_module.account_summary_last_updated_ts = self._original_summary_ts

    def test_get_risk_table_returns_spot_rows_for_stock_only(self):
        response = self.client.post(
            "/get_risk_table",
            json={
                "legs": [{"conId": 101, "qty": 2, "costBasis": 500.0}],
                "spot": 300.0,
                "time_steps": [0, 30],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(payload["spot"], 300.0)
        self.assertEqual(payload["cost_basis"], 500.0)
        self.assertEqual(payload["days_to_expiry"], 0)
        self.assertEqual(len(payload["rows"]), 2)

        for row in payload["rows"]:
            self.assertIn("days", row)
            self.assertEqual(row["dte"], 0)
            self.assertFalse(row["is_expiration"])
            self.assertEqual(row["pnl_at_spot"], 100.0)
            self.assertEqual(row["pnl_pct"], 20.0)
            self.assertEqual(row["delta"], 0.0)
            self.assertEqual(row["gamma"], 0.0)
            self.assertEqual(row["vega"], 0.0)
            self.assertEqual(row["theta"], 0.0)

    def test_get_risk_table_returns_404_for_unknown_legs(self):
        response = self.client.post(
            "/get_risk_table",
            json={"legs": [{"conId": 999999, "qty": 1}]},
        )

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertIn("error", payload)

    def test_get_pnl_by_date_returns_dynamic_greek_curves(self):
        response = self.client.post(
            "/get_pnl_by_date",
            json={
                "legs": [{"conId": 101, "qty": 2, "costBasis": 500.0}],
                "days_to_add": 4,
                "iv_shift": 0.12,
                "price_range": [290.0, 300.0],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["pnl_curve"], [80.0, 100.0])
        self.assertIn("greek_curves", payload)
        self.assertEqual(payload["greek_curves"]["delta"], [0.0, 0.0])
        self.assertEqual(payload["greek_curves"]["gamma"], [0.0, 0.0])
        self.assertEqual(payload["greek_curves"]["vega"], [0.0, 0.0])
        self.assertEqual(payload["greek_curves"]["theta"], [0.0, 0.0])

    def test_get_risk_table_includes_scenario_matrix_payload(self):
        response = self.client.post(
            "/get_risk_table",
            json={
                "legs": [{"conId": 101, "qty": 2, "costBasis": 500.0}],
                "spot": 300.0,
                "time_steps": [0, 4, 8],
                "strike_steps_each_side": 2,
                "strike_step_pct": 1.0,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("matrix", payload)

        matrix = payload["matrix"]
        self.assertEqual(len(matrix["time_columns"]), 3)
        self.assertEqual(len(matrix["price_axis"]), 5)
        self.assertEqual(matrix["atm_row_index"], 2)
        self.assertIn("metric_surfaces", matrix)
        self.assertEqual(matrix["metric_surfaces"]["pnl"][0][2], 100.0)
        self.assertEqual(matrix["metric_surfaces"]["pnl_pct"][0][2], 20.0)
        self.assertEqual(
            matrix["metric_surfaces"]["delta"][0], [0.0, 0.0, 0.0, 0.0, 0.0]
        )

    def test_get_sgpv_sim_normalizes_short_positions_to_absolute_exposure(self):
        short_response = self.client.post(
            "/get_sgpv_sim",
            json={
                "legs": [{"conId": 101, "qty": -2, "costBasis": 500.0}],
                "spot": 300.0,
                "net_liq": 10.0,
                "time_steps": [0],
            },
        )
        long_response = self.client.post(
            "/get_sgpv_sim",
            json={
                "legs": [{"conId": 101, "qty": 2, "costBasis": 500.0}],
                "spot": 300.0,
                "net_liq": 10.0,
                "time_steps": [0],
            },
        )

        self.assertEqual(short_response.status_code, 200)
        self.assertEqual(long_response.status_code, 200)

        short_payload = short_response.get_json()
        long_payload = long_response.get_json()

        self.assertEqual(short_payload["price_range"], long_payload["price_range"])
        self.assertEqual(
            short_payload["curves"]["t0_sgpv_curve"],
            long_payload["curves"]["t0_sgpv_curve"],
        )
        self.assertEqual(short_payload["metrics"]["sgpv_at_spot"], 600.0)
        self.assertEqual(short_payload["metrics"]["ratio_at_spot"], 60.0)
        self.assertEqual(short_payload["thresholds"]["open_restriction_ratio"], 30.0)
        self.assertEqual(short_payload["thresholds"]["liquidation_ratio"], 50.0)
        self.assertTrue(short_payload["breach_ranges"]["warning"])
        self.assertTrue(short_payload["breach_ranges"]["liquidation"])

    def test_get_sgpv_sim_filters_legs_by_selected_account(self):
        response = self.client.post(
            "/get_sgpv_sim",
            json={
                "legs": [{"conId": 101, "qty": 2, "costBasis": 500.0}],
                "selected_account": "DU00000",
                "spot": 300.0,
                "net_liq": 1000.0,
                "time_steps": [0],
            },
        )
        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertIn("selected account", payload.get("error", ""))

    def test_get_account_risk_context_returns_thresholds_and_account_defaults(self):
        response = self.client.post(
            "/get_account_risk_context",
            json={
                "selected_account": "DU12345",
                "legs": [{"conId": 101, "qty": 2, "costBasis": 500.0}],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["selected_account"], "DU12345")
        self.assertIn("DU12345", payload["accounts"])
        self.assertEqual(payload["net_liq"]["source"], "selected_legs_estimate")
        self.assertEqual(payload["net_liq"]["value"], 600.0)
        self.assertEqual(payload["thresholds"]["open_restriction_ratio"], 30.0)
        self.assertEqual(payload["thresholds"]["liquidation_ratio"], 50.0)
        self.assertEqual(payload["thresholds"]["open_restriction_value"], 18000.0)
        self.assertEqual(payload["thresholds"]["liquidation_value"], 30000.0)

    def test_get_account_risk_context_rejects_unknown_selected_account(self):
        response = self.client.post(
            "/get_account_risk_context",
            json={"selected_account": "DU99999"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn("error", payload)

    def test_get_account_risk_context_uses_tws_account_summary_when_available(self):
        with account_summary_lock:
            account_summary_data["DU12345"] = {
                "NetLiquidation": {
                    "value": "1000.00",
                    "currency": "USD",
                    "updated_at": 1.0,
                },
                "MaintMarginReq": {
                    "value": "120.00",
                    "currency": "USD",
                    "updated_at": 1.0,
                },
            }
            dashboard_module.account_summary_last_updated_ts = 1.0

        response = self.client.post(
            "/get_account_risk_context",
            json={
                "selected_account": "DU12345",
                "legs": [{"conId": 101, "qty": 2, "costBasis": 500.0}],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["net_liq"]["source"], "tws_account_summary")
        self.assertEqual(payload["net_liq"]["value"], 1000.0)
        self.assertEqual(payload["maintenance_margin"]["source"], "tws_account_summary")
        self.assertEqual(payload["maintenance_margin"]["value"], 120.0)
        self.assertTrue(payload["tws_account_summary"]["available"])
        self.assertIn("DU12345", payload["accounts"])

    def test_get_portfolio_risk_digest_returns_sgpv_ratio_and_thresholds(self):
        response = self.client.get("/get_portfolio_risk_digest")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(payload["selected_account"], "All")
        self.assertEqual(
            payload["net_liq"]["source"], "portfolio_market_value_abs_estimate"
        )
        self.assertEqual(payload["net_liq"]["value"], 600.0)
        self.assertEqual(payload["sgpv"]["value"], 600.0)
        self.assertEqual(payload["sgpv"]["ratio"], 1.0)
        self.assertEqual(payload["sgpv"]["open_restriction_ratio"], 30.0)
        self.assertEqual(payload["sgpv"]["liquidation_ratio"], 50.0)
        self.assertEqual(payload["sgpv"]["open_restriction_value"], 18000.0)
        self.assertEqual(payload["sgpv"]["liquidation_value"], 30000.0)
        self.assertEqual(
            payload["sgpv"]["source"], "portfolio_market_value_abs_estimate"
        )

    def test_get_portfolio_risk_digest_prefers_tws_sgpv_when_available(self):
        with account_summary_lock:
            account_summary_data["DU12345"] = {
                "NetLiquidation": {
                    "value": "1000.00",
                    "currency": "USD",
                    "updated_at": 1.0,
                },
                "GrossPositionValue": {
                    "value": "2500.00",
                    "currency": "USD",
                    "updated_at": 1.0,
                },
            }
            dashboard_module.account_summary_last_updated_ts = 1.0

        response = self.client.get("/get_portfolio_risk_digest?account=DU12345")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(payload["selected_account"], "DU12345")
        self.assertEqual(payload["net_liq"]["source"], "tws_account_summary")
        self.assertEqual(payload["net_liq"]["value"], 1000.0)
        self.assertEqual(payload["sgpv"]["source"], "tws_account_summary")
        self.assertEqual(payload["sgpv"]["value"], 2500.0)
        self.assertEqual(payload["sgpv"]["ratio"], 2.5)

    def test_get_portfolio_risk_digest_includes_expiring_soon_options(self):
        near_expiry = (datetime.now().date() + timedelta(days=3)).strftime("%Y%m%d")
        with portfolio_lock:
            portfolio_data[202] = {
                "conId": 202,
                "account": "DU12345",
                "position": 1,
                "costBasis": 100.0,
                "marketValue": 110.0,
                "status": "Snapshot",
                "description": "AAPL near option",
                "contract": {
                    "secType": "OPT",
                    "symbol": "AAPL",
                    "strike": 310.0,
                    "right": "C",
                    "expiry": near_expiry,
                    "multiplier": 100,
                },
                "greeks": {"undPrice": 300.0},
                "pnl": {"daily": 0.0},
            }

        response = self.client.get("/get_portfolio_risk_digest")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["expiring_soon"])
        first = payload["expiring_soon"][0]
        self.assertEqual(first["conId"], 202)
        self.assertEqual(first["expiry"], near_expiry)

    def test_get_portfolio_risk_digest_rejects_unknown_account_filter(self):
        response = self.client.get("/get_portfolio_risk_digest?account=DU404")
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
