# backend/options_router.py

import asyncio
from fastapi import APIRouter, HTTPException, Depends
from starlette.requests import Request
from ibapi.contract import Contract
from typing import Dict, List
from datetime import datetime
import numpy as np
from py_vollib_vectorized import vectorized_black_scholes

from models import OptionChainResponse, TheoreticalProfileRequest, RiskProfileResponse, find_breakevens
from config import settings # <-- Import settings

RISK_FREE_RATE = 0.05
router = APIRouter(prefix="/options", tags=["options"])


def get_ib_app(request: Request):
    if not hasattr(request.app.state, 'tws_app'):
        raise HTTPException(status_code=503, detail="TWS connection not available")
    return request.app.state.tws_app

def create_underlying_contract(symbol: str) -> Contract:
    contract = Contract(); symbol = symbol.upper(); contract.symbol = symbol; contract.currency = "USD"
    if symbol in ["SPX", "VIX", "NDX", "RUT"]:
        contract.secType = "IND"; contract.exchange = "CBOE"
    else:
        contract.secType = "STK"; contract.exchange = "SMART"
    return contract

@router.get("/expiries", response_model=Dict)
async def get_expiries(symbol: str, ib_app = Depends(get_ib_app)):
    req_id = ib_app.next_req_id; ib_app.next_req_id += 1
    event = asyncio.Event(); expirations = set()
    original_secDefOptParams = ib_app.securityDefinitionOptionParameter
    original_secDefOptParamsEnd = ib_app.securityDefinitionOptionParameterEnd
    def securityDefinitionOptionParameter(reqId, exchange, underlyingConId, tradingClass, multiplier, exps, strikes):
        if reqId == req_id: expirations.update(exps)
    def securityDefinitionOptionParameterEnd(reqId):
        if reqId == req_id: event.set()
    ib_app.securityDefinitionOptionParameter = securityDefinitionOptionParameter
    ib_app.securityDefinitionOptionParameterEnd = securityDefinitionOptionParameterEnd
    contract = create_underlying_contract(symbol)
    try:
        underlying_details = await asyncio.wait_for(ib_app.resolve_contract(req_id, contract), timeout=10)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not find contract for {symbol}: {e}")
    ib_app.reqSecDefOptParams(req_id, underlying_details.symbol, "", underlying_details.secType, underlying_details.conId)
    try:
        await asyncio.wait_for(event.wait(), timeout=20)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timed out fetching expirations")
    finally:
        ib_app.securityDefinitionOptionParameter = original_secDefOptParams
        ib_app.securityDefinitionOptionParameterEnd = original_secDefOptParamsEnd
    return {"symbol": symbol, "expiries": sorted(list(expirations))}

@router.get("/chain", response_model=OptionChainResponse)
async def get_option_chain(symbol: str, expiry: str, ib_app = Depends(get_ib_app)):
    req_id_start = ib_app.next_req_id; ib_app.next_req_id += 1
    contract = create_underlying_contract(symbol)
    try:
        underlying_details = await asyncio.wait_for(ib_app.resolve_contract(req_id_start, contract), timeout=10)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not find contract for symbol: {e}")
    req_id_params = ib_app.next_req_id; ib_app.next_req_id += 1
    event_params = asyncio.Event(); strikes = set()
    original_secDefOptParams = ib_app.securityDefinitionOptionParameter; original_secDefOptParamsEnd = ib_app.securityDefinitionOptionParameterEnd
    def securityDefinitionOptionParameter(reqId, exchange, underlyingConId, tradingClass, multiplier, exps, s):
        if reqId == req_id_params: strikes.update(s)
    def securityDefinitionOptionParameterEnd(reqId):
        if reqId == req_id_params: event_params.set()
    ib_app.securityDefinitionOptionParameter = securityDefinitionOptionParameter; ib_app.securityDefinitionOptionParameterEnd = securityDefinitionOptionParameterEnd
    ib_app.reqSecDefOptParams(req_id_params, underlying_details.symbol, "", underlying_details.secType, underlying_details.conId)
    try:
        await asyncio.wait_for(event_params.wait(), timeout=20)
    finally:
        ib_app.securityDefinitionOptionParameter = original_secDefOptParams; ib_app.securityDefinitionOptionParameterEnd = original_secDefOptParamsEnd
    und_price = ib_app.und_price_cache.get(symbol.upper(), 0)
    if und_price == 0:
        raise HTTPException(status_code=404, detail=f"Underlying price for {symbol} not available yet.")
    sorted_strikes = sorted(list(strikes)); atm_index = min(range(len(sorted_strikes)), key=lambda i: abs(sorted_strikes[i] - und_price));
    start_index = max(0, atm_index - 15); end_index = min(len(sorted_strikes), atm_index + 16);
    filtered_strikes = sorted_strikes[start_index:end_index]
    tasks = []
    for strike in filtered_strikes:
        for right in ["C", "P"]:
            opt_contract = Contract(); opt_contract.symbol = symbol.upper(); opt_contract.secType = "OPT"; opt_contract.currency = "USD";
            opt_contract.exchange = "SMART"; opt_contract.lastTradeDateOrContractMonth = expiry;
            opt_contract.strike = strike; opt_contract.right = right;
            if symbol.upper() in ["SPX", "VIX"]: opt_contract.exchange = "CBOE"
            tasks.append(ib_app.fetch_option_data(opt_contract))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    chain_dict = {s: {'strike': s, 'call': None, 'put': None} for s in filtered_strikes}
    for res in results:
        if isinstance(res, dict) and 'contract' in res:
            contract_obj = res['contract']
            if contract_obj.strike in chain_dict:
                contract_data = { "conId": contract_obj.conId, "symbol": contract_obj.symbol, "lastTradeDateOrContractMonth": contract_obj.lastTradeDateOrContractMonth, "strike": contract_obj.strike, "right": contract_obj.right, "multiplier": contract_obj.multiplier, "exchange": contract_obj.exchange, "currency": contract_obj.currency, "localSymbol": contract_obj.localSymbol, }
                market_data = res.get('data', {})
                full_leg_data = { "contract": contract_data, "data": market_data }
                target_key = 'call' if contract_obj.right == 'C' else 'put'
                chain_dict[contract_obj.strike][target_key] = full_leg_data
    return {"chain": list(chain_dict.values()), "undPrice": und_price}


