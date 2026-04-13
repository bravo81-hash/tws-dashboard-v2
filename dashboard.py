# ========================================================================================
# --- TWS DASHBOARD BACKEND ---
# DEFINITIVE, COMPLETE, AND FINAL VERSION (ALL FEATURES + ALL FIXES)
# ========================================================================================
import sys
import json
from ibapi.contract import ComboLeg
import threading
import time
import queue
import math
import os
import traceback
from flask import Flask, jsonify, request
from flask_cors import CORS
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
import numpy as np

from runtime import (
    apply_runtime_compat_env,
    get_runtime_diagnostics,
    log_startup_diagnostics,
)

apply_runtime_compat_env()
from py_vollib.black_scholes.greeks.analytical import delta, gamma, vega, theta
from py_vollib.black_scholes.implied_volatility import implied_volatility as bs_iv
from datetime import datetime, timedelta
from typing import Optional

from combo_schema import normalize_combos_payload
from client_portal_adapter import ClientPortalAdapter
from routes import register_core_routes
from valuation import (
    RISK_FREE_RATE,
    calculate_expiration_pnl,
    calculate_greeks_at_point,
    calculate_greek_surface,
    calculate_pnl_curve,
    calculate_position_value_curve,
    derive_cost_basis_for_qty,
    find_breakevens,
    get_contract_multiplier,
    safe_float,
)

# ========================================================================================
# --- CONFIGURATION ---
# ========================================================================================
IGNORE_LIST = ["MESZ5", "DAL   251017C00070000"]
TWS_PORT = 7496
SERVER_PORT = 5001
REFRESH_INTERVAL = 120
FALLBACK_TIMEOUT_SEC = 6
OPTION_EOD_SOURCE = "MIDPOINT"
UNDERLYING_EOD_SOURCE = "TRADES"
CLIENT_ID = 100
OPTION_CHAIN_CONTRACT_CACHE_TTL_SEC = 120

# ========================================================================================
# --- GLOBAL STATE & APP INITIALIZATION ---
# ========================================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMBOS_FILE = os.path.join(BASE_DIR, "combos.json")

app = Flask(__name__, static_url_path="", static_folder=BASE_DIR)
CORS(app)

ib_app: Optional["IBKRApp"] = None

# Portfolio State
portfolio_data = {}
portfolio_lock = threading.Lock()
request_queue = queue.Queue()
underlying_prices = {}
underlying_mkt_reqs = {}
client_portal_adapter = ClientPortalAdapter.from_env()

# Temporary Option Chain State
chain_data_cache = {}
chain_lock = threading.Lock()
chain_underlying_price = None
option_chain_contract_cache = {}
option_chain_contract_cache_lock = threading.Lock()

# Account Risk Context State (TWS account summary stream)
account_summary_data = {}
account_summary_lock = threading.Lock()
account_summary_last_updated_ts = 0.0


def status_is_live_or_snapshot(tws_data):
    status = str((tws_data or {}).get("status", ""))
    return status.startswith("Live") or status == "Snapshot"


def build_legs_with_details(profile_legs, require_live=True):
    legs_with_details = []
    if not isinstance(profile_legs, list):
        return legs_with_details

    with portfolio_lock:
        for leg_req in profile_legs:
            if not isinstance(leg_req, dict):
                continue
            raw_con_id = leg_req.get("conId")
            con_id = None
            if isinstance(raw_con_id, int):
                con_id = raw_con_id
            elif isinstance(raw_con_id, float) and raw_con_id.is_integer():
                con_id = int(raw_con_id)
            else:
                parsed_con_id = safe_float(raw_con_id, None)
                if (
                    parsed_con_id is not None
                    and math.isfinite(parsed_con_id)
                    and float(parsed_con_id).is_integer()
                ):
                    con_id = int(parsed_con_id)
            qty = safe_float(leg_req.get("qty"), None)
            if qty is None:
                continue
            tws_data = portfolio_data.get(con_id) if con_id is not None else None

            sec_type = str(leg_req.get("secType", "OPT")).upper().strip() or "OPT"
            strike = safe_float(leg_req.get("strike"), None)
            right = str(leg_req.get("right", "")).upper().strip()
            expiry = str(leg_req.get("expiry", "")).strip()
            multiplier = safe_float(leg_req.get("multiplier"), 100.0)
            iv = safe_float(leg_req.get("iv"), 0.0)
            und_price = safe_float(leg_req.get("undPrice"), None)

            synthetic_leg = None
            if (
                sec_type == "OPT"
                and strike is not None
                and math.isfinite(strike)
                and strike > 0
                and right in ("C", "P")
                and len(expiry) == 8
                and expiry.isdigit()
            ):
                synthetic_leg = {
                    "conId": con_id,
                    "qty": qty,
                    "costBasis": safe_float(leg_req.get("costBasis"), 0.0),
                    "secType": "OPT",
                    "symbol": str(leg_req.get("symbol", "")).strip(),
                    "right": right,
                    "strike": float(strike),
                    "expiry": expiry,
                    "iv": max(iv, 0.0),
                    "multiplier": max(multiplier, 1.0),
                    "undPrice": und_price if und_price and und_price > 0 else None,
                }

            if tws_data:
                contract = (
                    tws_data.get("contract", {}) if isinstance(tws_data, dict) else {}
                )
                sec_type_live = str(contract.get("secType", "")).upper().strip()
                strike_live = safe_float(contract.get("strike"), None)
                right_live = str(contract.get("right", "")).upper().strip()
                expiry_live = str(contract.get("expiry", "")).strip()
                live_is_option_ready = sec_type_live != "OPT" or (
                    strike_live is not None
                    and math.isfinite(strike_live)
                    and strike_live > 0
                    and right_live in ("C", "P")
                    and len(expiry_live) == 8
                    and expiry_live.isdigit()
                )
                is_live_ready = (
                    not require_live or status_is_live_or_snapshot(tws_data)
                ) and live_is_option_ready
                if is_live_ready:
                    legs_with_details.append(
                        {
                            "conId": con_id,
                            "qty": qty,
                            "costBasis": derive_cost_basis_for_qty(
                                tws_data, qty, leg_req.get("costBasis")
                            ),
                            "tws_data": tws_data,
                        }
                    )
                    continue

                if synthetic_leg:
                    legs_with_details.append(synthetic_leg)
                continue

            if synthetic_leg:
                legs_with_details.append(synthetic_leg)
    return legs_with_details


def resolve_underlying_price(legs_with_details):
    for leg in legs_with_details:
        tws_data = leg.get("tws_data")
        if not tws_data:
            continue
        und_price = safe_float(tws_data.get("greeks", {}).get("undPrice"), None)
        if und_price is not None and und_price > 0:
            return und_price

    for leg in legs_with_details:
        und_price = safe_float(leg.get("undPrice"), None)
        if und_price is not None and und_price > 0:
            return und_price

    if not legs_with_details:
        return None

    first = legs_with_details[0]
    symbol = (
        first.get("tws_data", {}).get("contract", {}).get("symbol")
        or first.get("symbol")
    )
    cached = underlying_prices.get(symbol)
    if isinstance(cached, dict):
        bid = safe_float(cached.get("bid"), None)
        ask = safe_float(cached.get("ask"), None)
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return None

    cached_price = safe_float(cached, None)
    if cached_price is not None and cached_price > 0:
        return cached_price
    return None


def finite_positive_or_none(value):
    parsed = safe_float(value, None)
    if parsed is None or not math.isfinite(parsed) or parsed <= 0:
        return None
    return float(parsed)


def update_quote_bucket_from_tick(bucket, tick_type, price):
    if not isinstance(bucket, dict):
        return
    if price is None or price <= -1:
        return
    if tick_type == 1:
        bucket["bid"] = price
    elif tick_type == 2:
        bucket["ask"] = price
    elif tick_type in [4, 68]:
        bucket["last"] = price
    elif tick_type == 9:
        bucket["close"] = price
    elif tick_type == 66:
        bucket["delayed_last"] = price


def merge_chain_snapshot_into_leg(leg_data, snapshot_data):
    if not isinstance(leg_data, dict) or not isinstance(snapshot_data, dict):
        return

    price_fields = ["bid", "ask", "last", "close", "delayed_last", "modelPrice"]
    for field in price_fields:
        current_val = finite_positive_or_none(leg_data.get(field))
        if current_val is not None:
            continue
        incoming = finite_positive_or_none(snapshot_data.get(field))
        if incoming is not None:
            leg_data[field] = incoming

    if leg_data.get("iv") is None:
        iv = safe_float(snapshot_data.get("iv"), None)
        if iv is not None and iv > -1:
            leg_data["iv"] = iv

    if leg_data.get("delta") is None:
        delta_val = safe_float(snapshot_data.get("delta"), None)
        if delta_val is not None and abs(delta_val) <= 1:
            leg_data["delta"] = delta_val


def resolve_chain_mark_and_quality(*, bid=None, ask=None, last=None, model=None, close=None):
    bid_v = finite_positive_or_none(bid)
    ask_v = finite_positive_or_none(ask)
    if bid_v is not None and ask_v is not None:
        return round(float((bid_v + ask_v) / 2.0), 4), "live", "live"

    last_v = finite_positive_or_none(last)
    if last_v is not None:
        return round(float(last_v), 4), "live", "live"

    model_v = finite_positive_or_none(model)
    if model_v is not None:
        return round(float(model_v), 4), "model", "fallback"

    close_v = finite_positive_or_none(close)
    if close_v is not None:
        return round(float(close_v), 4), "close", "fallback"

    return None, "none", "missing"


def select_chain_contracts_for_stream(
    contracts_details, spot_price=None, strike_half_width=10
):
    if not isinstance(contracts_details, list) or not contracts_details:
        return []

    deduped = {}
    strikes = set()

    for detail in contracts_details:
        contract = getattr(detail, "contract", None)
        if contract is None:
            continue
        con_id = getattr(contract, "conId", None)
        right = str(getattr(contract, "right", "")).strip().upper()[:1]
        strike = safe_float(getattr(contract, "strike", None), None)
        if (
            not isinstance(con_id, int)
            or right not in {"C", "P"}
            or strike is None
            or not math.isfinite(strike)
            or strike <= 0
        ):
            continue
        strike_key = round(float(strike), 6)
        key = (strike_key, right)
        if key not in deduped:
            deduped[key] = detail
            strikes.add(strike_key)

    ordered_strikes = sorted(strikes)
    if not ordered_strikes:
        return []

    half = max(1, int(safe_float(strike_half_width, 10)))
    window = (half * 2) + 1
    if len(ordered_strikes) <= window:
        selected_strikes = ordered_strikes
    else:
        spot = finite_positive_or_none(spot_price)
        if spot is not None:
            nearest_idx = min(
                range(len(ordered_strikes)),
                key=lambda idx: abs(float(ordered_strikes[idx]) - float(spot)),
            )
        else:
            nearest_idx = len(ordered_strikes) // 2
        start = max(0, nearest_idx - half)
        end = min(len(ordered_strikes), nearest_idx + half + 1)
        if start == 0:
            end = min(len(ordered_strikes), window)
        elif end == len(ordered_strikes):
            start = max(0, len(ordered_strikes) - window)
        selected_strikes = ordered_strikes[start:end]

    selected = []
    for strike in selected_strikes:
        strike_key = round(float(strike), 6)
        for right in ("C", "P"):
            detail = deduped.get((strike_key, right))
            if detail is not None:
                selected.append(detail)
    return selected


def get_cached_option_chain_contracts(symbol, expiry, now_ts=None):
    if not symbol or not expiry:
        return None
    now_val = float(now_ts) if now_ts is not None else time.time()
    key = (str(symbol).upper(), str(expiry))
    with option_chain_contract_cache_lock:
        entry = option_chain_contract_cache.get(key)
        if not entry:
            return None
        cached_at = safe_float(entry.get("cached_at"), None)
        if cached_at is None:
            option_chain_contract_cache.pop(key, None)
            return None
        age = now_val - cached_at
        if age < 0 or age > OPTION_CHAIN_CONTRACT_CACHE_TTL_SEC:
            option_chain_contract_cache.pop(key, None)
            return None
        contracts = entry.get("contracts")
        if not isinstance(contracts, list) or not contracts:
            return None
        return list(contracts)


def set_cached_option_chain_contracts(symbol, expiry, contracts_details, now_ts=None):
    if not symbol or not expiry or not isinstance(contracts_details, list):
        return
    if not contracts_details:
        return
    now_val = float(now_ts) if now_ts is not None else time.time()
    key = (str(symbol).upper(), str(expiry))
    with option_chain_contract_cache_lock:
        option_chain_contract_cache[key] = {
            "cached_at": now_val,
            "contracts": list(contracts_details),
        }


def build_expiry_lookup_contract(symbol):
    normalized = str(symbol or "").strip().upper()
    contract = Contract()
    contract.symbol = normalized
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"

    index_exchange_map = {
        "SPX": "CBOE",
        "SPXW": "CBOE",
        "VIX": "CBOE",
        "RUT": "RUSSELL",
        "NDX": "NASDAQ",
        "XSP": "CBOE",
    }
    if normalized in index_exchange_map:
        contract.secType = "IND"
        contract.exchange = index_exchange_map[normalized]
    return contract


def allocate_request_id(ib_client):
    if ib_client is None:
        raise ValueError("IB client is required")
    allocator = getattr(ib_client, "allocate_req_id", None)
    if callable(allocator):
        return int(allocator())
    req_id = int(getattr(ib_client, "next_req_id"))
    ib_client.next_req_id = req_id + 1
    return req_id


def maybe_qualify_underlying_conid(ib_client, contract, timeout_sec=10):
    if not ib_client or not contract:
        return None

    req_id = allocate_request_id(ib_client)
    event = threading.Event()
    ib_client.req_map[req_id] = {
        "event": event,
        "contract": None,
        "req_type": "underlying_qualification",
    }

    try:
        print(
            f"--> Qualifying underlying contract for expiries {contract.symbol} (req_id={req_id})"
        )
        api_gate.wait()
        ib_client.reqContractDetails(req_id, contract)
        if not event.wait(timeout=timeout_sec):
            print(
                f"⚠️ Underlying qualification timeout for {contract.symbol} (req_id={req_id})"
            )
            return None

        qualified = ib_client.req_map.get(req_id, {}).get("contract")
        con_id = int(safe_float(getattr(qualified, "conId", 0), 0))
        if con_id > 0:
            return con_id
        return None
    finally:
        ib_client.req_map.pop(req_id, None)


