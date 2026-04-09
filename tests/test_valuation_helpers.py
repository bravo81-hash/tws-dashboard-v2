import unittest

from dashboard import (
    calculate_expiration_pnl,
    calculate_greeks_at_point,
    calculate_greek_surface,
    calculate_pnl_curve,
    derive_cost_basis_for_qty,
    find_breakevens,
    get_contract_multiplier,
)


class ValuationHelpersTests(unittest.TestCase):
    def test_get_contract_multiplier_defaults_to_100(self):
        self.assertEqual(get_contract_multiplier(None), 100.0)
        self.assertEqual(get_contract_multiplier({}), 100.0)
        self.assertEqual(get_contract_multiplier({"multiplier": 0}), 100.0)

    def test_get_contract_multiplier_uses_contract_value(self):
        self.assertEqual(get_contract_multiplier({"multiplier": "50"}), 50.0)
        self.assertEqual(get_contract_multiplier({"multiplier": 25}), 25.0)

    def test_derive_cost_basis_for_qty_prefers_explicit_value(self):
        tws_data = {"position": 2, "costBasis": 500.0}
        self.assertEqual(
            derive_cost_basis_for_qty(tws_data, 1, explicit_cost_basis="123.45"), 123.45
        )

    def test_derive_cost_basis_for_qty_scales_with_position(self):
        tws_data = {"position": 4, "costBasis": 2000.0}
        self.assertEqual(derive_cost_basis_for_qty(tws_data, 1), 500.0)
        self.assertEqual(derive_cost_basis_for_qty(tws_data, -2), -1000.0)

    def test_derive_cost_basis_for_qty_returns_zero_for_zero_or_missing_position(self):
        self.assertEqual(
            derive_cost_basis_for_qty({"position": 0, "costBasis": 1000.0}, 2), 0.0
        )
        self.assertEqual(derive_cost_basis_for_qty({}, 2), 0.0)
        self.assertEqual(derive_cost_basis_for_qty(None, 2), 0.0)

    def test_calculate_pnl_curve_matches_for_tws_and_builder_shape(self):
        price_range = [90.0, 100.0, 110.0]

        tws_leg_shape = [
            {
                "qty": 2,
                "costBasis": 1000.0,
                "tws_data": {
                    "contract": {"secType": "STK", "multiplier": 5},
                    "greeks": {},
                },
            }
        ]
        builder_leg_shape = [
            {
                "qty": 2,
                "costBasis": 1000.0,
                "secType": "STK",
                "multiplier": 5,
            }
        ]

        tws_curve = calculate_pnl_curve(tws_leg_shape, price_range)
        builder_curve = calculate_pnl_curve(builder_leg_shape, price_range)

        self.assertEqual(tws_curve, builder_curve)
        self.assertEqual(tws_curve, [-100.0, 0.0, 100.0])

    def test_option_intrinsic_path_is_deterministic_for_expired_contract(self):
        option_leg = [
            {
                "qty": 1,
                "costBasis": 0.0,
                "right": "C",
                "strike": 100.0,
                "expiry": "20000101",
                "iv": 0.0,
                "multiplier": 100.0,
                "secType": "OPT",
            }
        ]
        price_range = [90.0, 110.0]

        self.assertEqual(calculate_pnl_curve(option_leg, price_range), [0.0, 1000.0])
        self.assertEqual(
            calculate_expiration_pnl(option_leg, price_range), [0.0, 1000.0]
        )

    def test_calculate_expiration_pnl_stock_only_uses_multiplier(self):
        stock_leg = [
            {
                "qty": 3,
                "costBasis": 1200.0,
                "secType": "STK",
                "multiplier": 2,
            }
        ]
        price_range = [100.0, 200.0]
        self.assertEqual(
            calculate_expiration_pnl(stock_leg, price_range), [-600.0, 0.0]
        )

    def test_find_breakevens_returns_sorted_unique_crossings(self):
        prices = [90.0, 100.0, 110.0, 120.0]
        pnls = [-10.0, 10.0, -10.0, 10.0]
        self.assertEqual(find_breakevens(prices, pnls), [95.0, 105.0, 115.0])

    def test_calculate_greek_surface_invalid_name_returns_empty(self):
        legs = [
            {
                "qty": 1,
                "costBasis": 0.0,
                "right": "C",
                "strike": 100.0,
                "expiry": "20300101",
                "iv": 0.2,
                "multiplier": 100.0,
                "secType": "OPT",
            }
        ]
        surface = calculate_greek_surface(legs, [100.0, 101.0], [0, 10], "invalid")
        self.assertEqual(surface, [])

    def test_calculate_greeks_at_point_stock_only_returns_zeroes(self):
        stock_leg = [
            {
                "qty": 10,
                "costBasis": 1000.0,
                "secType": "STK",
                "multiplier": 1,
            }
        ]
        self.assertEqual(
            calculate_greeks_at_point(
                stock_leg, price=100.0, days_to_add=0, iv_shift=0.0
            ),
            {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0},
        )


if __name__ == "__main__":
    unittest.main()