def calculate_theoretical_pnl_curve(legs: List[dict], price_range: np.ndarray, days_to_add: int):
    total_pnl = np.zeros_like(price_range)
    today = datetime.now()
    
    for leg in legs:
        K = leg['strike']
        T_sim = ((datetime.strptime(leg['expiry'], "%Y%m%d") - today).days - days_to_add) / 365.25
        iv = leg['iv'] if leg['iv'] > 0 else 0.20
        
        current_option_price_arr = vectorized_black_scholes(leg['right'].lower(), np.array([leg['undPrice']]), K, T_sim, RISK_FREE_RATE, iv)
        current_option_price = float(current_option_price_arr.iloc[0])

        if T_sim > 1e-9:
            option_prices_at_range = vectorized_black_scholes(leg['right'].lower(), price_range, K, T_sim, RISK_FREE_RATE, iv)
            # --- THIS IS THE FIX ---
            # Flatten the result to ensure it is a 1D array before calculation
            leg_pnl_series = (option_prices_at_range - current_option_price) * leg['quantity'] * 100
            leg_pnl = leg_pnl_series.to_numpy().flatten()
        else:
            if leg['right'].lower() == 'c': intrinsic_value = np.maximum(0, price_range - K)
            else: intrinsic_value = np.maximum(0, K - price_range)
            leg_pnl = (intrinsic_value - current_option_price) * leg['quantity'] * 100
        
        total_pnl += leg_pnl

    return total_pnl.tolist()


@router.post("/calculate-profile", response_model=RiskProfileResponse)
async def get_theoretical_risk_profile(request: TheoreticalProfileRequest):
    if not request.legs:
        raise HTTPException(status_code=400, detail="No legs provided for profile calculation")

    und_price = request.undPrice
    price_range = np.linspace(und_price * 0.80, und_price * 1.20, 200)

    exp_dates = [datetime.strptime(leg.expiry, "%Y%m%d") for leg in request.legs]
    min_exp_date = min(exp_dates) if exp_dates else datetime.now()
    dte = (min_exp_date - datetime.now()).days

    legs_with_und_price = [leg.model_dump() for leg in request.legs]
    for leg in legs_with_und_price:
        leg['undPrice'] = und_price

    curves = {}
    curve_steps = np.linspace(0, max(0, dte), 5, dtype=int)
    
    for days_to_add in curve_steps:
        label = f"T+{days_to_add}" if days_to_add < dte else "Expiration"
        curves[label] = calculate_theoretical_pnl_curve(legs_with_und_price, price_range, int(days_to_add))
    
    exp_curve = curves.get("Expiration", [])
    breakevens = find_breakevens(price_range, exp_curve) if exp_curve else []

    return RiskProfileResponse(
        price_range=price_range.tolist(),
        curves=curves,
        breakevens_exp=breakevens,
        current_und_price=und_price,
        dte=dte
    )