def compute_days_to_expiry(legs_with_details):
    option_legs = []
    for leg in legs_with_details:
        contract = (
            leg.get("tws_data", {}).get("contract") if leg.get("tws_data") else leg
        )
        if (contract or {}).get("secType", "OPT") == "OPT":
            option_legs.append(leg)
    if not option_legs:
        return 0

    try:
        earliest_expiry_str = min(
            (
                l["tws_data"]["contract"]["expiry"]
                if l.get("tws_data")
                else l.get("expiry")
            )
            for l in option_legs
            if (
                l.get("tws_data", {}).get("contract", {}).get("expiry")
                if l.get("tws_data")
                else l.get("expiry")
            )
        )
        if not earliest_expiry_str:
            return 0
        earliest_expiry_date = datetime.strptime(earliest_expiry_str, "%Y%m%d")
        return max(0, (earliest_expiry_date.date() - datetime.now().date()).days)
    except Exception:
        return 0


def normalize_time_steps(dte, requested_steps=None, default_columns=6):
    if isinstance(requested_steps, list) and requested_steps:
        source_steps = requested_steps
    elif dte > 0:
        columns = int(safe_float(default_columns, 6))
        columns = max(2, min(columns, 40))
        source_steps = [
            int(round((idx / (columns - 1)) * dte)) for idx in range(columns)
        ]
    else:
        source_steps = [0]

    steps = []
    seen = set()
    for raw_step in source_steps:
        step = int(safe_float(raw_step, 0))
        if step < 0:
            continue
        if dte > 0:
            step = min(step, dte)
        if step in seen:
            continue
        seen.add(step)
        steps.append(step)

    if not steps:
        return [0]
    return sorted(steps)


def build_price_axis_from_spot(spot, steps_each_side=10, step_pct=0.5):
    spot = safe_float(spot, 0.0)
    if spot <= 0:
        return [0.0]

    steps_each_side = int(safe_float(steps_each_side, 10))
    steps_each_side = max(2, min(steps_each_side, 60))
    step_pct = safe_float(step_pct, 0.5)
    step_pct = min(max(step_pct, 0.1), 20.0)

    prices = []
    for idx in range(-steps_each_side, steps_each_side + 1):
        pct = (idx * step_pct) / 100.0
        price = max(0.01, spot * (1.0 + pct))
        prices.append(round(float(price), 2))
    return prices


def build_builder_price_axis(spot, builder_legs, lower_pct=0.8, upper_pct=1.2):
    spot = safe_float(spot, 0.0)
    if spot <= 0:
        return [0.0]

    lo = max(0.01, spot * lower_pct)
    hi = max(lo + 0.01, spot * upper_pct)

    strikes = []
    for raw_leg in builder_legs or []:
        strike = safe_float((raw_leg or {}).get("strike"), None)
        if strike is None or not math.isfinite(strike) or strike <= 0:
            continue
        strikes.append(float(strike))
    strikes = sorted(set(strikes))

    min_gap = None
    if len(strikes) >= 2:
        gaps = [
            b - a for a, b in zip(strikes, strikes[1:]) if (b - a) > 1e-9
        ]
        if gaps:
            min_gap = min(gaps)

    if min_gap is not None:
        # Keep enough resolution to preserve narrow spread break-evens.
        target_step = max(0.5, min_gap / 2.0)
        points = int(math.ceil((hi - lo) / target_step)) + 1
    else:
        points = 900

    points = max(900, min(points, 2400))
    base_axis = np.linspace(lo, hi, points)
    anchors = np.array([spot] + strikes, dtype=float) if strikes else np.array([spot])
    merged = np.concatenate((base_axis, anchors))

    return sorted(
        {
            round(float(px), 2)
            for px in merged
            if math.isfinite(float(px)) and float(px) > 0
        }
    )


def estimate_net_liq_from_legs(legs_with_details):
    estimate = 0.0
    for leg in legs_with_details:
        tws_data = leg.get("tws_data", {})
        position = safe_float(tws_data.get("position"), 0.0)
        market_value = safe_float(tws_data.get("marketValue"), 0.0)
        qty = safe_float(leg.get("qty"), 0.0)
        ratio = abs(qty / position) if abs(position) > 1e-9 else 0.0
        estimate += abs(market_value * ratio)

    if estimate <= 1e-9:
        estimate = sum(
            abs(safe_float(leg.get("costBasis"), 0.0)) for leg in legs_with_details
        )

    return max(estimate, 1.0)


def get_portfolio_accounts():
    with portfolio_lock:
        accounts = sorted(
            {
                str(leg.get("account", "")).strip()
                for leg in portfolio_data.values()
                if str(leg.get("account", "")).strip()
            }
        )
    return accounts


def estimate_net_liq_for_account(account):
    market_value_abs = 0.0
    cost_basis_abs = 0.0
    with portfolio_lock:
        for leg in portfolio_data.values():
            leg_account = str(leg.get("account", "")).strip()
            if account != "All" and leg_account != account:
                continue
            market_value_abs += abs(safe_float(leg.get("marketValue"), 0.0))
            cost_basis_abs += abs(safe_float(leg.get("costBasis"), 0.0))
    return max(market_value_abs, cost_basis_abs, 1.0)


def estimate_sgpv_for_account(account):
    sgpv = 0.0
    with portfolio_lock:
        for leg in portfolio_data.values():
            leg_account = str(leg.get("account", "")).strip()
            if account != "All" and leg_account != account:
                continue
            sgpv += abs(safe_float(leg.get("marketValue"), 0.0))
    return max(sgpv, 0.0)


def build_expiry_alerts(max_days=7, max_rows=12):
    alerts = []
    today = datetime.now().date()
    with portfolio_lock:
        for leg in portfolio_data.values():
            contract = leg.get("contract", {})
            if contract.get("secType") != "OPT":
                continue
            expiry_str = str(contract.get("expiry", "")).strip()
            if len(expiry_str) != 8 or not expiry_str.isdigit():
                continue
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y%m%d").date()
            except Exception:
                continue
            dte = (expiry_date - today).days
            if dte < 0 or dte > max_days:
                continue
            alerts.append(
                {
                    "conId": leg.get("conId"),
                    "account": str(leg.get("account", "")).strip(),
                    "description": leg.get("description"),
                    "symbol": contract.get("symbol"),
                    "expiry": expiry_str,
                    "dte": int(dte),
                    "position": safe_float(leg.get("position"), 0.0),
                }
            )

    alerts.sort(
        key=lambda row: (
            row.get("dte", 9999),
            row.get("symbol", ""),
            row.get("description", ""),
        )
    )
    return alerts[:max_rows]


def _parse_summary_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_summary_metric(summary_by_tag, candidate_tags):
    if not isinstance(summary_by_tag, dict):
        return None
    for tag in candidate_tags:
        entry = summary_by_tag.get(tag)
        if isinstance(entry, dict):
            parsed = _parse_summary_value(entry.get("value"))
        else:
            parsed = _parse_summary_value(entry)
        if parsed is not None:
            return parsed
    return None


def get_tws_summary_accounts():
    with account_summary_lock:
        return sorted(
            [account for account in account_summary_data.keys() if str(account).strip()]
        )


def get_tws_account_risk_context(selected_account):
    global account_summary_last_updated_ts

    with account_summary_lock:
        snapshot = {
            account: dict(values) for account, values in account_summary_data.items()
        }
        updated_ts = account_summary_last_updated_ts

    if not snapshot:
        return {
            "available": False,
            "net_liq": None,
            "maintenance_margin": None,
            "sgpv": None,
            "accounts": [],
            "selected_account": selected_account,
            "age_sec": None,
        }

    netliq_tags = ["NetLiquidation", "NetLiquidation-S", "NetLiq"]
    maint_tags = ["MaintMarginReq", "LookAheadMaintMarginReq", "MaintMarginReq-C"]
    sgpv_tags = [
        "GrossPositionValue",
        "GrossPositionValue-S",
        "SecuritiesGrossPositionValue",
        "SecuritiesGrossPositionValue-S",
    ]

    account_keys = sorted(snapshot.keys())
    if selected_account != "All":
        account_values = snapshot.get(selected_account)
        if not account_values:
            return {
                "available": False,
                "net_liq": None,
                "maintenance_margin": None,
                "sgpv": None,
                "accounts": account_keys,
                "selected_account": selected_account,
                "age_sec": round(max(0.0, time.time() - updated_ts), 2)
                if updated_ts
                else None,
            }
        net_liq = _pick_summary_metric(account_values, netliq_tags)
        maintenance = _pick_summary_metric(account_values, maint_tags)
        sgpv = _pick_summary_metric(account_values, sgpv_tags)
    else:
        net_liq = 0.0
        maintenance = 0.0
        sgpv = 0.0
        has_net = False
        has_maint = False
        has_sgpv = False
        for _, account_values in snapshot.items():
            account_net = _pick_summary_metric(account_values, netliq_tags)
            account_maint = _pick_summary_metric(account_values, maint_tags)
            account_sgpv = _pick_summary_metric(account_values, sgpv_tags)
            if account_net is not None:
                net_liq += account_net
                has_net = True
            if account_maint is not None:
                maintenance += account_maint
                has_maint = True
            if account_sgpv is not None:
                sgpv += account_sgpv
                has_sgpv = True
        if not has_net:
            net_liq = None
        if not has_maint:
            maintenance = None
        if not has_sgpv:
            sgpv = None

    return {
        "available": net_liq is not None or maintenance is not None or sgpv is not None,
        "net_liq": net_liq,
        "maintenance_margin": maintenance,
        "sgpv": sgpv,
        "accounts": account_keys,
        "selected_account": selected_account,
        "age_sec": round(max(0.0, time.time() - updated_ts), 2) if updated_ts else None,
    }


def compute_breach_ranges(price_axis, values, min_value, max_value=None):
    if not price_axis or not values:
        return []

    ranges = []
    active_start = None
    for idx, value in enumerate(values):
        val = safe_float(value, 0.0)
        in_range = val >= min_value and (max_value is None or val < max_value)
        if in_range and active_start is None:
            active_start = idx
        if not in_range and active_start is not None:
            ranges.append(
                [
                    round(float(price_axis[active_start]), 2),
                    round(float(price_axis[idx - 1]), 2),
                ]
            )
            active_start = None

    if active_start is not None:
        ranges.append(
            [
                round(float(price_axis[active_start]), 2),
                round(float(price_axis[-1]), 2),
            ]
        )

    return ranges


class RequestGate:
    def __init__(self, requests_per_second=45):
        self.requests_per_second = requests_per_second
        self.interval = 1.0 / requests_per_second
        self.last_request_time = 0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_request_time = time.time()


api_gate = RequestGate()


class IBKRApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.next_req_id = 1
        self._req_id_lock = threading.Lock()
        self.next_order_id = 1
        self.account_summary_req_id = None
        self.req_map = {}
        self.active_chain_reqs = set()
        self.fallback_deadline = {}
        self._positions_being_updated = set()
        self.tick_data = {}
        self.hist_req_map = {}
        self.eod_fallback_inflight = set()

    def allocate_req_id(self):
        with self._req_id_lock:
            req_id = int(self.next_req_id)
            self.next_req_id += 1
        return req_id

    def nextValidId(self, orderId: int):
        with self._req_id_lock:
            self.next_req_id = int(orderId)
        self.next_order_id = orderId
        print("✅ TWS API Connected. Requesting initial positions list...")
        self.reqPositions()
        self.request_account_summary_stream()

    def connectionClosed(self):
        super().connectionClosed()
        self.account_summary_req_id = None

    def request_account_summary_stream(self):
        if not self.isConnected():
            return
        if self.account_summary_req_id is not None:
            return
        req_id = self.allocate_req_id()
        self.account_summary_req_id = req_id
        tags = ",".join(
            [
                "NetLiquidation",
                "GrossPositionValue",
                "MaintMarginReq",
                "LookAheadMaintMarginReq",
                "ExcessLiquidity",
                "AvailableFunds",
                "InitMarginReq",
                "BuyingPower",
            ]
        )
        try:
            api_gate.wait()
            self.reqAccountSummary(req_id, "All", tags)
            print(f"--> Subscribed account summary stream (ReqId: {req_id})")
        except Exception as exc:
            print(f"⚠️ Could not request account summary stream: {exc}")

    def accountSummary(self, reqId, account, tag, value, currency):
        global account_summary_last_updated_ts

        if (
            self.account_summary_req_id is not None
            and reqId != self.account_summary_req_id
        ):
            return
        if not account or not tag:
            return

        with account_summary_lock:
            account_bucket = account_summary_data.setdefault(account, {})
            account_bucket[tag] = {
                "value": value,
                "currency": currency,
                "updated_at": time.time(),
            }
            account_summary_last_updated_ts = time.time()

    def accountSummaryEnd(self, reqId):
        if (
            self.account_summary_req_id is not None
            and reqId != self.account_summary_req_id
        ):
            return
        print(f"--> Account summary stream snapshot received (ReqId: {reqId})")

    def error(self, reqId, errorCode, errorString):
        if errorCode in [
            2104,
            2106,
            2108,
            2158,
            2103,
            2105,
            2157,
            162,
            321,
            354,
            200,
            2107,
        ]:
            return
        if errorCode == 300 and "Can't find EId with tickerId" in errorString:
            return
        if errorCode == 354:
            print(
                f"⚠️ TWS Warning (reqId {reqId}): Market data request failed. Possible subscription issue. Msg: {errorString}"
            )
            return
        if (
            reqId in self.req_map
            and isinstance(self.req_map.get(reqId), dict)
            and "event" in self.req_map[reqId]
        ):
            if errorCode == 200:
                print(
                    f"⚠️ Warning (reqId {reqId}): No security definition found. Unblocking."
                )
                self.req_map[reqId]["event"].set()
        print(f"TWS Error (reqId {reqId}): {errorCode} - {errorString}")

    def orderStatus(
        self,
        orderId,
        status,
        filled,
        remaining,
        avgFillPrice,
        permId,
        parentId,
        lastFillPrice,
        clientId,
        whyHeld,
        mktCapPrice,
    ):
        print(
            f"📊 Order {orderId}: status={status}, filled={filled}/{filled + remaining}"
        )
        if status == "Submitted":
            print(f"✅ Order {orderId} has been received and accepted by TWS.")
        elif status == "Filled":
            print(f"🎉 Order {orderId} has been completely filled.")
        # <-- Added logging for Inactive status -->
        elif status == "Inactive":
            print(
                f"ℹ️ Order {orderId} is now Inactive (likely needs manual transmission in TWS)."
            )

    def openOrder(self, orderId, contract, order, orderState):
        print(
            f"📖 Open Order {orderId}: {order.action} {order.totalQuantity} {contract.symbol} @ {order.lmtPrice if order.orderType == 'LMT' else 'MKT'}"
        )
        if orderState.status not in ["Submitted", "PreSubmitted", "Filled"]:
            print(f"   - Status: {orderState.status}")
        if orderState.warningText:
            print(f"   - ⚠️ Warning: {orderState.warningText}")

    def execDetails(self, reqId, contract, execution):
        print(
            f"✅ Execution {execution.execId}: {execution.side} {execution.shares} shares of {contract.symbol} @ ${execution.price}"
        )

    def position(
        self, account: str, contract: Contract, position: float, avgCost: float
    ):
        desc = self.get_contract_description(contract)
        if contract.localSymbol.strip() in IGNORE_LIST or desc in IGNORE_LIST:
            return
        with portfolio_lock:
            conId = contract.conId
            self._positions_being_updated.add(conId)
            cost_basis = position * avgCost
            if conId not in portfolio_data:
                portfolio_data[conId] = {
                    "conId": conId,
                    "description": desc,
                    "position": position,
                    "account": account,
                    "avgCost": avgCost,
                    "costBasis": cost_basis,
                    "marketValue": cost_basis,
                    "bid": None,
                    "ask": None,
                    "pnl": {"daily": 0.0, "unrealized": 0.0},
                    "greeks": {
                        "delta": None,
                        "gamma": None,
                        "vega": None,
                        "theta": None,
                        "iv": None,
                        "undPrice": None,
                    },
                    "contract": {
                        "symbol": contract.symbol,
                        "secType": contract.secType,
                        "strike": contract.strike,
                        "right": contract.right,
                        "expiry": contract.lastTradeDateOrContractMonth,
                        "multiplier": float(contract.multiplier or "100"),
                    },
                    "status": "Queued",
                }
            else:
                portfolio_data[conId].update(
                    {
                        "position": position,
                        "avgCost": avgCost,
                        "costBasis": cost_basis,
                        "account": account,
                    }
                )

    def positionEnd(self):
        super().positionEnd()
        with portfolio_lock:
            all_conIds = set(portfolio_data.keys())
            stale_conIds = all_conIds - self._positions_being_updated
            for conId in stale_conIds:
                if conId in portfolio_data:
                    pnl_req_id = portfolio_data[conId].get("pnl_req_id")
                    mkt_req_id = portfolio_data[conId].get("mkt_req_id")
                    if pnl_req_id:
                        api_gate.wait()
                        self.cancelPnLSingle(pnl_req_id)
                    if mkt_req_id:
                        api_gate.wait()
                        self.cancelMktData(mkt_req_id)
                    del portfolio_data[conId]
            current_symbols = {
                p["contract"]["symbol"]
                for p in portfolio_data.values()
                if p["contract"]["secType"] == "OPT"
            }
            new_symbols_to_req = current_symbols - set(underlying_mkt_reqs.keys())
            for symbol in new_symbols_to_req:
                uc = Contract()
                uc.symbol = symbol
                uc.currency = "USD"
                uc.secType = "IND" if symbol in ["SPX", "VIX"] else "STK"
                uc.exchange = "CBOE" if symbol in ["SPX", "VIX"] else "SMART"
                req_id = self.allocate_req_id()
                underlying_mkt_reqs[symbol] = req_id
                self.req_map[req_id] = symbol
                self.reqMktData(req_id, uc, "106", False, False, [])
            stale_symbols_to_cancel = set(underlying_mkt_reqs.keys()) - current_symbols
            for symbol in stale_symbols_to_cancel:
                req_id = underlying_mkt_reqs.pop(symbol)
                self.cancelMktData(req_id)
                if symbol in underlying_prices:
                    del underlying_prices[symbol]
        self._positions_being_updated.clear()
        print(
            f"--> ✅ Position snapshot complete. Current positions: {len(portfolio_data)}"
        )

    def get_contract_description(self, contract: Contract):
        try:
            if contract.secType in ["STK", "ETF", "FUT"]:
                return f"{contract.symbol}"
            elif contract.secType == "OPT":
                right = "Call" if contract.right == "C" else "Put"
                strike_val = float(contract.strike) if contract.strike else 0.0
                return f"{contract.symbol} {contract.lastTradeDateOrContractMonth} {int(strike_val)} {right}"
        except Exception as e:
            print(f"Error formatting description for {contract.localSymbol}: {e}")
        return contract.localSymbol.strip()

    def contractDetails(self, reqId, contractDetails):
        if reqId not in self.req_map or not isinstance(self.req_map.get(reqId), dict):
            return

        req = self.req_map[reqId]
        if "contracts" in req:
            req["contracts"].append(contractDetails)
            return

        if "event" in req:
            req["contract"] = contractDetails.contract

    def contractDetailsEnd(self, reqId):
        if (
            reqId in self.req_map
            and isinstance(self.req_map.get(reqId), dict)
            and "event" in self.req_map[reqId]
        ):
            self.req_map[reqId]["event"].set()

    def securityDefinitionOptionParameter(
        self,
        reqId,
        exchange,
        underlyingConId,
        tradingClass,
        multiplier,
        expirations,
        strikes,
    ):
        if (
            reqId in self.req_map
            and isinstance(self.req_map.get(reqId), dict)
            and "event" in self.req_map[reqId]
        ):
            req = self.req_map[reqId]
            if "expirations" not in req:
                req["expirations"] = set()
                req["strikes"] = set()
            req["expirations"].update(expirations)
            req["strikes"].update(strikes)

    def securityDefinitionOptionParameterEnd(self, reqId):
        if (
            reqId in self.req_map
            and isinstance(self.req_map.get(reqId), dict)
            and "event" in self.req_map[reqId]
        ):
            self.req_map[reqId]["event"].set()

    def pnlSingle(self, reqId, pos, dailyPnL, unrealizedPnL, realizedPnL, value):
        conId = self.req_map.get(reqId)
        if not conId or not isinstance(conId, int):
            return
        with portfolio_lock:
            if conId in portfolio_data:
                leg = portfolio_data[conId]
                if dailyPnL is not None and dailyPnL != float("inf"):
                    leg["pnl"]["daily"] = dailyPnL
                if value is not None and value != float("inf"):
                    leg["marketValue"] = value
                    leg["pnl"]["unrealized"] = value - leg["costBasis"]
                self.fallback_deadline.pop(conId, None)

    def tickPrice(self, reqId, tickType, price, attrib):
        snapshot_req = self.req_map.get(reqId)
        if isinstance(snapshot_req, dict) and "snapshot_chain_leg" in snapshot_req:
            update_quote_bucket_from_tick(
                snapshot_req.get("snapshot_chain_leg"), tickType, price
            )
            return

        if reqId in self.active_chain_reqs:
            with chain_lock:
                conId = self.req_map.get(reqId)
                if conId and conId in chain_data_cache:
                    leg_data = chain_data_cache[conId]
                    update_quote_bucket_from_tick(leg_data, tickType, price)
                    if (
                        "bid" in leg_data
                        and "ask" in leg_data
                        and leg_data["bid"] is not None
                        and leg_data["ask"] is not None
                    ):
                        leg_data["mid"] = round(
                            (leg_data["bid"] + leg_data["ask"]) / 2.0, 2
                        )
            return

        map_val = self.req_map.get(reqId)
        if not map_val:
            return
        with portfolio_lock:
            if isinstance(map_val, str):  # Underlying price update
                if tickType in [4, 9, 68] and price > -1:
                    underlying_prices[map_val] = price
                elif tickType in [1, 2] and price > -1:
                    if map_val not in underlying_prices:
                        underlying_prices[map_val] = {}
                    if isinstance(underlying_prices[map_val], dict):
                        if tickType == 1:
                            underlying_prices[map_val]["bid"] = price
                        elif tickType == 2:
                            underlying_prices[map_val]["ask"] = price
                        ubid = underlying_prices[map_val].get("bid")
                        uask = underlying_prices[map_val].get("ask")
                        if ubid is not None and uask is not None:
                            underlying_prices[map_val] = (ubid + uask) / 2

            elif isinstance(map_val, int):  # Portfolio leg update
                conId = map_val
                if conId in portfolio_data:
                    leg = portfolio_data[conId]
                    self.fallback_deadline.pop(conId, None)
                    if conId not in self.tick_data:
                        self.tick_data[conId] = {}

                    if tickType == 1:
                        self.tick_data[conId]["bid"] = price
                        leg["bid"] = price
                    elif tickType == 2:
                        self.tick_data[conId]["ask"] = price
                        leg["ask"] = price
                    elif tickType == 4 and price > -1:
                        self.tick_data[conId]["last"] = price
                    elif tickType == 9 and price > -1:
                        self.tick_data[conId]["close"] = price
                    elif tickType == 66 and price > -1:
                        self.tick_data[conId]["delayed_last"] = price

                    multiplier = get_contract_multiplier(leg.get("contract"))

                    last_price = self.tick_data[conId].get("last", -1.0)
                    if last_price == -1.0:
                        last_price = self.tick_data[conId].get("close", -1.0)
                    if last_price == -1.0:
                        last_price = self.tick_data[conId].get("delayed_last", -1.0)

                    if last_price == -1.0:
                        bid = self.tick_data[conId].get("bid", -1.0)
                        ask = self.tick_data[conId].get("ask", -1.0)
                        if bid > -1 and ask > -1:
                            last_price = (bid + ask) / 2

                    if last_price > -1:
                        leg["marketValue"] = last_price * leg["position"] * multiplier
                        leg["pnl"]["unrealized"] = leg["marketValue"] - leg["costBasis"]
                        if leg["status"] != "Live (EOD)":
                            leg["status"] = "Live"

    def tickOptionComputation(
        self,
        reqId,
        tickType,
        tickAttrib,
        impliedVol,
        delta,
        optPrice,
        pvDividend,
        gamma,
        vega,
        theta,
        undPrice,
    ):
        map_val = self.req_map.get(reqId)
        if isinstance(map_val, dict) and "snapshot_chain_leg" in map_val:
            if tickType != 13:
                return
            snapshot = map_val.get("snapshot_chain_leg")
            if impliedVol is not None and impliedVol > -1:
                snapshot["iv"] = impliedVol
            if delta is not None and abs(delta) <= 1:
                snapshot["delta"] = delta
            if optPrice is not None and optPrice > 0:
                snapshot["modelPrice"] = optPrice
            return

        conId = map_val
        # log_prefix = f"tickOptionComputation (ReqId:{reqId}, ConId:{conId}): "

        if tickType != 13:
            return

        # print(log_prefix + f"Received Data -> IV:{impliedVol}, Delta:{delta}, Gamma:{gamma}, Vega:{vega}, Theta:{theta}, OptPrice:{optPrice}, UndPrice:{undPrice}")

        global chain_underlying_price
        if undPrice is not None and undPrice > 0:
            if reqId in self.active_chain_reqs:
                chain_underlying_price = undPrice
            else:
                if conId and isinstance(conId, int) and conId in portfolio_data:
                    with portfolio_lock:
                        portfolio_data[conId]["greeks"]["undPrice"] = undPrice

        if reqId in self.active_chain_reqs:
            with chain_lock:
                if conId and conId in chain_data_cache:
                    leg_data = chain_data_cache[conId]
                    if impliedVol is not None and impliedVol > -1:
                        leg_data["iv"] = impliedVol
                    if delta is not None and abs(delta) <= 1:
                        leg_data["delta"] = delta
                    if optPrice is not None and optPrice > 0:
                        leg_data["modelPrice"] = optPrice
            return

        if not conId or not isinstance(conId, int):
            return

        with portfolio_lock:
            if conId in portfolio_data:
                leg = portfolio_data[conId]
                greeks = leg["greeks"]

                valid_greeks = {}
                if delta is not None and abs(delta) <= 1:
                    valid_greeks["delta"] = delta
                if gamma is not None and gamma >= 0:
                    valid_greeks["gamma"] = gamma
                if vega is not None:
                    valid_greeks["vega"] = vega
                if theta is not None:
                    valid_greeks["theta"] = theta
                if impliedVol is not None and impliedVol > -1:
                    valid_greeks["iv"] = impliedVol

                if valid_greeks:
                    greeks.update(valid_greeks)
                    if leg["status"] != "Live (EOD)":
                        leg["status"] = "Live"
                    # print(log_prefix + f"Updated portfolio greeks: {valid_greeks}")
                # else:
                # print(log_prefix + "No valid greeks received to update portfolio.")

                if optPrice is not None and optPrice > 0:
                    multiplier = get_contract_multiplier(leg.get("contract"))
                    leg["marketValue"] = optPrice * leg["position"] * multiplier
                    leg["pnl"]["unrealized"] = leg["marketValue"] - leg["costBasis"]

                self.fallback_deadline.pop(conId, None)

    def tickSnapshotEnd(self, reqId):
        req_data = self.req_map.get(reqId)
        if (
            isinstance(req_data, dict)
            and "event" in req_data
            and "snapshot_chain_leg" in req_data
        ):
            req_data["event"].set()

    def start_eod_fallback(self, conId):
        with portfolio_lock:
            leg = portfolio_data.get(conId)
            if (
                not leg
                or conId in self.eod_fallback_inflight
                or leg["status"].startswith("Live")
            ):
                return
            print(
                f"--> Starting EOD fallback for {leg['description']} (ConId: {conId})..."
            )
            self.eod_fallback_inflight.add(conId)

            if not leg["greeks"].get("undPrice"):
                und = Contract()
                und.symbol = leg["contract"]["symbol"]
                und.currency = "USD"
                und.exchange = "SMART"
                if leg["contract"]["secType"] in ("FOP", "FUT"):
                    und.secType = "FUT"
                elif leg["contract"]["symbol"] in ("SPX", "VIX"):
                    und.secType = "IND"
                    und.exchange = "CBOE"
                else:
                    und.secType = "STK"
                hist_id = self.allocate_req_id()
                self.hist_req_map[hist_id] = ("und", conId)
                query_time = (datetime.now() - timedelta(days=1)).strftime(
                    "%Y%m%d 23:59:59"
                )
                print(
                    f"    Requesting EOD underlying for {und.symbol} (HistId: {hist_id})"
                )
                api_gate.wait()
                self.reqHistoricalData(
                    hist_id,
                    und,
                    query_time,
                    "1 D",
                    "1 day",
                    UNDERLYING_EOD_SOURCE,
                    0,
                    1,
                    False,
                    [],
                )

            if leg["contract"]["secType"] == "OPT":
                opt = Contract()
                opt.conId = conId
                opt.exchange = "SMART"
                opt.currency = "USD"
                hist_id2 = self.allocate_req_id()
                self.hist_req_map[hist_id2] = ("opt", conId)
                query_time = (datetime.now() - timedelta(days=1)).strftime(
                    "%Y%m%d 23:59:59"
                )
                print(
                    f"    Requesting EOD option price for {leg['description']} (HistId: {hist_id2})"
                )
                api_gate.wait()
                self.reqHistoricalData(
                    hist_id2,
                    opt,
                    query_time,
                    "1 D",
                    "1 day",
                    OPTION_EOD_SOURCE,
                    0,
                    1,
                    False,
                    [],
                )
            else:
                self.eod_fallback_inflight.discard(conId)

    def historicalData(self, reqId, bar):
        # print(f"historicalData (ReqId: {reqId}): Received bar - Close={bar.close}")
        if reqId in self.hist_req_map:
            kind, conId = self.hist_req_map.get(reqId, (None, None))
            if not conId:
                return

            processed = False
            with portfolio_lock:
                if conId not in portfolio_data:
                    return
                leg = portfolio_data[conId]

                if kind == "und":
                    if leg["greeks"].get("undPrice") is None:
                        leg["greeks"]["undPrice"] = bar.close
                        # print(f"    EOD Fallback: Set UndPrice for ConId {conId} to {bar.close}")
                        processed = True
                        if leg["contract"]["secType"] != "OPT":
                            self.eod_fallback_inflight.discard(conId)
                            if leg["status"] != "Live":
                                leg["status"] = "Live (EOD)"
                    # else:
                    # print(f"    EOD Fallback: UndPrice for ConId {conId} already exists ({leg['greeks']['undPrice']}), ignoring EOD value {bar.close}")
                    # if leg['contract']['secType'] != 'OPT': self.eod_fallback_inflight.discard(conId)

                elif kind == "opt":
                    try:
                        S = leg["greeks"].get("undPrice")
                        if (
                            S
                            and S > 0
                            and bar.close > 0
                            and leg["greeks"].get("iv") is None
                        ):
                            K = leg["contract"]["strike"]
                            r_type = leg["contract"]["right"].lower()
                            expiry_dt = datetime.strptime(
                                leg["contract"]["expiry"], "%Y%m%d"
                            )
                            T = max(1e-9, (expiry_dt - datetime.now()).days / 365.25)
                            # print(f"    EOD Fallback: Calculating IV for ConId {conId} with S={S}, K={K}, T={T:.4f}, Price={bar.close}")
                            iv = bs_iv(bar.close, S, K, T, RISK_FREE_RATE, r_type)
                            # print(f"    EOD Fallback: Calculated IV = {iv}")
                            if iv and iv > 0 and math.isfinite(iv):
                                greeks_to_update = {
                                    "iv": iv,
                                    "delta": delta(r_type, S, K, T, RISK_FREE_RATE, iv),
                                    "gamma": gamma(r_type, S, K, T, RISK_FREE_RATE, iv),
                                    "vega": vega(r_type, S, K, T, RISK_FREE_RATE, iv),
                                    "theta": theta(r_type, S, K, T, RISK_FREE_RATE, iv),
                                }
                                leg["greeks"].update(greeks_to_update)
                                # print(f"    EOD Fallback: Calculated and updated greeks for ConId {conId}: {greeks_to_update}")
                            # else: print(f"    EOD Fallback: IV calculation failed or invalid for ConId {conId}.")
                        # elif not S or S <= 0: print(f"    EOD Fallback: Cannot calculate greeks for ConId {conId} yet, missing underlying price.")
                        # elif leg['greeks'].get('iv') is not None: print(f"    EOD Fallback: Greeks for ConId {conId} already exist, ignoring EOD calculation.")

                        multiplier = get_contract_multiplier(leg.get("contract"))
                        leg["marketValue"] = bar.close * leg["position"] * multiplier
                        leg["pnl"]["unrealized"] = leg["marketValue"] - leg["costBasis"]
                        if leg["status"] != "Live":
                            leg["status"] = "Live (EOD)"
                        # print(f"    EOD Fallback: Updated MarketValue for ConId {conId} to {leg['marketValue']}")
                        processed = True

                    except Exception as ex:
                        print(
                            f"    EOD Fallback: Error during calculation for ConId {conId}: {ex}"
                        )
                        if leg["status"] not in ["Live", "Live (EOD)"]:
                            leg["status"] = "Error"
                    finally:
                        self.eod_fallback_inflight.discard(conId)
                        # print(f"    EOD Fallback: Finished processing OPT for ConId {conId}")

            if processed and reqId in self.hist_req_map:
                del self.hist_req_map[reqId]

    def historicalDataEnd(self, reqId, start, end):
        # print(f"historicalDataEnd received for ReqId: {reqId}")
        hist_req_info = self.hist_req_map.pop(reqId, None)
        if hist_req_info:
            kind, conId = hist_req_info
            # print(f"    Cleaning up hist_req_map for ReqId {reqId} (ConId: {conId}, Kind: {kind})")
            with portfolio_lock:
                if conId in portfolio_data:
                    leg = portfolio_data[conId]
                    is_opt = leg["contract"]["secType"] == "OPT"
                    if is_opt and kind == "opt":
                        self.eod_fallback_inflight.discard(conId)
                        # print(f"    EOD Fallback: Finalizing OPT fallback for ConId {conId} due to historicalDataEnd.")
                        if leg["status"] in ["Loading...", "Queued", "Error"]:
                            leg["status"] = (
                                "Live (EOD)"
                                if leg["marketValue"] is not None
                                else "Error"
                            )
                    elif not is_opt and kind == "und":
                        self.eod_fallback_inflight.discard(conId)
                        # print(f"    EOD Fallback: Finalizing non-OPT fallback for ConId {conId} due to historicalDataEnd.")
                        if leg["status"] in ["Loading...", "Queued", "Error"]:
                            leg["status"] = (
                                "Live (EOD)"
                                if leg["marketValue"] is not None
                                else "Error"
                            )


