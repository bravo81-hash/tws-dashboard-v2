# backend/options_router.py

import asyncio
from fastapi import APIRouter, HTTPException, Depends
from starlette.requests import Request
from ibapi.contract import Contract
from typing import Dict, List
from datetime import datetime
import numpy as np
from py_vollib_vectorized import vectorized_black_scholes
import math

from models import (OptionChainResponse, TheoreticalProfileRequest, 
                    RiskProfileResponse, find_breakevens, 
                    TickerAnalyticsResponse, ExpiryAnalytics)
from config import settings

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

@router.get("/analytics", response_model=TickerAnalyticsResponse)
async def get_ticker_analytics(symbol: str, ib_app = Depends(get_ib_app)):
    await asyncio.sleep(2)
    und_contract = create_underlying_contract(symbol)
    try:
        und_contract = await ib_app.resolve_contract(und_contract)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not find contract for {symbol}: {e}")

    hist_vol_task = ib_app.fetch_historical_volatility(und_contract)
    
    req_id_exp = ib_app.next_req_id; ib_app.next_req_id += 1
    exp_event = asyncio.Event(); expirations = set()
    original_secDefOptParams = ib_app.securityDefinitionOptionParameter; original_secDefOptParamsEnd = ib_app.securityDefinitionOptionParameterEnd
    def secDefOptParams(reqId, exchange, underlyingConId, tradingClass, multiplier, exps, strikes):
        if reqId == req_id_exp: expirations.update(exps)
    def secDefOptParamsEnd(reqId):
        if reqId == req_id_exp: exp_event.set()
    ib_app.securityDefinitionOptionParameter = secDefOptParams; ib_app.securityDefinitionOptionParameterEnd = secDefOptParamsEnd
    ib_app.reqSecDefOptParams(req_id_exp, und_contract.symbol, "", und_contract.secType, und_contract.conId)
    
    try:
        hist_vols, _ = await asyncio.gather(hist_vol_task, asyncio.wait_for(exp_event.wait(), timeout=20))
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timed out fetching initial analytics data from TWS")
    finally:
        ib_app.securityDefinitionOptionParameter = original_secDefOptParams; ib_app.securityDefinitionOptionParameterEnd = original_secDefOptParamsEnd

    sorted_expiries = sorted(list(expirations))
    if not sorted_expiries:
        raise HTTPException(status_code=404, detail=f"No options found for {symbol}")

    und_price = ib_app.und_price_cache.get(symbol.upper())
    if not und_price:
        raise HTTPException(status_code=404, detail=f"Underlying price for {symbol} not available in cache.")

    all_strikes_req_id = ib_app.next_req_id; ib_app.next_req_id += 1
    strikes_event = asyncio.Event(); all_strikes = set()
    def strikes_secDefOptParams(reqId, exchange, underlyingConId, tradingClass, multiplier, exps, strikes):
        if reqId == all_strikes_req_id: all_strikes.update(strikes)
    def strikes_secDefOptParamsEnd(reqId):
        if reqId == all_strikes_req_id: strikes_event.set()
    ib_app.securityDefinitionOptionParameter = strikes_secDefOptParams; ib_app.securityDefinitionOptionParameterEnd = strikes_secDefOptParamsEnd
    ib_app.reqSecDefOptParams(all_strikes_req_id, und_contract.symbol, "", und_contract.secType, und_contract.conId)
    await asyncio.wait_for(strikes_event.wait(), timeout=20)
    ib_app.securityDefinitionOptionParameter = original_secDefOptParams; ib_app.securityDefinitionOptionParameterEnd = original_secDefOptParamsEnd
    
    if not all_strikes:
        raise HTTPException(status_code=404, detail=f"Could not retrieve strikes for {symbol}")
    
    atm_strike = min(all_strikes, key=lambda s: abs(s - und_price))

    # --- THIS IS THE FIX ---
    # Expanded the list comprehension into a full loop to create contracts correctly
    atm_iv_tasks = []
    for expiry in sorted_expiries:
        opt_contract = Contract()
        opt_contract.symbol = und_contract.symbol
        opt_contract.secType = "OPT"
        opt_contract.currency = "USD"
        opt_contract.exchange = "SMART" if symbol.upper() not in ["SPX", "VIX"] else "CBOE"
        opt_contract.lastTradeDateOrContractMonth = expiry
        opt_contract.strike = atm_strike
        opt_contract.right = "C"
        atm_iv_tasks.append(ib_app.fetch_option_data(opt_contract))
    
    atm_iv_results = await asyncio.gather(*atm_iv_tasks)

    current_iv = next((res.get('data', {}).get('iv') for res in atm_iv_results if res.get('data', {}).get('iv')), 0)
    
    iv_rank = 0; iv_percentile = 0
    if hist_vols and current_iv > 0:
        iv_low_52wk = min(hist_vols); iv_high_52wk = max(hist_vols)
        if iv_high_52wk > iv_low_52wk:
            iv_rank = (current_iv - iv_low_52wk) / (iv_high_52wk - iv_low_52wk) * 100
        days_lower = sum(1 for v in hist_vols if v < current_iv)
        iv_percentile = (days_lower / len(hist_vols)) * 100

    expiries_analytics = []
    today = datetime.now()
    for i, expiry in enumerate(sorted_expiries):
        dte = (datetime.strptime(expiry, "%Y%m%d") - today).days
        atm_iv = atm_iv_results[i].get('data', {}).get('iv') if i < len(atm_iv_results) else 0
        expected_move = und_price * (atm_iv or 0) * math.sqrt(max(0, dte) / 365)
        expiries_analytics.append(ExpiryAnalytics(expiry=expiry, dte=dte, expected_move=expected_move))
        
    return TickerAnalyticsResponse(iv_rank=iv_rank, iv_percentile=iv_percentile, expiries=expiries_analytics)


