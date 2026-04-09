import math
from datetime import datetime, timedelta

import numpy as np
from py_vollib.black_scholes import black_scholes as bs_price
from py_vollib.black_scholes.greeks.analytical import delta, gamma, theta, vega

RISK_FREE_RATE = 0.05


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_contract_multiplier(contract_data, default=100.0):
    multiplier = safe_float((contract_data or {}).get("multiplier", default), default)
    return multiplier if multiplier else default


def derive_cost_basis_for_qty(tws_data, qty, explicit_cost_basis=None):
    if explicit_cost_basis is not None:
        return safe_float(explicit_cost_basis, 0.0)
    if not tws_data:
        return 0.0
    position = safe_float(tws_data.get("position"), 0.0)
    if position == 0:
        return 0.0
    return (safe_float(tws_data.get("costBasis"), 0.0) / position) * safe_float(
        qty, 0.0
    )


def calculate_pnl_curve(legs_with_details, price_range, days_to_add=0, iv_shift=0.0):
    total_cost_basis = sum(leg.get("costBasis", 0) or 0 for leg in legs_with_details)
    today = datetime.now()
    sim_date = today + timedelta(days=days_to_add)
    pnl_curve = []

    for price in price_range:
        sim_value = 0.0
        for leg in legs_with_details:
            tws_leg_data = leg.get("tws_data")
            if tws_leg_data:
                pos = leg["qty"]
                contract = tws_leg_data["contract"]
                greeks = tws_leg_data["greeks"]
                leg_multiplier = get_contract_multiplier(contract)
            else:
                pos = leg["qty"]
                contract = leg
                greeks = leg
                leg_multiplier = get_contract_multiplier(contract)

            if contract.get("secType", "OPT") != "OPT":
                sim_value += price * pos * leg_multiplier
                continue

            K = contract["strike"]
            r_type = contract["right"].lower()
            initial_iv = greeks.get("iv", 0)
            sim_iv = (
                initial_iv * (1 + iv_shift) if initial_iv and initial_iv > 0 else 0.0001
            )
            expiry_dt = datetime.strptime(contract["expiry"], "%Y%m%d")
            T_sim = max(1e-9, (expiry_dt - sim_date).days / 365.25)

            try:
                if T_sim > 1e-9 and sim_iv > 1e-9:
                    leg_price = bs_price(
                        r_type, price, K, T_sim, RISK_FREE_RATE, sim_iv
                    )
                    leg_price = max(0, leg_price)
                else:
                    leg_price = (
                        max(0, price - K) if r_type == "c" else max(0, K - price)
                    )

                sim_value += leg_price * pos * leg_multiplier

            except Exception:
                intrinsic_value = (
                    max(0, price - K) if r_type == "c" else max(0, K - price)
                )
                sim_value += intrinsic_value * pos * leg_multiplier

        pnl_curve.append(round(sim_value - total_cost_basis, 2))
    return pnl_curve