def process_request_queue():
    while True:
        try:
            if not ib_app or not ib_app.isConnected():
                time.sleep(0.1)
                continue
            conId = request_queue.get(timeout=1)
            with portfolio_lock:
                if conId not in portfolio_data:
                    continue
                leg = portfolio_data[conId]
                fc = Contract()
                fc.conId = conId
                fc.exchange = "SMART"

            # print(f"Processing request queue for ConId: {conId} ({leg['description']})")

            pnl_req_id = allocate_request_id(ib_app)
            ib_app.req_map[pnl_req_id] = conId
            # print(f"  Requesting PnL (ReqId: {pnl_req_id})")
            api_gate.wait()
            ib_app.reqPnLSingle(pnl_req_id, leg["account"], "", conId)

            mkt_req_id = allocate_request_id(ib_app)
            ib_app.req_map[mkt_req_id] = conId
            genericTickList = "100,101,104,106"
            # print(f"  Requesting Market Data (ReqId: {mkt_req_id}, Ticks: {genericTickList})")
            api_gate.wait()
            ib_app.reqMktData(mkt_req_id, fc, genericTickList, False, False, [])

            with portfolio_lock:
                ib_app.fallback_deadline[conId] = time.time() + FALLBACK_TIMEOUT_SEC

        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ Error in request queue processing: {e}")
            traceback.print_exc()


def auto_refresh_positions():
    while True:
        time.sleep(REFRESH_INTERVAL)
        if ib_app and ib_app.isConnected() and "--snapshot" not in sys.argv:
            print("--> Auto-refreshing positions...")
            try:
                ib_app.request_account_summary_stream()
                api_gate.wait()
                ib_app.reqPositions()
            except Exception as e:
                print(f"❌ Error during auto-refresh: {e}")


def fallback_watchdog():
    while True:
        time.sleep(1)
        if not ib_app or not ib_app.isConnected():
            continue
        now = time.time()

        items_to_check = list(ib_app.fallback_deadline.items())

        for conId, deadline in items_to_check:
            if now >= deadline:
                # print(f"Fallback Watchdog: Deadline reached for ConId {conId}.")
                if conId in ib_app.fallback_deadline:
                    try:
                        ib_app.start_eod_fallback(conId)
                    except Exception as e:
                        print(f"❌ Error starting EOD fallback for {conId}: {e}")
                    finally:
                        ib_app.fallback_deadline.pop(conId, None)


def threaded_place_order(order_id, contract, order):
    try:
        if not hasattr(order, "algoParams"):
            order.algoParams = []
        if not hasattr(order, "smartComboRoutingParams"):
            order.smartComboRoutingParams = []

        print(
            f"--> [Thread] Submitting order {order_id} to TWS for Acc: {order.account}"
        )
        print(
            f"    Contract: {contract.symbol}, SecType: {contract.secType}, Exchange: {contract.exchange}"
        )
        if contract.secType == "BAG":
            for i, leg in enumerate(contract.comboLegs):
                print(
                    f"    Leg {i + 1}: conId={leg.conId}, ratio={leg.ratio}, action={leg.action}, exchange={leg.exchange}"
                )
        print(
            f"    Order: Action={order.action}, Type={order.orderType}, Qty={order.totalQuantity}, LmtPx={getattr(order, 'lmtPrice', 'N/A')}, TIF={order.tif}, Transmit={order.transmit}"
        )

        time.sleep(0.1)

        ib_app.placeOrder(order_id, contract, order)
        print(f"--> [Thread] API call to placeOrder for {order_id} completed.")

    except Exception as e:
        print(f"❌ Exception in threaded_place_order for order_id={order_id}: {e}")
        traceback.print_exc()


# --- Flask Routes ---
register_core_routes(
    app,
    base_dir=BASE_DIR,
    combos_file=COMBOS_FILE,
    portfolio_data=portfolio_data,
    portfolio_lock=portfolio_lock,
    request_queue=request_queue,
    underlying_prices=underlying_prices,
    api_gate=api_gate,
    get_ib_app=lambda: ib_app,
    get_runtime_diagnostics=get_runtime_diagnostics,
    normalize_combos_payload=normalize_combos_payload,
    client_portal_adapter=client_portal_adapter,
)