@router.get("/chain", response_model=OptionChainResponse)
async def get_option_chain(symbol: str, expiry: str, ib_app = Depends(get_ib_app)):
    try:
        underlying_details = await ib_app.resolve_contract(create_underlying_contract(symbol))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not find contract for symbol: {e}")

    req_id_params = ib_app.next_req_id; ib_app.next_req_id += 1; event_params = asyncio.Event(); strikes = set(); original_secDefOptParams = ib_app.securityDefinitionOptionParameter; original_secDefOptParamsEnd = ib_app.securityDefinitionOptionParameterEnd
    def securityDefinitionOptionParameter(reqId, exchange, underlyingConId, tradingClass, multiplier, exps, s):
        if reqId == req_id_params: strikes.update(s)
    def securityDefinitionOptionParameterEnd(reqId):
        if reqId == req_id_params: event_params.set()
    ib_app.securityDefinitionOptionParameter = securityDefinitionOptionParameter; ib_app.securityDefinitionOptionParameterEnd = securityDefinitionOptionParameterEnd
    ib_app.reqSecDefOptParams(req_id_params, underlying_details.symbol, "", underlying_details.secType, underlying_details.conId)
    try: await asyncio.wait_for(event_params.wait(), timeout=20)
    finally: ib_app.securityDefinitionOptionParameter = original_secDefOptParams; ib_app.securityDefinitionOptionParameterEnd = original_secDefOptParamsEnd
    und_price = ib_app.und_price_cache.get(symbol.upper(), 0)
    if und_price == 0: raise HTTPException(status_code=404, detail=f"Underlying price for {symbol} not available yet.")
    sorted_strikes = sorted(list(strikes)); atm_index = min(range(len(sorted_strikes)), key=lambda i: abs(sorted_strikes[i] - und_price)); start_index = max(0, atm_index - 15); end_index = min(len(sorted_strikes), atm_index + 16); filtered_strikes = sorted_strikes[start_index:end_index]
    
    # --- THIS IS THE SECOND FIX ---
    tasks = []
    for strike in filtered_strikes:
        for right in ["C", "P"]:
            opt_contract = Contract()
            opt_contract.symbol = symbol.upper()
            opt_contract.secType = "OPT"
            opt_contract.currency = "USD"
            opt_contract.exchange = "SMART" if symbol.upper() not in ["SPX", "VIX"] else "CBOE"
            opt_contract.lastTradeDateOrContractMonth = expiry
            opt_contract.strike = strike
            opt_contract.right = right
            tasks.append(ib_app.fetch_option_data(opt_contract))

    results = await asyncio.gather(*tasks)
    chain_dict = {s: {'strike': s, 'call': None, 'put': None} for s in filtered_strikes}
    for res in results:
        if isinstance(res, dict) and 'contract' in res:
            contract_obj = res['contract']
            if contract_obj and contract_obj.strike in chain_dict:
                contract_data = { "conId": contract_obj.conId, "symbol": contract_obj.symbol, "lastTradeDateOrContractMonth": contract_obj.lastTradeDateOrContractMonth, "strike": contract_obj.strike, "right": contract_obj.right, "multiplier": contract_obj.multiplier, "exchange": contract_obj.exchange, "currency": contract_obj.currency, "localSymbol": contract_obj.localSymbol, }; market_data = res.get('data', {}); full_leg_data = { "contract": contract_data, "data": market_data }; target_key = 'call' if contract_obj.right == 'C' else 'put'; chain_dict[contract_obj.strike][target_key] = full_leg_data
    return {"chain": list(chain_dict.values()), "undPrice": und_price}