def calculate_expiration_pnl(legs_with_details, price_range):
    total_cost_basis = sum(leg.get("costBasis", 0) or 0 for leg in legs_with_details)

    def get_contract(leg):
        return leg.get("tws_data", {}).get("contract", leg)

    option_legs = [
        leg
        for leg in legs_with_details
        if get_contract(leg).get("secType", "OPT") == "OPT"
    ]

    if not option_legs:
        stock_leg = next(
            (
                leg
                for leg in legs_with_details
                if get_contract(leg).get("secType", "OPT") != "OPT"
            ),
            None,
        )
        if stock_leg:
            contract = get_contract(stock_leg)
            leg_multiplier = get_contract_multiplier(contract, default=1.0)
            pnl = [
                round((price * stock_leg["qty"] * leg_multiplier) - total_cost_basis, 2)
                for price in price_range
            ]
            return pnl
        return [round(-total_cost_basis, 2)] * len(price_range)

    earliest_expiry_str = min(get_contract(leg)["expiry"] for leg in option_legs)
    earliest_expiry_date = datetime.strptime(earliest_expiry_str, "%Y%m%d")

    pnl_curve = []
    for price in price_range:
        value_at_earliest_expiry = 0.0
        for leg in legs_with_details:
            tws_leg_data = leg.get("tws_data")
            if tws_leg_data:
                pos = leg["qty"]
                contract = tws_leg_data["contract"]
                greeks = tws_leg_data["greeks"]
                leg_multiplier = get_contract_multiplier(contract)
            else:
                pos = leg["qty"]
                contract = leg
                greeks = leg
                leg_multiplier = get_contract_multiplier(contract)

            if contract.get("secType", "OPT") != "OPT":
                value_at_earliest_expiry += price * pos * leg_multiplier
                continue

            K = contract["strike"]
            r_type = contract["right"].lower()
            leg_expiry_date = datetime.strptime(contract["expiry"], "%Y%m%d")

            if leg_expiry_date <= earliest_expiry_date:
                intrinsic_value = (
                    max(0, price - K) if r_type == "c" else max(0, K - price)
                )
                value_at_earliest_expiry += intrinsic_value * pos * leg_multiplier
            else:
                initial_iv = greeks.get("iv", 0)
                T_remaining = max(
                    1e-9, (leg_expiry_date - earliest_expiry_date).days / 365.25
                )

                try:
                    sim_iv = initial_iv if initial_iv and initial_iv > 0 else 0.0001
                    if T_remaining > 1e-9 and sim_iv > 1e-9:
                        back_leg_price = bs_price(
                            r_type, price, K, T_remaining, RISK_FREE_RATE, sim_iv
                        )
                        back_leg_price = max(0, back_leg_price)
                    else:
                        back_leg_price = (
                            max(0, price - K) if r_type == "c" else max(0, K - price)
                        )

                    value_at_earliest_expiry += back_leg_price * pos * leg_multiplier

                except Exception:
                    intrinsic_value = (
                        max(0, price - K) if r_type == "c" else max(0, K - price)
                    )
                    value_at_earliest_expiry += intrinsic_value * pos * leg_multiplier

        pnl_curve.append(round(value_at_earliest_expiry - total_cost_basis, 2))
    return pnl_curve


def find_breakevens(prices, pnls):
    p, v, b = np.array(prices), np.array(pnls), []
    if np.all(np.sign(v) >= 0) or np.all(np.sign(v) <= 0):
        return []

    idx = np.where(np.diff(np.sign(v)))[0]
    for i in idx:
        if i < len(p) - 1 and i < len(v) - 1:
            p1, p2, v1, v2 = p[i], p[i + 1], v[i], v[i + 1]
            if (v2 - v1) != 0:
                try:
                    breakeven = p1 - v1 * (p2 - p1) / (v2 - v1)
                    if math.isfinite(breakeven):
                        b.append(round(float(breakeven), 2))
                except Exception:
                    pass
    return sorted(list(set(b)))


def calculate_greek_surface(
    legs_with_details, price_range, time_range_days, greek_name, iv_shift=0.0
):
    surface, today = [], datetime.now()
    greek_func = {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}.get(
        greek_name
    )
    if not greek_func:
        return []

    for days_to_add in time_range_days:
        row = []
        for price in price_range:
            total_greek = 0.0
            for leg in legs_with_details:
                tws_leg_data = leg.get("tws_data")
                if tws_leg_data:
                    pos = leg["qty"]
                    contract = tws_leg_data["contract"]
                    greeks = tws_leg_data["greeks"]
                    leg_multiplier = get_contract_multiplier(contract)
                else:
                    pos = leg["qty"]
                    contract = leg
                    greeks = leg
                    leg_multiplier = get_contract_multiplier(contract)

                if contract.get("secType", "OPT") != "OPT":
                    continue

                K, initial_iv, r_type = (
                    contract["strike"],
                    greeks.get("iv", 0),
                    contract["right"].lower(),
                )
                sim_iv = (
                    initial_iv * (1 + iv_shift)
                    if initial_iv and initial_iv > 0
                    else 0.0001
                )
                expiry_dt = datetime.strptime(contract["expiry"], "%Y%m%d")
                T_sim = max(
                    1e-9,
                    (expiry_dt - (today + timedelta(days=days_to_add))).days / 365.25,
                )

                try:
                    if T_sim > 1e-9 and sim_iv > 1e-9:
                        greek_val = greek_func(
                            r_type, price, K, T_sim, RISK_FREE_RATE, sim_iv
                        )
                        if math.isfinite(greek_val):
                            total_greek += greek_val * pos * leg_multiplier

                except Exception:
                    pass

            row.append(round(total_greek, 4))
        surface.append(row)
    return surface