@app.route("/place_order", methods=["POST"])
def place_order():
    if not ib_app or not ib_app.isConnected():
        return jsonify({"error": "TWS not connected"}), 503

    try:
        data = request.get_json(silent=True) or {}
        legs = data.get("legs", [])
        orderType = data.get("orderType", "LMT")
        limitPrice = data.get("limitPrice")
        account = data.get("account")
        tif = data.get("tif", "DAY")

        if not legs or not account:
            return jsonify({"error": "Missing legs or account information"}), 400

        order = Order()
        order.orderType = orderType
        order.tif = tif
        # <-- FIX: Set transmit to False -->
        order.transmit = False
        order.account = account

        order.eTradeOnly = False
        order.firmQuoteOnly = False
        order.optOutSmartRouting = False
        order.outsideRth = False

        order_id = ib_app.next_order_id
        ib_app.next_order_id += 1

        print(
            f"\n--- Preparing Order {order_id} (Transmit=False) ---"
        )  # <-- Log transmit status
        print(f"Account: {account}, Type: {orderType}, TIF: {tif}")

        if len(legs) == 1:
            # --- Single Leg Order ---
            leg = legs[0]
            conId = leg.get("conId")
            qty = float(leg.get("qty"))

            if not conId or not qty:
                return jsonify(
                    {"error": "Missing conId or quantity for single leg order"}
                ), 400

            temp_contract = Contract()
            temp_contract.conId = conId
            req_id = allocate_request_id(ib_app)
            event = threading.Event()
            ib_app.req_map[req_id] = {"event": event, "contract": None}

            print(f"  Qualifying contract for conId {conId} (req_id={req_id})...")
            api_gate.wait()
            ib_app.reqContractDetails(req_id, temp_contract)

            if not event.wait(timeout=15):
                ib_app.req_map.pop(req_id, None)
                return jsonify(
                    {
                        "error": f"Timeout getting contract details for conId {conId} (req_id={req_id})"
                    }
                ), 504

            contract = ib_app.req_map.pop(req_id, {}).get("contract")
            if not contract:
                return jsonify(
                    {
                        "error": f"Could not qualify contract for conId {conId} (req_id={req_id})"
                    }
                ), 400

            order.action = "BUY" if qty < 0 else "SELL"
            order.totalQuantity = abs(qty)

            if orderType == "LMT":
                if limitPrice is None or limitPrice <= 0:
                    return jsonify(
                        {
                            "error": "Valid positive Limit Price is required for LMT order."
                        }
                    ), 400
                order.lmtPrice = float(limitPrice)
            elif orderType == "MKT":
                order.lmtPrice = 0
            else:
                return jsonify({"error": f"Unsupported order type: {orderType}"}), 400

            print(
                f"  Placing single leg order: {order.action} {order.totalQuantity} {contract.localSymbol} @ {order.lmtPrice if orderType == 'LMT' else 'MKT'}"
            )

            order_thread = threading.Thread(
                target=threaded_place_order, args=(order_id, contract, order)
            )
            order_thread.start()

        else:
            # --- Combo Order ---
            print(f"  Preparing {len(legs)}-leg combo order...")

            qualified_contracts = {}
            for leg_data in legs:
                conId = leg_data.get("conId")
                if not conId:
                    return jsonify({"error": "Missing conId in combo leg data"}), 400

                if conId not in qualified_contracts:
                    temp_contract = Contract()
                    temp_contract.conId = conId
                    req_id = allocate_request_id(ib_app)
                    event = threading.Event()
                    ib_app.req_map[req_id] = {"event": event, "contract": None}

                    print(f"    - Qualifying leg conId {conId} (req_id={req_id})...")
                    api_gate.wait()
                    ib_app.reqContractDetails(req_id, temp_contract)

                    if not event.wait(timeout=15):
                        ib_app.req_map.pop(req_id, None)
                        return jsonify(
                            {
                                "error": f"Timeout qualifying conId {conId} (req_id={req_id})"
                            }
                        ), 504

                    qualified = ib_app.req_map.pop(req_id, {}).get("contract")
                    if not qualified:
                        return jsonify(
                            {
                                "error": f"Could not qualify conId {conId} (req_id={req_id})"
                            }
                        ), 400

                    qualified_contracts[conId] = qualified

            first_conId = legs[0].get("conId")
            symbol = data.get("symbol", qualified_contracts[first_conId].symbol)

            contract = Contract()
            contract.symbol = symbol
            contract.secType = "BAG"
            contract.currency = "USD"
            bag_exchange = "CBOE" if symbol in ["SPX", "SPXW", "VIX"] else "SMART"
            contract.exchange = bag_exchange
            if symbol in ["SPX", "SPXW"]:
                contract.tradingClass = "SPX"

            contract.comboLegs = []
            order.totalQuantity = 1

            net_delta_sign = 0

            for leg_data in legs:
                conId = leg_data.get("conId")
                qty = float(leg_data.get("qty"))
                if qty == 0:
                    continue

                combo_leg = ComboLeg()
                combo_leg.conId = conId
                combo_leg.ratio = int(abs(qty))
                combo_leg.action = "BUY" if qty < 0 else "SELL"
                combo_leg.exchange = bag_exchange
                contract.comboLegs.append(combo_leg)

                with portfolio_lock:
                    tws_data = portfolio_data.get(conId)
                    if tws_data and tws_data["greeks"].get("delta") is not None:
                        net_delta_sign += tws_data["greeks"]["delta"] * qty

            if not contract.comboLegs:
                return jsonify({"error": "No valid legs found for combo order"}), 400

            if orderType == "LMT":
                if limitPrice is None:
                    return jsonify(
                        {"error": "Net Limit Price is required for LMT combo order."}
                    ), 400
                lp = float(limitPrice)
                order.action = "BUY" if lp > 0 else "SELL"
                order.lmtPrice = abs(lp)
            elif orderType == "MKT":
                order.action = "SELL" if net_delta_sign > 0 else "BUY"
                order.lmtPrice = 0
            else:
                return jsonify({"error": f"Unsupported order type: {orderType}"}), 400

            print(
                f"  COMBO CONTRACT: Symbol={contract.symbol}, SecType={contract.secType}, Exchange={contract.exchange}, TradingClass={getattr(contract, 'tradingClass', 'N/A')}"
            )
            for i, leg in enumerate(contract.comboLegs):
                print(
                    f"    Leg {i + 1}: conId={leg.conId}, ratio={leg.ratio}, action={leg.action}, exchange={leg.exchange}"
                )

            print(
                f"  PLACING COMBO ORDER: {order.action} {order.totalQuantity} unit(s) @ {order.lmtPrice if orderType == 'LMT' else 'MKT'}"
            )

            order_thread = threading.Thread(
                target=threaded_place_order, args=(order_id, contract, order)
            )
            order_thread.start()

        return jsonify(
            {
                "status": "success",
                # <-- Modified success message -->
                "message": f"Order {order_id} sent to TWS. Please check TWS Activity Monitor to transmit.",
                "orderId": order_id,
            }
        )

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ Order submission error:\n{error_trace}")
        return jsonify({"error": str(e), "trace": error_trace}), 500


# ... (rest of the file remains unchanged) ...
@app.route("/get_expiries", methods=["GET"])
def get_expiries():
    symbol = request.args.get("symbol")
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    symbol = str(symbol).strip().upper()
    if not ib_app or not ib_app.isConnected():
        return jsonify({"error": "TWS not connected"}), 503

    contract = build_expiry_lookup_contract(symbol)
    underlying_con_id = 0
    qualified_con_id = maybe_qualify_underlying_conid(ib_app, contract)
    if qualified_con_id:
        underlying_con_id = int(qualified_con_id)
        print(
            f"--> Using qualified underlying conId {underlying_con_id} for {symbol}"
        )
    else:
        print(
            f"⚠️ Proceeding without qualified underlying conId for {symbol}; falling back to 0."
        )

    def fetch_expiries_for_conid(con_id, timeout_sec):
        req_id_local = allocate_request_id(ib_app)
        event_local = threading.Event()
        ib_app.req_map[req_id_local] = {
            "event": event_local,
            "expirations": set(),
            "strikes": set(),
            "req_type": "opt_params",
        }

        print(
            f"--> Requesting option parameters for {symbol} (req_id={req_id_local}, conId={int(con_id or 0)})"
        )
        api_gate.wait()
        ib_app.reqSecDefOptParams(
            req_id_local,
            contract.symbol,
            "",
            contract.secType,
            int(con_id or 0),
        )

        timed_out_local = not event_local.wait(timeout=timeout_sec)
        req_data_local = ib_app.req_map.pop(req_id_local, {})
        expirations_local = sorted(
            {
                str(value).strip()
                for value in req_data_local.get("expirations", set())
                if str(value).strip()
            }
        )
        return req_id_local, expirations_local, timed_out_local

    wait_timeout = 30 if contract.secType == "IND" else 20
    req_id, expirations, timed_out = fetch_expiries_for_conid(
        underlying_con_id, wait_timeout
    )

    if not expirations and underlying_con_id > 0:
        print(
            f"⚠️ No expirations returned for {symbol} using conId {underlying_con_id}; retrying with conId 0."
        )
        retry_req_id, retry_expirations, retry_timed_out = fetch_expiries_for_conid(
            0, wait_timeout
        )
        if retry_expirations:
            req_id = retry_req_id
            expirations = retry_expirations
            timed_out = retry_timed_out
        else:
            timed_out = timed_out and retry_timed_out

    if timed_out and not expirations:
        print(f"Timeout fetching expirations for {symbol} (req_id={req_id})")
        return jsonify({"error": f"Timeout fetching expirations for {symbol}"}), 504
    if timed_out and expirations:
        print(
            f"⚠️ Option param end timeout for {symbol}, using partial expirations: {len(expirations)}"
        )

    if not expirations:
        print(f"No expirations found for {symbol} (req_id={req_id})")
        return jsonify(
            {
                "error": f"No option expirations found for {symbol}. Is it an optionable symbol?"
            }
        ), 404

    und_price = underlying_prices.get(symbol)
    if not und_price or isinstance(und_price, dict):
        print(
            f"Underlying price for {symbol} not cached or incomplete, requesting snapshot..."
        )
        und_contract = Contract()
        und_contract.symbol = symbol
        und_contract.secType = contract.secType
        und_contract.exchange = contract.exchange
        und_contract.currency = "USD"

        und_req_id = allocate_request_id(ib_app)
        ib_app.req_map[und_req_id] = symbol

        api_gate.wait()
        ib_app.reqMktData(und_req_id, und_contract, "1,2,4,9", True, False, [])

        time.sleep(1.5)

        und_price = underlying_prices.get(symbol)
        if isinstance(und_price, dict):
            ubid = und_price.get("bid")
            uask = und_price.get("ask")
            if ubid is not None and uask is not None:
                und_price = (ubid + uask) / 2
            else:
                und_price = None
                print(
                    f"Could not get underlying price for {symbol} after snapshot request."
                )
        elif und_price:
            print(f"Got underlying price {und_price} for {symbol} from snapshot.")

        api_gate.wait()
        ib_app.cancelMktData(und_req_id)
        ib_app.req_map.pop(und_req_id, None)

    print(
        f"Returning {len(expirations)} expirations for {symbol}. Und Price: {und_price}"
    )
    return jsonify({"expiries": expirations, "undPrice": und_price})