def calculate_theoretical_pnl_curve(legs: List[dict], price_range: np.ndarray, days_to_add: int):
    total_pnl = np.zeros_like(price_range); today = datetime.now()
    for leg in legs:
        K = leg['strike']; T_sim = ((datetime.strptime(leg['expiry'], "%Y%m%d") - today).days - days_to_add) / 365.25; iv = leg.get('iv') if leg.get('iv') and leg['iv'] > 0 else 0.20
        if T_sim <= 1e-9:
            if leg['right'].lower() == 'c': intrinsic_value = np.maximum(0, price_range - K)
            else: intrinsic_value = np.maximum(0, K - price_range)
            leg_pnl = intrinsic_value * leg['quantity'] * 100
        else:
            option_prices_at_range = vectorized_black_scholes(leg['right'].lower(), price_range, K, T_sim, settings.RISK_FREE_RATE, iv)
            leg_pnl = option_prices_at_range * leg['quantity'] * 100
        total_pnl += leg_pnl.values if hasattr(leg_pnl, 'values') else leg_pnl
    cleaned_pnl = np.nan_to_num(total_pnl, nan=None, posinf=None, neginf=None)
    return cleaned_pnl.tolist()

@router.post("/calculate-profile", response_model=RiskProfileResponse)
async def get_theoretical_risk_profile(request: TheoreticalProfileRequest):
    if not request.legs: raise HTTPException(status_code=400, detail="No legs provided for profile calculation")
    und_price = request.undPrice; price_range = np.linspace(und_price * 0.80, und_price * 1.20, 200)
    exp_dates = [datetime.strptime(leg.expiry, "%Y%m%d") for leg in request.legs]; min_exp_date = min(exp_dates) if exp_dates else datetime.now(); dte = (min_exp_date - datetime.now()).days
    legs_with_und_price = [leg.model_dump() for leg in request.legs]
    for leg in legs_with_und_price: leg['undPrice'] = und_price
    curves = {}; curve_steps = np.linspace(0, max(0, dte), 5, dtype=int)
    for days_to_add in curve_steps:
        label = f"T+{days_to_add}" if days_to_add < dte else "Expiration"
        curves[label] = calculate_theoretical_pnl_curve(legs_with_und_price, price_range, int(days_to_add))
    exp_curve = curves.get("Expiration", []); breakevens = find_breakevens(price_range, exp_curve) if exp_curve else []
    return RiskProfileResponse(price_range=price_range.tolist(), curves=curves, breakevens_exp=breakevens, current_und_price=und_price, dte=dte)