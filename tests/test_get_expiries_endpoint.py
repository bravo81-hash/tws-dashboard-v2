import unittest
from copy import deepcopy
from types import SimpleNamespace

import dashboard as dashboard_module
from dashboard import app, underlying_prices


class _FakeIBAppForExpiries:
    def __init__(self, *, qualified_conid=0, expirations=None):
        self._connected = True
        self.next_req_id = 5000
        self.req_map = {}
        self.calls = []
        self.qualified_conid = int(qualified_conid or 0)
        self.expirations = set(expirations or {"20260419"})

    def isConnected(self):
        return self._connected

    def reqContractDetails(self, req_id, contract):
        self.calls.append(
            (
                "reqContractDetails",
                req_id,
                getattr(contract, "symbol", None),
                getattr(contract, "secType", None),
                getattr(contract, "exchange", None),
            )
        )
        req = self.req_map.get(req_id)
        if isinstance(req, dict):
            req["contract"] = SimpleNamespace(conId=self.qualified_conid)
            req["event"].set()

    def reqSecDefOptParams(
        self, req_id, underlying_symbol, fut_fop_exchange, underlying_sec_type, con_id
    ):
        self.calls.append(
            (
                "reqSecDefOptParams",
                req_id,
                underlying_symbol,
                fut_fop_exchange,
                underlying_sec_type,
                con_id,
            )
        )
        req = self.req_map.get(req_id)
        if isinstance(req, dict):
            req.setdefault("expirations", set()).update(self.expirations)
            req["event"].set()

    def reqMktData(self, *args, **kwargs):
        self.calls.append(("reqMktData", args, kwargs))

    def cancelMktData(self, req_id):
        self.calls.append(("cancelMktData", req_id))


class GetExpiriesEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._original_ib_app = dashboard_module.ib_app
        self._original_underlying_prices = deepcopy(underlying_prices)

    def tearDown(self):
        dashboard_module.ib_app = self._original_ib_app
        underlying_prices.clear()
        underlying_prices.update(self._original_underlying_prices)

    def test_get_expiries_qualifies_index_contract_before_secdef_request(self):
        fake = _FakeIBAppForExpiries(qualified_conid=416904)
        dashboard_module.ib_app = fake
        underlying_prices["SPX"] = 5000.0

        response = self.client.get("/get_expiries?symbol=SPX")
        self.assertEqual(response.status_code, 200)

        contract_calls = [c for c in fake.calls if c[0] == "reqContractDetails"]
        self.assertEqual(len(contract_calls), 1)
        self.assertEqual(contract_calls[0][2], "SPX")
        self.assertEqual(contract_calls[0][3], "IND")

        secdef_calls = [c for c in fake.calls if c[0] == "reqSecDefOptParams"]
        self.assertEqual(len(secdef_calls), 1)
        self.assertEqual(secdef_calls[0][5], 416904)

    def test_get_expiries_for_stock_skips_contract_qualification(self):
        fake = _FakeIBAppForExpiries(qualified_conid=123456)
        dashboard_module.ib_app = fake
        underlying_prices["AAPL"] = 180.0

        response = self.client.get("/get_expiries?symbol=AAPL")
        self.assertEqual(response.status_code, 200)

        contract_calls = [c for c in fake.calls if c[0] == "reqContractDetails"]
        self.assertEqual(len(contract_calls), 0)

        secdef_calls = [c for c in fake.calls if c[0] == "reqSecDefOptParams"]
        self.assertEqual(len(secdef_calls), 1)
        self.assertEqual(secdef_calls[0][5], 0)


if __name__ == "__main__":
    unittest.main()
