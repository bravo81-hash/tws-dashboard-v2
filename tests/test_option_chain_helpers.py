import unittest
from copy import deepcopy
from types import SimpleNamespace

import dashboard as dashboard_module


def _contract_detail(con_id, strike, right):
    contract = SimpleNamespace(
        conId=con_id,
        strike=float(strike),
        right=str(right),
        secType="OPT",
    )
    return SimpleNamespace(contract=contract)


class OptionChainHelperTests(unittest.TestCase):
    def setUp(self):
        self._original_contract_cache = deepcopy(
            dashboard_module.option_chain_contract_cache
        )
        dashboard_module.option_chain_contract_cache.clear()

    def tearDown(self):
        dashboard_module.option_chain_contract_cache.clear()
        dashboard_module.option_chain_contract_cache.update(
            self._original_contract_cache
        )

    def test_resolve_chain_mark_prefers_bid_ask_then_last_then_model_then_close(self):
        resolve = dashboard_module.resolve_chain_mark_and_quality

        mark, source, quality = resolve(
            bid=1.2,
            ask=1.4,
            last=1.3,
            model=1.5,
            close=1.6,
        )
        self.assertAlmostEqual(mark, 1.3, places=6)
        self.assertEqual(source, "live")
        self.assertEqual(quality, "live")

        mark, source, quality = resolve(
            bid=None,
            ask=None,
            last=1.25,
            model=1.5,
            close=1.6,
        )
        self.assertAlmostEqual(mark, 1.25, places=6)
        self.assertEqual(source, "live")
        self.assertEqual(quality, "live")

        mark, source, quality = resolve(
            bid=None,
            ask=None,
            last=None,
            model=1.45,
            close=1.6,
        )
        self.assertAlmostEqual(mark, 1.45, places=6)
        self.assertEqual(source, "model")
        self.assertEqual(quality, "fallback")

        mark, source, quality = resolve(
            bid=None,
            ask=None,
            last=None,
            model=None,
            close=1.55,
        )
        self.assertAlmostEqual(mark, 1.55, places=6)
        self.assertEqual(source, "close")
        self.assertEqual(quality, "fallback")

        mark, source, quality = resolve(
            bid=None,
            ask=None,
            last=None,
            model=None,
            close=None,
        )
        self.assertIsNone(mark)
        self.assertEqual(source, "none")
        self.assertEqual(quality, "missing")

    def test_select_chain_contracts_for_stream_uses_centered_strike_window(self):
        select = dashboard_module.select_chain_contracts_for_stream

        contracts = []
        con_id = 1000
        for strike in range(90, 111):
            contracts.append(_contract_detail(con_id, strike, "C"))
            con_id += 1
            contracts.append(_contract_detail(con_id, strike, "P"))
            con_id += 1

        selected = select(contracts, spot_price=100.0, strike_half_width=2)
        selected_strikes = sorted(
            {
                int(round(item.contract.strike))
                for item in selected
            }
        )

        self.assertEqual(selected_strikes, [98, 99, 100, 101, 102])
        self.assertEqual(len(selected), 10)

    def test_merge_chain_snapshot_into_leg_fills_missing_but_preserves_live_values(self):
        merge = dashboard_module.merge_chain_snapshot_into_leg

        leg = {
            "bid": 1.10,
            "ask": 1.30,
            "last": None,
            "close": None,
            "delayed_last": None,
            "modelPrice": None,
            "iv": None,
            "delta": None,
        }
        snapshot = {
            "bid": 1.00,
            "ask": 1.40,
            "last": 1.25,
            "close": 1.20,
            "delayed_last": 1.22,
            "modelPrice": 1.28,
            "iv": 0.24,
            "delta": 0.31,
        }

        merge(leg, snapshot)

        self.assertAlmostEqual(leg["bid"], 1.10)
        self.assertAlmostEqual(leg["ask"], 1.30)
        self.assertAlmostEqual(leg["last"], 1.25)
        self.assertAlmostEqual(leg["close"], 1.20)
        self.assertAlmostEqual(leg["delayed_last"], 1.22)
        self.assertAlmostEqual(leg["modelPrice"], 1.28)
        self.assertAlmostEqual(leg["iv"], 0.24)
        self.assertAlmostEqual(leg["delta"], 0.31)

    def test_update_quote_bucket_from_tick_updates_expected_fields(self):
        update = dashboard_module.update_quote_bucket_from_tick
        bucket = {
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "delayed_last": None,
        }

        update(bucket, 1, 1.10)
        update(bucket, 2, 1.20)
        update(bucket, 4, 1.15)
        update(bucket, 9, 1.11)
        update(bucket, 66, 1.13)

        self.assertAlmostEqual(bucket["bid"], 1.10)
        self.assertAlmostEqual(bucket["ask"], 1.20)
        self.assertAlmostEqual(bucket["last"], 1.15)
        self.assertAlmostEqual(bucket["close"], 1.11)
        self.assertAlmostEqual(bucket["delayed_last"], 1.13)

    def test_option_chain_contract_cache_returns_fresh_entries(self):
        set_cache = dashboard_module.set_cached_option_chain_contracts
        get_cache = dashboard_module.get_cached_option_chain_contracts

        contracts = [_contract_detail(5001, 100, "C"), _contract_detail(5002, 100, "P")]
        set_cache("SPY", "20260515", contracts, now_ts=1000.0)

        cached = get_cache("SPY", "20260515", now_ts=1050.0)
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 2)
        self.assertEqual(cached[0].contract.conId, 5001)
        self.assertEqual(cached[1].contract.conId, 5002)

    def test_option_chain_contract_cache_expires_old_entries(self):
        set_cache = dashboard_module.set_cached_option_chain_contracts
        get_cache = dashboard_module.get_cached_option_chain_contracts
        ttl = dashboard_module.OPTION_CHAIN_CONTRACT_CACHE_TTL_SEC

        contracts = [_contract_detail(6001, 95, "C")]
        set_cache("QQQ", "20260619", contracts, now_ts=2000.0)

        expired = get_cache("QQQ", "20260619", now_ts=2000.0 + ttl + 1.0)
        self.assertIsNone(expired)


if __name__ == "__main__":
    unittest.main()
