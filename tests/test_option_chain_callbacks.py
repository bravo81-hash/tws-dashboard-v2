import threading
import unittest
from types import SimpleNamespace

import dashboard as dashboard_module


class OptionChainCallbackTests(unittest.TestCase):
    def test_contract_details_appends_for_chain_requests(self):
        ib_app = dashboard_module.IBKRApp()
        req_id = 101
        ib_app.req_map[req_id] = {
            "event": threading.Event(),
            "contracts": [],
            "req_type": "chain_details",
        }

        contract_a = SimpleNamespace(conId=111)
        contract_b = SimpleNamespace(conId=222)

        ib_app.contractDetails(req_id, SimpleNamespace(contract=contract_a))
        ib_app.contractDetails(req_id, SimpleNamespace(contract=contract_b))

        cached = ib_app.req_map[req_id]["contracts"]
        self.assertEqual(len(cached), 2)
        self.assertIs(cached[0].contract, contract_a)
        self.assertIs(cached[1].contract, contract_b)

    def test_contract_details_sets_single_contract_for_non_chain_requests(self):
        ib_app = dashboard_module.IBKRApp()
        req_id = 202
        ib_app.req_map[req_id] = {
            "event": threading.Event(),
            "contract": None,
        }
        contract = SimpleNamespace(conId=333)

        ib_app.contractDetails(req_id, SimpleNamespace(contract=contract))

        self.assertIs(ib_app.req_map[req_id]["contract"], contract)

    def test_snapshot_chain_ticks_are_captured_and_event_is_signaled(self):
        ib_app = dashboard_module.IBKRApp()
        req_id = 303
        event = threading.Event()
        ib_app.req_map[req_id] = {
            "event": event,
            "snapshot_chain_leg": {
                "conId": 444,
                "bid": None,
                "ask": None,
                "last": None,
                "close": None,
                "delayed_last": None,
                "modelPrice": None,
                "iv": None,
                "delta": None,
            },
        }

        ib_app.tickPrice(req_id, 1, 1.10, None)   # bid
        ib_app.tickPrice(req_id, 2, 1.30, None)   # ask
        ib_app.tickPrice(req_id, 4, 1.20, None)   # last
        ib_app.tickPrice(req_id, 9, 1.15, None)   # close
        ib_app.tickPrice(req_id, 66, 1.18, None)  # delayed_last

        snap = ib_app.req_map[req_id]["snapshot_chain_leg"]
        self.assertAlmostEqual(snap["bid"], 1.10)
        self.assertAlmostEqual(snap["ask"], 1.30)
        self.assertAlmostEqual(snap["last"], 1.20)
        self.assertAlmostEqual(snap["close"], 1.15)
        self.assertAlmostEqual(snap["delayed_last"], 1.18)

        self.assertFalse(event.is_set())
        ib_app.tickSnapshotEnd(req_id)
        self.assertTrue(event.is_set())

    def test_snapshot_chain_option_computation_is_captured(self):
        ib_app = dashboard_module.IBKRApp()
        req_id = 404
        ib_app.req_map[req_id] = {
            "event": threading.Event(),
            "snapshot_chain_leg": {
                "conId": 555,
                "bid": None,
                "ask": None,
                "last": None,
                "close": None,
                "delayed_last": None,
                "modelPrice": None,
                "iv": None,
                "delta": None,
            },
        }

        ib_app.tickOptionComputation(
            req_id,
            13,
            0,
            0.22,
            0.31,
            1.45,
            0.0,
            0.05,
            0.1,
            -0.02,
            5123.0,
        )

        snap = ib_app.req_map[req_id]["snapshot_chain_leg"]
        self.assertAlmostEqual(snap["iv"], 0.22)
        self.assertAlmostEqual(snap["delta"], 0.31)
        self.assertAlmostEqual(snap["modelPrice"], 1.45)


if __name__ == "__main__":
    unittest.main()
