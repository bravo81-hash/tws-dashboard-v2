import os
import unittest
from unittest.mock import patch

from client_portal_adapter import ClientPortalAdapter


class ClientPortalAdapterTests(unittest.TestCase):
    def test_from_env_defaults_to_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            adapter = ClientPortalAdapter.from_env()
        self.assertFalse(adapter.enabled)
        self.assertEqual(adapter.base_url, "https://localhost:5000/v1/api")
        self.assertFalse(adapter.verify_ssl)
        self.assertEqual(adapter.timeout_sec, 2.0)

    def test_disabled_health_does_not_probe_network(self):
        adapter = ClientPortalAdapter(enabled=False)
        health = adapter.health()
        self.assertEqual(health["enabled"], False)
        self.assertEqual(health["checked"], False)
        self.assertEqual(health["reachable"], False)
        self.assertNotIn("status_code", health)

    def test_from_env_parses_values(self):
        with patch.dict(
            os.environ,
            {
                "CLIENT_PORTAL_ENABLED": "true",
                "CLIENT_PORTAL_BASE_URL": "https://127.0.0.1:5005/v1/api",
                "CLIENT_PORTAL_VERIFY_SSL": "1",
                "CLIENT_PORTAL_TIMEOUT_SEC": "3.5",
            },
            clear=True,
        ):
            adapter = ClientPortalAdapter.from_env()
        self.assertTrue(adapter.enabled)
        self.assertEqual(adapter.base_url, "https://127.0.0.1:5005/v1/api")
        self.assertTrue(adapter.verify_ssl)
        self.assertEqual(adapter.timeout_sec, 3.5)

    def test_disabled_account_risk_context_returns_unavailable(self):
        adapter = ClientPortalAdapter(enabled=False)
        context = adapter.account_risk_context("DU12345")
        self.assertFalse(context["enabled"])
        self.assertFalse(context["available"])
        self.assertIsNone(context["net_liq"])
        self.assertIsNone(context["maintenance_margin"])

    def test_account_risk_context_parses_netliq_and_maintenance(self):
        adapter = ClientPortalAdapter(enabled=True)
        with patch.object(
            adapter,
            "_request_json",
            side_effect=[
                {"ok": True, "data": {"accounts": ["DU12345"]}},
                {
                    "ok": True,
                    "data": [
                        {"key": "NetLiquidation", "value": "12345.67"},
                        {"key": "MaintMarginReq", "value": "891.25"},
                    ],
                },
            ],
        ):
            context = adapter.account_risk_context("DU12345")

        self.assertTrue(context["enabled"])
        self.assertTrue(context["available"])
        self.assertEqual(context["net_liq"], 12345.67)
        self.assertEqual(context["maintenance_margin"], 891.25)
        self.assertEqual(context["source"], "portfolio/DU12345/summary")


if __name__ == "__main__":
    unittest.main()