def calculate_greeks_at_point(legs_with_details, price, days_to_add=0, iv_shift=0.0):
    totals = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    target_date = datetime.now() + timedelta(days=days_to_add)
    greek_funcs = {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}

    for leg in legs_with_details:
        tws_leg_data = leg.get("tws_data")
        if tws_leg_data:
            pos = leg["qty"]
            contract = tws_leg_data["contract"]
            greeks = tws_leg_data["greeks"]
            leg_multiplier = get_contract_multiplier(contract)
        else:
            pos = leg["qty"]
            contract = leg
            greeks = leg
            leg_multiplier = get_contract_multiplier(contract)

        if contract.get("secType", "OPT") != "OPT":
            continue

        K = contract["strike"]
        r_type = contract["right"].lower()
        initial_iv = greeks.get("iv", 0)
        sim_iv = (
            initial_iv * (1 + iv_shift) if initial_iv and initial_iv > 0 else 0.0001
        )
        expiry_dt = datetime.strptime(contract["expiry"], "%Y%m%d")
        T_sim = max(1e-9, (expiry_dt - target_date).days / 365.25)

        if not (T_sim > 1e-9 and sim_iv > 1e-9):
            continue

        for name, func in greek_funcs.items():
            try:
                greek_val = func(r_type, price, K, T_sim, RISK_FREE_RATE, sim_iv)
                if math.isfinite(greek_val):
                    totals[name] += greek_val * pos * leg_multiplier
            except Exception:
                continue

    return {name: round(value, 4) for name, value in totals.items()}


def calculate_position_value_curve(
    legs_with_details, price_range, days_to_add=0, iv_shift=0.0, absolute_qty=False
):
    today = datetime.now()
    sim_date = today + timedelta(days=days_to_add)
    value_curve = []

    for price in price_range:
        sim_value = 0.0
        for leg in legs_with_details:
            tws_leg_data = leg.get("tws_data")
            if tws_leg_data:
                pos = safe_float(leg.get("qty"), 0.0)
                contract = tws_leg_data.get("contract", {})
                greeks = tws_leg_data.get("greeks", {})
                leg_multiplier = get_contract_multiplier(contract)
            else:
                pos = safe_float(leg.get("qty"), 0.0)
                contract = leg
                greeks = leg
                leg_multiplier = get_contract_multiplier(contract)

            if absolute_qty:
                pos = abs(pos)

            if contract.get("secType", "OPT") != "OPT":
                sim_value += price * pos * leg_multiplier
                continue

            K = safe_float(contract.get("strike"), 0.0)
            r_type = str(contract.get("right", "")).lower()
            initial_iv = safe_float(greeks.get("iv"), 0.0)
            sim_iv = initial_iv * (1 + iv_shift) if initial_iv > 0 else 0.0001
            expiry_raw = contract.get("expiry")
            if not expiry_raw:
                continue

            try:
                expiry_dt = datetime.strptime(expiry_raw, "%Y%m%d")
            except Exception:
                continue

            T_sim = max(1e-9, (expiry_dt - sim_date).days / 365.25)
            try:
                if T_sim > 1e-9 and sim_iv > 1e-9 and r_type in ("c", "p"):
                    leg_price = bs_price(
                        r_type, price, K, T_sim, RISK_FREE_RATE, sim_iv
                    )
                    leg_price = max(0, leg_price)
                else:
                    leg_price = (
                        max(0, price - K) if r_type == "c" else max(0, K - price)
                    )
                sim_value += leg_price * pos * leg_multiplier
            except Exception:
                intrinsic_value = (
                    max(0, price - K) if r_type == "c" else max(0, K - price)
                )
                sim_value += intrinsic_value * pos * leg_multiplier

        value_curve.append(round(sim_value, 2))

    return value_curve