@app.route("/option_chain", methods=["GET"])
def get_option_chain():
    symbol = str(request.args.get("symbol") or "").strip().upper()
    expiry = request.args.get("expiry")
    strike_half_width = int(safe_float(request.args.get("strike_half_width"), 10))
    strike_half_width = max(2, min(strike_half_width, 30))
    if not symbol or not expiry:
        return jsonify({"error": "Symbol and expiry are required"}), 400
    if not ib_app or not ib_app.isConnected():
        return jsonify({"error": "TWS not connected"}), 503

    print(f"\n--- Requesting Option Chain: {symbol} {expiry} ---")

    active_reqs = list(ib_app.active_chain_reqs)
    print(f"Cancelling {len(active_reqs)} previous chain market data requests...")
    for req_id in active_reqs:
        api_gate.wait()
        ib_app.cancelMktData(req_id)
        ib_app.req_map.pop(req_id, None)
    ib_app.active_chain_reqs.clear()

    with chain_lock:
        chain_data_cache.clear()
        global chain_underlying_price
        chain_underlying_price = None

    contract = Contract()
    contract.symbol = symbol
    contract.secType = "OPT"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiry

    contracts_details = get_cached_option_chain_contracts(symbol, expiry)
    timed_out = False
    used_contract_cache = bool(contracts_details)
    if used_contract_cache:
        print(
            f"Using cached contract details for {symbol} {expiry} ({len(contracts_details)} contracts)."
        )
    else:
        req_id = allocate_request_id(ib_app)
        event = threading.Event()
        ib_app.req_map[req_id] = {
            "event": event,
            "contracts": [],
            "req_type": "chain_details",
        }

        print(f"Requesting contract details for chain (req_id={req_id})...")
        api_gate.wait()
        ib_app.reqContractDetails(req_id, contract)

        timed_out = not event.wait(timeout=25)
        req_data = ib_app.req_map.pop(req_id, {})
        contracts_details = req_data.get("contracts", [])

        if timed_out:
            print(
                f"Timeout fetching option chain contracts for {symbol} {expiry} (req_id={req_id}); partial contracts: {len(contracts_details)}"
            )
        elif contracts_details:
            set_cached_option_chain_contracts(symbol, expiry, contracts_details)

    if not contracts_details:
        print(f"No contracts found for {symbol} {expiry}.")
        return jsonify(
            {"error": "No contracts found for the specified symbol and expiry."}
        ), 404

    spot_price = None
    cached_underlying = underlying_prices.get(symbol)
    if isinstance(cached_underlying, dict):
        ubid = finite_positive_or_none(cached_underlying.get("bid"))
        uask = finite_positive_or_none(cached_underlying.get("ask"))
        if ubid is not None and uask is not None:
            spot_price = (ubid + uask) / 2.0
    else:
        spot_price = finite_positive_or_none(cached_underlying)

    selected_contracts = select_chain_contracts_for_stream(
        contracts_details,
        spot_price=spot_price,
        strike_half_width=strike_half_width,
    )
    if not selected_contracts:
        return jsonify({"error": "No valid option contracts found for selected expiry."}), 404

    print(
        f"Received {len(contracts_details)} contracts for chain; selected {len(selected_contracts)} for streaming window."
    )

    selected_con_ids = []
    selected_contract_by_con_id = {}
    with chain_lock:
        for c_details in selected_contracts:
            c = c_details.contract
            selected_contract_by_con_id[c.conId] = c
            chain_data_cache[c.conId] = {
                "conId": c.conId,
                "strike": c.strike,
                "right": c.right,
                "bid": None,
                "ask": None,
                "mid": None,
                "last": None,
                "close": None,
                "delayed_last": None,
                "modelPrice": None,
                "iv": None,
                "delta": None,
            }
            selected_con_ids.append(c.conId)
            mkt_req_id = allocate_request_id(ib_app)
            ib_app.req_map[mkt_req_id] = c.conId
            ib_app.active_chain_reqs.add(mkt_req_id)
            api_gate.wait()
            ib_app.reqMktData(mkt_req_id, c, "106", False, False, [])

    wait_deadline = time.time() + 6.0
    coverage_target = max(4, int(round(len(selected_con_ids) * 0.35)))
    coverage_any = 0
    while time.time() < wait_deadline:
        with chain_lock:
            coverage_any = 0
            for con_id in selected_con_ids:
                quote = chain_data_cache.get(con_id, {})
                mark, _, _ = resolve_chain_mark_and_quality(
                    bid=quote.get("bid"),
                    ask=quote.get("ask"),
                    last=quote.get("last") or quote.get("delayed_last"),
                    model=quote.get("modelPrice"),
                    close=quote.get("close"),
                )
                if mark is not None:
                    coverage_any += 1
        if coverage_any >= coverage_target:
            break
        time.sleep(0.2)

    snapshot_requested = 0
    snapshot_completed = 0
    snapshot_mark_recovered = 0
    snapshot_max_contracts = 16
    with chain_lock:
        missing_con_ids = []
        for con_id in selected_con_ids:
            quote = chain_data_cache.get(con_id, {})
            mark, _, _ = resolve_chain_mark_and_quality(
                bid=quote.get("bid"),
                ask=quote.get("ask"),
                last=quote.get("last") or quote.get("delayed_last"),
                model=quote.get("modelPrice"),
                close=quote.get("close"),
            )
            if mark is None:
                missing_con_ids.append(con_id)

    snapshot_candidates = missing_con_ids[:snapshot_max_contracts]
    snapshot_requested = len(snapshot_candidates)
    for con_id in snapshot_candidates:
        contract = selected_contract_by_con_id.get(con_id)
        if contract is None:
            continue

        snapshot_req_id = allocate_request_id(ib_app)
        snapshot_event = threading.Event()
        snapshot_entry = {
            "event": snapshot_event,
            "snapshot_chain_leg": {
                "conId": con_id,
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
        ib_app.req_map[snapshot_req_id] = snapshot_entry

        try:
            api_gate.wait()
            ib_app.reqMktData(
                snapshot_req_id, contract, "1,2,4,9,106", True, False, []
            )
            if snapshot_event.wait(timeout=1.5):
                snapshot_completed += 1
        finally:
            ib_app.req_map.pop(snapshot_req_id, None)

        snapshot_quote = snapshot_entry.get("snapshot_chain_leg", {})
        with chain_lock:
            leg_data = chain_data_cache.get(con_id)
            if leg_data is None:
                continue
            mark_before, _, _ = resolve_chain_mark_and_quality(
                bid=leg_data.get("bid"),
                ask=leg_data.get("ask"),
                last=leg_data.get("last") or leg_data.get("delayed_last"),
                model=leg_data.get("modelPrice"),
                close=leg_data.get("close"),
            )
            merge_chain_snapshot_into_leg(leg_data, snapshot_quote)
            mark_after, _, _ = resolve_chain_mark_and_quality(
                bid=leg_data.get("bid"),
                ask=leg_data.get("ask"),
                last=leg_data.get("last") or leg_data.get("delayed_last"),
                model=leg_data.get("modelPrice"),
                close=leg_data.get("close"),
            )
            if mark_before is None and mark_after is not None:
                snapshot_mark_recovered += 1

    with chain_lock:
        coverage_any = 0
        for con_id in selected_con_ids:
            quote = chain_data_cache.get(con_id, {})
            mark, _, _ = resolve_chain_mark_and_quality(
                bid=quote.get("bid"),
                ask=quote.get("ask"),
                last=quote.get("last") or quote.get("delayed_last"),
                model=quote.get("modelPrice"),
                close=quote.get("close"),
            )
            if mark is not None:
                coverage_any += 1

    rows = {}
    coverage_mark = 0
    coverage_bidask = 0
    with chain_lock:
        print(f"Processing {len(chain_data_cache)} items from chain cache...")
        for conId, data in chain_data_cache.items():
            strike = data["strike"]
            if strike not in rows:
                rows[strike] = {"strike": strike, "call": {}, "put": {}}

            mark, mark_source, quote_quality = resolve_chain_mark_and_quality(
                bid=data.get("bid"),
                ask=data.get("ask"),
                last=data.get("last") or data.get("delayed_last"),
                model=data.get("modelPrice"),
                close=data.get("close"),
            )
            if mark is not None:
                coverage_mark += 1
            if (
                finite_positive_or_none(data.get("bid")) is not None
                and finite_positive_or_none(data.get("ask")) is not None
            ):
                coverage_bidask += 1

            entry = {
                "conId": data["conId"],
                "strike": data["strike"],
                "right": data["right"],
                "bid": data.get("bid"),
                "ask": data.get("ask"),
                "mid": mark,
                "mark_source": mark_source,
                "quote_quality": quote_quality,
                "last": data.get("last") or data.get("delayed_last"),
                "close": data.get("close"),
                "model_price": data.get("modelPrice"),
                "iv": data.get("iv"),
                "delta": data.get("delta"),
            }
            if data["right"] == "C":
                rows[strike]["call"] = entry
            else:
                rows[strike]["put"] = entry

    sorted_rows = sorted(rows.values(), key=lambda x: x["strike"])

    final_und_price = finite_positive_or_none(chain_underlying_price)
    if final_und_price is None:
        final_und_price = finite_positive_or_none(spot_price)

    meta = {
        "contracts_total": int(len(contracts_details)),
        "contracts_selected": int(len(selected_con_ids)),
        "coverage_any": int(coverage_any),
        "coverage_mark": int(coverage_mark),
        "coverage_bidask": int(coverage_bidask),
        "coverage_target": int(coverage_target),
        "strike_half_width": int(strike_half_width),
        "timed_out_contract_scan": bool(timed_out),
        "used_contract_cache": bool(used_contract_cache),
        "snapshot_requested": int(snapshot_requested),
        "snapshot_completed": int(snapshot_completed),
        "snapshot_mark_recovered": int(snapshot_mark_recovered),
    }

    print(
        f"Option chain built. Rows: {len(sorted_rows)}, Underlying Price: {final_und_price}, Coverage: {meta}"
    )

    return jsonify({"rows": sorted_rows, "undPrice": final_und_price, "meta": meta})


@app.route("/get_risk_profile", methods=["POST"])
def get_risk_profile():
    try:
        data = request.get_json(silent=True) or {}
        profile_legs = data.get("legs")

        print("\n--- Generating Risk Profile ---")
        print(f"Received {len(profile_legs or [])} legs for profiling.")

        legs_with_details = build_legs_with_details(profile_legs, require_live=True)

        if not legs_with_details:
            return jsonify(
                {
                    "error": "No valid (Live or Snapshot) legs found in portfolio for profiling."
                }
            ), 404

        und_price = resolve_underlying_price(legs_with_details)
        if not und_price:
            print(
                "  Error: Underlying price not available in any profiled leg's greek data or cache."
            )
            return jsonify(
                {"error": "Underlying price not available for profiled legs."}
            ), 404

        print(f"  Using Underlying Price: {und_price:.2f}")

        def _contract_from_leg(leg):
            if leg.get("tws_data"):
                return leg.get("tws_data", {}).get("contract", {})
            return leg

        strikes = [
            safe_float(_contract_from_leg(l).get("strike"), None)
            for l in legs_with_details
            if safe_float(_contract_from_leg(l).get("strike"), None) is not None
        ]
        points_of_interest = [s for s in strikes if s is not None] + [und_price]
        min_point = min(points_of_interest) if points_of_interest else und_price * 0.8
        max_point = max(points_of_interest) if points_of_interest else und_price * 1.2

        if min_point == max_point:
            min_point = und_price * 0.8
            max_point = und_price * 1.2

        price_buffer = (max_point - min_point) * 0.3
        min_buffer = und_price * 0.1
        price_buffer = max(price_buffer, min_buffer)

        lo = max(0, min_point - price_buffer)
        hi = max_point + price_buffer
        price_range = np.linspace(lo, hi, 150).tolist()
        # print(f"  Price Range: {lo:.2f} to {hi:.2f}")

        dte = compute_days_to_expiry(legs_with_details)

        # print(f"  Calculated DTE: {dte} days")

        # print("  Calculating P/L curves...")
        t0_pnl = calculate_pnl_curve(legs_with_details, price_range, days_to_add=0)
        exp_pnl = calculate_expiration_pnl(legs_with_details, price_range)
        greek_curves = {
            "delta": calculate_greek_surface(
                legs_with_details, price_range, [0], "delta"
            )[0],
            "gamma": calculate_greek_surface(
                legs_with_details, price_range, [0], "gamma"
            )[0],
            "vega": calculate_greek_surface(legs_with_details, price_range, [0], "vega")[
                0
            ],
            "theta": calculate_greek_surface(
                legs_with_details, price_range, [0], "theta"
            )[0],
        }

        time_steps = [
            int(round(dte * p)) for p in [0.25, 0.50, 0.75] if int(round(dte * p)) > 0
        ]
        intermediate_curves = {
            f"t{step}_pnl": calculate_pnl_curve(
                legs_with_details, price_range, days_to_add=step
            )
            for step in time_steps
        }
        # print(f"  Intermediate time steps: {time_steps}")

        # print("  Calculating metrics...")
        breakevens = find_breakevens(price_range, exp_pnl)
        finite_exp_pnl = [p for p in exp_pnl if p is not None and math.isfinite(p)]

        net_calls = sum(
            l["qty"]
            for l in legs_with_details
            if str(_contract_from_leg(l).get("right", "")).upper() == "C"
        )
        net_puts = sum(
            l["qty"]
            for l in legs_with_details
            if str(_contract_from_leg(l).get("right", "")).upper() == "P"
        )

        has_unlimited_profit = (net_calls > 0) or (net_puts < 0)
        has_unlimited_loss = (net_calls < 0) or (net_puts > 0)

        max_profit_val = (
            "Unlimited"
            if has_unlimited_profit
            else (round(float(np.max(finite_exp_pnl)), 2) if finite_exp_pnl else 0)
        )
        max_loss_val = (
            "Unlimited"
            if has_unlimited_loss
            else (round(float(np.min(finite_exp_pnl)), 2) if finite_exp_pnl else 0)
        )

        # print(f"  Max Profit: {max_profit_val}, Max Loss: {max_loss_val}, Breakevens: {breakevens}")

        response_data = {
            "price_range": [round(p, 2) for p in price_range],
            "t0_pnl_curve": t0_pnl,
            "exp_pnl_curve": exp_pnl,
            "greek_curves": greek_curves,
            "intermediate_curves": intermediate_curves,
            "metrics": {
                "current_und_price": round(und_price, 2),
                "max_profit": max_profit_val,
                "max_loss": max_loss_val,
                "breakevens_exp": breakevens,
                "days_to_expiry": dte,
                "time_steps": time_steps,
            },
        }
        # print("--- Risk Profile Generation Complete ---")
        return jsonify(response_data)
    except Exception as exc:
        print(f"Error while building risk profile: {exc}")
        traceback.print_exc()
        return jsonify({"error": f"Failed to fetch risk profile: {exc}"}), 500


@app.route("/get_pnl_by_date", methods=["POST"])
def get_pnl_by_date():
    data = request.get_json(silent=True) or {}
    profile_legs = data.get("legs")
    days_to_add = data.get("days_to_add", 0)
    iv_shift = data.get("iv_shift", 0.0)
    price_range_req = data.get("price_range")

    # print(f"\n--- Calculating PnL Curve for T+{days_to_add}, IV Shift: {iv_shift*100:.1f}% ---")

    legs_with_details = build_legs_with_details(profile_legs, require_live=False)

    if not legs_with_details:
        # print("  Error: No valid legs found.")
        return jsonify({"error": "No valid legs found for PnL calculation"}), 404

    und_price = resolve_underlying_price(legs_with_details)
    if not und_price:
        return jsonify({"error": "Underlying price not available"}), 404

    price_range = (
        price_range_req
        if price_range_req
        else np.linspace(und_price * 0.8, und_price * 1.2, 150).tolist()
    )
    # print(f"  Using {len(price_range)} price points.")

    days_to_add_int = int(days_to_add)
    pnl_curve = calculate_pnl_curve(
        legs_with_details, price_range, days_to_add_int, iv_shift
    )
    greek_curves = {
        "delta": calculate_greek_surface(
            legs_with_details,
            price_range,
            [days_to_add_int],
            "delta",
            iv_shift=iv_shift,
        )[0],
        "gamma": calculate_greek_surface(
            legs_with_details,
            price_range,
            [days_to_add_int],
            "gamma",
            iv_shift=iv_shift,
        )[0],
        "vega": calculate_greek_surface(
            legs_with_details, price_range, [days_to_add_int], "vega", iv_shift=iv_shift
        )[0],
        "theta": calculate_greek_surface(
            legs_with_details,
            price_range,
            [days_to_add_int],
            "theta",
            iv_shift=iv_shift,
        )[0],
    }
    # print("--- PnL Curve Calculation Complete ---")
    return jsonify({"pnl_curve": pnl_curve, "greek_curves": greek_curves})


@app.route("/get_risk_table", methods=["POST"])
def get_risk_table():
    data = request.get_json(silent=True) or {}
    profile_legs = data.get("legs")
    requested_steps = data.get("time_steps")
    iv_shift = safe_float(data.get("iv_shift"), 0.0)
    spot = safe_float(data.get("spot"), None)
    columns = int(safe_float(data.get("columns"), 20))
    strike_steps_each_side = int(safe_float(data.get("strike_steps_each_side"), 10))
    strike_step_pct = safe_float(data.get("strike_step_pct"), 0.5)

    legs_with_details = build_legs_with_details(profile_legs, require_live=False)
    if not legs_with_details:
        return jsonify({"error": "No valid legs found for risk table"}), 404

    if not spot:
        spot = resolve_underlying_price(legs_with_details)
    if not spot:
        return jsonify({"error": "Underlying price not available"}), 404

    total_cost_basis = sum(leg.get("costBasis", 0) or 0 for leg in legs_with_details)
    dte = compute_days_to_expiry(legs_with_details)
    steps = normalize_time_steps(
        dte, requested_steps=requested_steps, default_columns=columns
    )

    rows = []
    for step in steps:
        if dte > 0 and step == dte:
            pnl_at_spot = calculate_expiration_pnl(legs_with_details, [spot])[0]
        else:
            pnl_at_spot = calculate_pnl_curve(
                legs_with_details, [spot], days_to_add=step, iv_shift=iv_shift
            )[0]
        greeks = calculate_greeks_at_point(
            legs_with_details, spot, days_to_add=step, iv_shift=iv_shift
        )
        pnl_pct = None
        if abs(total_cost_basis) > 1e-9:
            pnl_pct = (pnl_at_spot / abs(total_cost_basis)) * 100

        rows.append(
            {
                "days": step,
                "dte": max(0, dte - step),
                "is_expiration": bool(dte > 0 and step == dte),
                "spot": round(float(spot), 2),
                "pnl_at_spot": round(float(pnl_at_spot), 2),
                "pnl_pct": round(float(pnl_pct), 2) if pnl_pct is not None else None,
                "delta": greeks["delta"],
                "gamma": greeks["gamma"],
                "vega": greeks["vega"],
                "theta": greeks["theta"],
            }
        )

    matrix_price_axis = build_price_axis_from_spot(
        spot,
        steps_each_side=strike_steps_each_side,
        step_pct=strike_step_pct,
    )
    matrix_pct_axis = [
        round((((price - spot) / spot) * 100.0), 2) if spot else 0.0
        for price in matrix_price_axis
    ]
    atm_row_index = (
        min(
            range(len(matrix_price_axis)),
            key=lambda idx: abs(matrix_price_axis[idx] - spot),
        )
        if matrix_price_axis
        else 0
    )

    pnl_surface = []
    for step in steps:
        if dte > 0 and step == dte:
            pnl_surface.append(
                calculate_expiration_pnl(legs_with_details, matrix_price_axis)
            )
        else:
            pnl_surface.append(
                calculate_pnl_curve(
                    legs_with_details,
                    matrix_price_axis,
                    days_to_add=step,
                    iv_shift=iv_shift,
                )
            )

    delta_surface = calculate_greek_surface(
        legs_with_details, matrix_price_axis, steps, "delta", iv_shift=iv_shift
    )
    gamma_surface = calculate_greek_surface(
        legs_with_details, matrix_price_axis, steps, "gamma", iv_shift=iv_shift
    )
    vega_surface = calculate_greek_surface(
        legs_with_details, matrix_price_axis, steps, "vega", iv_shift=iv_shift
    )
    theta_surface = calculate_greek_surface(
        legs_with_details, matrix_price_axis, steps, "theta", iv_shift=iv_shift
    )
    has_basis = abs(total_cost_basis) > 1e-9
    pnl_pct_surface = [
        [
            round((safe_float(v, 0.0) / abs(total_cost_basis)) * 100.0, 2)
            if has_basis
            else None
            for v in row
        ]
        for row in pnl_surface
    ]

    time_columns = [
        {
            "days": step,
            "dte": max(0, dte - step),
            "label": f"T+{step}",
            "date": (datetime.now() + timedelta(days=step)).strftime("%b %d"),
            "is_expiration": bool(dte > 0 and step == dte),
        }
        for step in steps
    ]

    return jsonify(
        {
            "spot": round(float(spot), 2),
            "cost_basis": round(float(total_cost_basis), 2),
            "days_to_expiry": dte,
            "rows": rows,
            "matrix": {
                "price_axis": matrix_price_axis,
                "price_pct_axis": matrix_pct_axis,
                "atm_row_index": atm_row_index,
                "time_columns": time_columns,
                "metric_surfaces": {
                    "pnl": pnl_surface,
                    "pnl_pct": pnl_pct_surface,
                    "delta": delta_surface,
                    "gamma": gamma_surface,
                    "vega": vega_surface,
                    "theta": theta_surface,
                },
                "metric_options": ["pnl", "pnl_pct", "delta", "gamma", "theta", "vega"],
            },
        }
    )


@app.route("/get_sgpv_sim", methods=["POST"])
def get_sgpv_sim():
    data = request.get_json(silent=True) or {}
    profile_legs = data.get("legs")
    selected_account = str(data.get("selected_account", "All")).strip() or "All"
    requested_steps = data.get("time_steps")
    iv_shift = safe_float(data.get("iv_shift"), 0.0)
    spot = safe_float(data.get("spot"), None)
    net_liq = safe_float(data.get("net_liq"), None)
    columns = int(safe_float(data.get("columns"), 6))
    strike_steps_each_side = int(safe_float(data.get("strike_steps_each_side"), 11))
    strike_step_pct = safe_float(data.get("strike_step_pct"), 5.0)

    legs_with_details = build_legs_with_details(profile_legs, require_live=False)
    if not legs_with_details:
        return jsonify({"error": "No valid legs found for SGPV simulation"}), 404

    if selected_account != "All":
        legs_with_details = [
            leg
            for leg in legs_with_details
            if (
                not leg.get("tws_data")
                or str(leg.get("tws_data", {}).get("account", "")).strip()
                == selected_account
            )
        ]
        if not legs_with_details:
            return jsonify(
                {
                    "error": f"No valid legs found for selected account {selected_account}"
                }
            ), 404

    if not spot:
        spot = resolve_underlying_price(legs_with_details)
    if not spot:
        return jsonify({"error": "Underlying price not available"}), 404

    if net_liq is None or net_liq <= 0:
        net_liq = estimate_net_liq_from_legs(legs_with_details)

    dte = compute_days_to_expiry(legs_with_details)
    steps = normalize_time_steps(
        dte, requested_steps=requested_steps, default_columns=columns
    )
    price_range = build_price_axis_from_spot(
        spot,
        steps_each_side=strike_steps_each_side,
        step_pct=strike_step_pct,
    )

    t0_sgpv_curve = calculate_position_value_curve(
        legs_with_details,
        price_range,
        days_to_add=0,
        iv_shift=iv_shift,
        absolute_qty=True,
    )

    intermediate_curves = {}
    exp_sgpv_curve = t0_sgpv_curve
    for step in steps:
        curve = calculate_position_value_curve(
            legs_with_details,
            price_range,
            days_to_add=step,
            iv_shift=iv_shift,
            absolute_qty=True,
        )
        if dte > 0 and step == dte:
            exp_sgpv_curve = curve
        elif step > 0:
            intermediate_curves[f"t{step}_sgpv"] = curve

    spot_idx = (
        min(
            range(len(price_range)),
            key=lambda idx: abs(price_range[idx] - spot),
        )
        if price_range
        else 0
    )

    warning_ratio = 30.0
    liquidation_ratio = 50.0
    warning_value = warning_ratio * net_liq
    liquidation_value = liquidation_ratio * net_liq
    sgpv_at_spot = safe_float(t0_sgpv_curve[spot_idx], 0.0) if t0_sgpv_curve else 0.0
    ratio_at_spot = (sgpv_at_spot / net_liq) if net_liq else 0.0

    warning_ranges = compute_breach_ranges(
        price_range, t0_sgpv_curve, warning_value, liquidation_value
    )
    liquidation_ranges = compute_breach_ranges(
        price_range, t0_sgpv_curve, liquidation_value
    )

    return jsonify(
        {
            "price_range": price_range,
            "curves": {
                "t0_sgpv_curve": t0_sgpv_curve,
                "exp_sgpv_curve": exp_sgpv_curve,
                "intermediate_curves": intermediate_curves,
            },
            "metrics": {
                "current_und_price": round(float(spot), 2),
                "days_to_expiry": dte,
                "time_steps": steps,
                "selected_account": selected_account,
                "net_liq": round(float(net_liq), 2),
                "sgpv_at_spot": round(float(sgpv_at_spot), 2),
                "ratio_at_spot": round(float(ratio_at_spot), 2),
                "max_sgpv": round(
                    float(max(t0_sgpv_curve) if t0_sgpv_curve else 0.0), 2
                ),
            },
            "thresholds": {
                "open_restriction_ratio": warning_ratio,
                "liquidation_ratio": liquidation_ratio,
                "open_restriction_value": round(float(warning_value), 2),
                "liquidation_value": round(float(liquidation_value), 2),
            },
            "breach_ranges": {
                "warning": warning_ranges,
                "liquidation": liquidation_ranges,
            },
        }
    )


@app.route("/get_account_risk_context", methods=["POST"])
def get_account_risk_context():
    data = request.get_json(silent=True) or {}
    selected_account_raw = str(data.get("selected_account", "All")).strip() or "All"
    requested_legs = data.get("legs")

    portfolio_accounts = get_portfolio_accounts()
    tws_accounts = get_tws_summary_accounts()
    accounts = sorted(set(portfolio_accounts) | set(tws_accounts))
    if selected_account_raw != "All" and selected_account_raw not in accounts:
        return jsonify({"error": f"Unknown account: {selected_account_raw}"}), 400

    selected_account = selected_account_raw
    if selected_account == "All" and not accounts:
        selected_account = "All"

    legs_for_estimate = build_legs_with_details(requested_legs, require_live=False)
    if selected_account != "All":
        legs_for_estimate = [
            leg
            for leg in legs_for_estimate
            if (
                not leg.get("tws_data")
                or str(leg.get("tws_data", {}).get("account", "")).strip()
                == selected_account
            )
        ]

    selected_legs_estimate = (
        estimate_net_liq_from_legs(legs_for_estimate) if legs_for_estimate else None
    )
    account_estimate = estimate_net_liq_for_account(selected_account)

    tws_context = get_tws_account_risk_context(selected_account)
    tws_net_liq = safe_float(tws_context.get("net_liq"), None)
    tws_maintenance = safe_float(tws_context.get("maintenance_margin"), None)

    cp_account = None if selected_account == "All" else selected_account
    cp_context = (
        client_portal_adapter.account_risk_context(cp_account)
        if client_portal_adapter
        else {"enabled": False, "available": False}
    )
    cp_net_liq = safe_float(cp_context.get("net_liq"), None)
    cp_maintenance = safe_float(cp_context.get("maintenance_margin"), None)

    if tws_net_liq is not None and tws_net_liq > 0:
        net_liq = tws_net_liq
        net_liq_source = "tws_account_summary"
    elif cp_net_liq is not None and cp_net_liq > 0:
        net_liq = cp_net_liq
        net_liq_source = "client_portal"
    elif selected_legs_estimate is not None and selected_legs_estimate > 0:
        net_liq = selected_legs_estimate
        net_liq_source = "selected_legs_estimate"
    else:
        net_liq = account_estimate
        net_liq_source = "portfolio_market_value_abs_estimate"

    if tws_maintenance is not None and tws_maintenance > 0:
        maintenance_margin = tws_maintenance
        maintenance_source = "tws_account_summary"
    elif cp_maintenance is not None and cp_maintenance > 0:
        maintenance_margin = cp_maintenance
        maintenance_source = "client_portal"
    else:
        maintenance_margin = None
        maintenance_source = None

    warning_ratio = 30.0
    liquidation_ratio = 50.0

    return jsonify(
        {
            "accounts": accounts,
            "selected_account": selected_account,
            "net_liq": {
                "value": round(float(net_liq), 2),
                "source": net_liq_source,
                "selected_legs_estimate": round(float(selected_legs_estimate), 2)
                if selected_legs_estimate is not None
                else None,
                "account_estimate": round(float(account_estimate), 2),
                "tws_account_summary_value": round(float(tws_net_liq), 2)
                if tws_net_liq is not None
                else None,
                "client_portal_value": round(float(cp_net_liq), 2)
                if cp_net_liq is not None
                else None,
            },
            "maintenance_margin": {
                "value": round(float(maintenance_margin), 2)
                if maintenance_margin is not None
                else None,
                "source": maintenance_source,
                "tws_account_summary_value": round(float(tws_maintenance), 2)
                if tws_maintenance is not None
                else None,
                "client_portal_value": round(float(cp_maintenance), 2)
                if cp_maintenance is not None
                else None,
            },
            "thresholds": {
                "open_restriction_ratio": warning_ratio,
                "liquidation_ratio": liquidation_ratio,
                "open_restriction_value": round(float(net_liq * warning_ratio), 2),
                "liquidation_value": round(float(net_liq * liquidation_ratio), 2),
            },
            "tws_account_summary": {
                "available": bool(tws_context.get("available", False)),
                "age_sec": tws_context.get("age_sec"),
                "accounts": tws_context.get("accounts", []),
            },
            "client_portal": {
                "enabled": bool(cp_context.get("enabled", False)),
                "available": bool(cp_context.get("available", False)),
                "source": cp_context.get("source"),
            },
        }
    )


@app.route("/get_portfolio_risk_digest", methods=["GET"])
def get_portfolio_risk_digest():
    accounts = get_portfolio_accounts()
    selected = request.args.get("account", "All")
    selected_account = str(selected or "All").strip() or "All"
    if selected_account != "All" and selected_account not in accounts:
        return jsonify({"error": f"Unknown account: {selected_account}"}), 400

    tws_context = get_tws_account_risk_context(selected_account)
    net_liq_tws = safe_float(tws_context.get("net_liq"), None)
    maintenance_tws = safe_float(tws_context.get("maintenance_margin"), None)
    sgpv_tws = safe_float(tws_context.get("sgpv"), None)

    net_liq_estimate = estimate_net_liq_for_account(selected_account)
    net_liq = (
        net_liq_tws if net_liq_tws is not None and net_liq_tws > 0 else net_liq_estimate
    )
    net_liq_source = (
        "tws_account_summary"
        if net_liq_tws is not None and net_liq_tws > 0
        else "portfolio_market_value_abs_estimate"
    )

    sgpv_estimate = estimate_sgpv_for_account(selected_account)
    sgpv = sgpv_tws if sgpv_tws is not None and sgpv_tws >= 0 else sgpv_estimate
    sgpv_source = (
        "tws_account_summary"
        if sgpv_tws is not None and sgpv_tws >= 0
        else "portfolio_market_value_abs_estimate"
    )
    ratio = (sgpv / net_liq) if net_liq and net_liq > 0 else 0.0
    warning_ratio = 30.0
    liquidation_ratio = 50.0

    account_rows = []
    all_accounts = sorted(set(accounts) | set(get_tws_summary_accounts()))
    for account in all_accounts:
        account_tws = get_tws_account_risk_context(account)
        account_netliq_tws = safe_float(account_tws.get("net_liq"), None)
        account_netliq_est = estimate_net_liq_for_account(account)
        account_netliq = (
            account_netliq_tws
            if account_netliq_tws is not None and account_netliq_tws > 0
            else account_netliq_est
        )
        account_sgpv_tws = safe_float(account_tws.get("sgpv"), None)
        account_sgpv_est = estimate_sgpv_for_account(account)
        account_sgpv = (
            account_sgpv_tws
            if account_sgpv_tws is not None and account_sgpv_tws >= 0
            else account_sgpv_est
        )
        account_rows.append(
            {
                "account": account,
                "net_liq": round(float(account_netliq), 2),
                "net_liq_source": "tws_account_summary"
                if account_netliq_tws is not None and account_netliq_tws > 0
                else "portfolio_market_value_abs_estimate",
                "sgpv": round(float(account_sgpv), 2),
                "sgpv_source": "tws_account_summary"
                if account_sgpv_tws is not None and account_sgpv_tws >= 0
                else "portfolio_market_value_abs_estimate",
                "ratio": round(float(account_sgpv / account_netliq), 2)
                if account_netliq > 0
                else None,
            }
        )

    return jsonify(
        {
            "selected_account": selected_account,
            "net_liq": {
                "value": round(float(net_liq), 2),
                "source": net_liq_source,
                "tws_value": round(float(net_liq_tws), 2)
                if net_liq_tws is not None
                else None,
                "estimate_value": round(float(net_liq_estimate), 2),
            },
            "sgpv": {
                "value": round(float(sgpv), 2),
                "source": sgpv_source,
                "tws_value": round(float(sgpv_tws), 2) if sgpv_tws is not None else None,
                "estimate_value": round(float(sgpv_estimate), 2),
                "ratio": round(float(ratio), 2),
                "open_restriction_ratio": warning_ratio,
                "liquidation_ratio": liquidation_ratio,
                "open_restriction_value": round(float(net_liq * warning_ratio), 2),
                "liquidation_value": round(float(net_liq * liquidation_ratio), 2),
            },
            "maintenance_margin": {
                "value": round(float(maintenance_tws), 2)
                if maintenance_tws is not None
                else None,
                "source": "tws_account_summary"
                if maintenance_tws is not None
                else None,
            },
            "expiring_soon": build_expiry_alerts(max_days=7, max_rows=12),
            "accounts": account_rows,
            "tws_account_summary": {
                "available": bool(tws_context.get("available", False)),
                "age_sec": tws_context.get("age_sec"),
            },
        }
    )


@app.route("/get_3d_surface", methods=["POST"])
def get_3d_surface():
    data = request.get_json(silent=True) or {}
    profile_legs = data.get("legs")
    surface_type = data.get("surface_type", "pnl")
    iv_shift = data.get("iv_shift", 0.0)

    # print(f"\n--- Generating 3D Surface: {surface_type.upper()} ---")

    legs_with_details = build_legs_with_details(profile_legs, require_live=True)

    if not legs_with_details:
        # print("  Error: No valid live legs found.")
        return jsonify(
            {"error": "No valid live legs found for surface generation"}
        ), 404

    und_price = resolve_underlying_price(legs_with_details)
    if not und_price:
        # print("  Error: Underlying price not available.")
        return jsonify({"error": "Underlying price not available"}), 404

    # print(f"  Using Underlying Price: {und_price:.2f}")

    option_legs = [
        l
        for l in legs_with_details
        if l["tws_data"].get("contract", {}).get("secType") == "OPT"
    ]
    dte = 0
    if option_legs:
        try:
            earliest_expiry_str = min(
                l["tws_data"]["contract"]["expiry"]
                for l in option_legs
                if l["tws_data"]["contract"].get("expiry")
            )
            if earliest_expiry_str:
                earliest_expiry_date = datetime.strptime(earliest_expiry_str, "%Y%m%d")
                dte = max(0, (earliest_expiry_date.date() - datetime.now().date()).days)
        except Exception:
            # print(f"  Error calculating DTE for surface: {e}")
            dte = 30

    # print(f"  Using DTE: {dte} days")

    num_price_steps = 25
    num_time_steps = 25
    price_range = np.linspace(
        und_price * 0.75, und_price * 1.25, num_price_steps
    ).tolist()
    time_range_days = np.linspace(0, dte, num_time_steps).tolist()

    # print(f"  Calculating surface ({num_price_steps} price x {num_time_steps} time points)...")

    if surface_type.lower() == "pnl":
        surface = [
            calculate_pnl_curve(
                legs_with_details, price_range, int(round(days)), iv_shift=iv_shift
            )
            for days in time_range_days
        ]
    elif surface_type.lower() in ["delta", "gamma", "vega", "theta"]:
        surface = calculate_greek_surface(
            legs_with_details,
            price_range,
            time_range_days,
            surface_type.lower(),
            iv_shift=iv_shift,
        )
    else:
        # print(f"  Error: Invalid surface type requested: {surface_type}")
        return jsonify({"error": f"Invalid surface type: {surface_type}"}), 400

    # print("--- 3D Surface Calculation Complete ---")
    return jsonify(
        {
            "price_range": [round(p, 2) for p in price_range],
            "time_range": [int(round(t)) for t in time_range_days],
            "surface": surface,
        }
    )


@app.route("/get_builder_profile", methods=["POST"])
def get_builder_profile():
    try:
        data = request.get_json(silent=True) or {}
        builder_legs = data.get("legs", [])
        S = safe_float(data.get("undPrice"), None)
        iv_shift = safe_float(data.get("ivShift"), 0.0)
        t_plus_days = int(safe_float(data.get("tPlusDays"), 0))
        commission = safe_float(data.get("commission"), 0.0)
        offset = safe_float(data.get("offset"), 0.0)

        if not S or not builder_legs:
            return jsonify({"error": "Missing underlying price or legs"}), 400

        # print(f"\n--- Calculating Builder Profile ---")
        # print(f"UndPrice: {S}, IV Shift: {iv_shift*100:.1f}%, T+{t_plus_days}, Comm: {commission}, Offset: {offset}")

        legs_with_details = []
        total_commission = 0
        total_entry_cost = 0

        today = datetime.now()

        for i, leg in enumerate(builder_legs):
            side_mult = 1 if leg.get("side") == "BUY" else -1
            qty = safe_float(leg.get("qty"), 0.0) * side_mult
            price = safe_float(leg.get("price"), 0.0)

            price_with_offset = price + (offset * side_mult)
            # Entry cost must keep side direction:
            # BUY contributes positive debit, SELL contributes negative credit.
            cost_per_leg = price_with_offset * qty * get_contract_multiplier(leg)
            total_entry_cost += cost_per_leg
            total_commission += abs(qty) * commission

            legs_with_details.append(
                {
                    "qty": qty,
                    "costBasis": 0,
                    "right": leg.get("right", "").upper(),
                    "strike": leg.get("strike"),
                    "expiry": leg.get("expiry"),
                    "iv": leg.get("iv", 0),
                    "multiplier": get_contract_multiplier(leg),
                    "secType": leg.get("secType", "OPT"),
                }
            )
            # print(f"  Leg {i+1}: {leg['side']} {leg['qty']} {leg.get('right','')}@{leg.get('strike')} Exp:{leg.get('expiry')} IV:{leg.get('iv',0):.3f} Price:{price:.2f} OffPrice:{price_with_offset:.2f}")

        aggregate_cost_basis = total_entry_cost + total_commission
        # print(f"  Total Entry Cost (incl. offset): {total_entry_cost:.2f}")
        # print(f"  Total Commission: {total_commission:.2f}")
        # print(f"  Aggregate Cost Basis (incl. comm): {aggregate_cost_basis:.2f}")

        if legs_with_details:
            legs_with_details[0]["costBasis"] = aggregate_cost_basis

        price_range = build_builder_price_axis(S, builder_legs)

        exp_pnl = calculate_expiration_pnl(legs_with_details, price_range)

        t_plus_pnl = calculate_pnl_curve(
            legs_with_details, price_range, days_to_add=t_plus_days, iv_shift=iv_shift
        )

        breakevens = find_breakevens(price_range, exp_pnl)
        finite_exp_pnl = [p for p in exp_pnl if p is not None and math.isfinite(p)]

        net_calls = sum(l["qty"] for l in legs_with_details if l["right"] == "C")
        # For non-negative underlyings, option-side unlimited tails are call-driven:
        # long net calls -> unlimited upside, short net calls -> unlimited upside risk.
        has_unlimited_profit = net_calls > 0
        has_unlimited_loss = net_calls < 0

        max_profit_val = (
            "Unlimited"
            if has_unlimited_profit
            else (round(float(np.max(finite_exp_pnl)), 2) if finite_exp_pnl else 0)
        )
        max_loss_val = (
            "Unlimited"
            if has_unlimited_loss
            else (round(float(np.min(finite_exp_pnl)), 2) if finite_exp_pnl else 0)
        )

        # print(f"  Max Profit: {max_profit_val}, Max Loss: {max_loss_val}, Breakevens: {breakevens}")

        response_data = {
            "priceRange": [round(p, 2) for p in price_range],
            "t0Curve": t_plus_pnl,
            "expCurve": exp_pnl,
            "metrics": {
                "netCost": aggregate_cost_basis,
                "maxProfit": max_profit_val,
                "maxLoss": max_loss_val,
                "breakevens": breakevens,
            },
        }
        # print("--- Builder Profile Calculation Complete ---")
        return jsonify(response_data)

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ Builder profile error:\n{error_trace}")
        return jsonify({"error": str(e), "trace": error_trace}), 500


@app.route("/generate_snapshot", methods=["GET"])
def generate_snapshot():
    try:
        template_path = os.path.join(BASE_DIR, "snapshot_template.html")
        with open(template_path, "r") as f:
            template = f.read()

        with portfolio_lock:
            snapshot_data = []
            for p_dict in portfolio_data.values():
                snapshot_data.append(dict(p_dict))

            for p in snapshot_data:
                p["status"] = "Snapshot"

        combos_data = []
        if os.path.exists(COMBOS_FILE):
            try:
                with open(COMBOS_FILE, "r") as f:
                    raw_combos = json.load(f)
                combos_data, combo_errors, combo_warnings = normalize_combos_payload(
                    raw_combos
                )
                if combo_warnings:
                    print("Snapshot combo warnings:", combo_warnings)
                if combo_errors:
                    print("Snapshot combo normalization errors:", combo_errors)
            except Exception as e:
                print(f"Warning: Could not load combos.json for snapshot: {e}")

        output_html = template.replace("_SNAPSHOT_DATA_", json.dumps(snapshot_data))
        output_html = output_html.replace("_SNAPSHOT_COMBOS_", json.dumps(combos_data))

        filename = (
            f"Portfolio_Snapshot_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.html"
        )
        filepath = os.path.join(BASE_DIR, filename)

        print(f"Generating snapshot file: {filepath}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(output_html)

        return jsonify({"status": "success", "file": filename})

    except Exception as e:
        error_msg = f"Snapshot generation failed: {e}"
        print(error_msg)
        traceback.print_exc()
        return jsonify({"error": error_msg}), 500


def run_ibkr_app():
    global ib_app
    ib_app = IBKRApp()
    try:
        print("Connecting to TWS...")
        ib_app.connect("127.0.0.1", TWS_PORT, clientId=CLIENT_ID)
        time.sleep(2)
        if ib_app.isConnected():
            print("TWS connection successful. Starting API loop.")
            ib_app.run()
            print("TWS API loop finished.")
        else:
            print(
                "❌ TWS connection failed. Please ensure TWS is running and API connections are enabled."
            )

    except ConnectionRefusedError:
        print(
            f"❌ Connection Refused: Could not connect to TWS on 127.0.0.1:{TWS_PORT}. Is TWS running and API enabled?"
        )
    except Exception as e:
        print(f"❌ Unexpected error during TWS connection or run: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    log_startup_diagnostics()

    if "--snapshot" in sys.argv:
        snapshot_file = "portfolio_snapshot.json"
        try:
            snap_idx = sys.argv.index("--snapshot")
            if snap_idx + 1 < len(sys.argv) and not sys.argv[snap_idx + 1].startswith(
                "--"
            ):
                snapshot_file = sys.argv[snap_idx + 1]
        except ValueError:
            pass

        print(f"--- LAUNCHING IN SNAPSHOT (READ-ONLY) MODE from {snapshot_file} ---")
        try:
            if not os.path.exists(snapshot_file):
                raise FileNotFoundError(f"Snapshot file '{snapshot_file}' not found.")

            with open(snapshot_file, "r") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError(
                        "Snapshot file does not contain a valid JSON list."
                    )

                with portfolio_lock:
                    portfolio_data.clear()
                    for pos in data:
                        pos["status"] = "Snapshot"
                        conId = pos.get("conId")
                        if conId:
                            portfolio_data[conId] = pos
                        else:
                            print(
                                "Warning: Skipping position in snapshot missing 'conId'."
                            )

            print(f"--> Loaded {len(portfolio_data)} positions from snapshot.")

        except FileNotFoundError as e:
            print(f"❌ ERROR: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ ERROR: Invalid JSON in snapshot file '{snapshot_file}': {e}")
            sys.exit(1)
        except ValueError as e:
            print(
                f"❌ ERROR: Invalid data format in snapshot file '{snapshot_file}': {e}"
            )
            sys.exit(1)
        except Exception as e:
            print(f"❌ ERROR: Failed to load snapshot '{snapshot_file}': {e}")
            sys.exit(1)

    else:
        print("--- LAUNCHING IN LIVE TRADING MODE ---")
        ibkr_thread = threading.Thread(target=run_ibkr_app, daemon=True)
        ibkr_thread.start()

        time.sleep(3)

        if ib_app and ib_app.isConnected():
            print("Starting background threads...")
            threading.Thread(target=process_request_queue, daemon=True).start()
            threading.Thread(target=auto_refresh_positions, daemon=True).start()
            threading.Thread(target=fallback_watchdog, daemon=True).start()
        else:
            print("IBKR connection failed, background threads not started.")

    use_waitress = False

    if use_waitress and "--snapshot" not in sys.argv:
        try:
            from waitress import serve

            print(
                f"\n--- TWS Dashboard Backend (Waitress) ---\n--> Open http://127.0.0.1:{SERVER_PORT} in browser.\n"
            )
            serve(app, host="0.0.0.0", port=SERVER_PORT)
        except ImportError:
            print("Waitress not installed, falling back to Flask development server.")
            print(
                f"\n--- TWS Dashboard Backend (Flask Dev) ---\n--> Open http://127.0.0.1:{SERVER_PORT} in browser.\n"
            )
            app.run(host="0.0.0.0", port=SERVER_PORT, threaded=True, debug=False)
    else:
        print(
            f"\n--- TWS Dashboard Backend (Flask Dev) ---\n--> Open http://127.0.0.1:{SERVER_PORT} in browser.\n"
        )
        app.run(host="0.0.0.0", port=SERVER_PORT, threaded=True, debug=False)
