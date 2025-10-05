# backend/main.py

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import threading
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime
from py_vollib_vectorized import vectorized_black_scholes
import numpy as np
# backend/main.py

# ... other imports
from config import settings # <-- Import settings

# ...

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ...
    ib_app = IBKRApp()
    app.state.tws_app = ib_app
    # Use settings for connection
    ib_app.connect(settings.TWS_HOST, settings.TWS_PORT, clientId=settings.TWS_CLIENT_ID)
    # ... rest of the file is the same

from sqlmodel import SQLModel, Session, select
from database import engine
# Import the new model
from models import Combo, RiskProfileResponse, find_breakevens, Surface3DResponse

from portfolio_manager import portfolio_manager
from tws_connection import IBKRApp

# ... (The top of the file: lifespan, app setup, router includes, CORS, get_session are all the same) ...
def create_db_and_tables(): SQLModel.metadata.create_all(engine)
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("INFO:     Creating database and tables...")
    create_db_and_tables()
    print("INFO:     Starting TWS connection in background thread...")
    ib_app = IBKRApp()
    app.state.tws_app = ib_app
    ib_app.connect("127.0.0.1", 7496, clientId=1)
    tws_thread = threading.Thread(target=ib_app.run, daemon=True)
    tws_thread.start()
    yield
    print("INFO:     Application shutting down.")
    ib_app.disconnect()
app = FastAPI(lifespan=lifespan)
from options_router import router as options_router
from strategies_router import router as strategies_router
app.include_router(options_router)
app.include_router(strategies_router)
origins = ["*"] 
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"],)
def get_session():
    with Session(engine) as session:
        yield session

# ... (Pydantic models and /combos, /portfolio endpoints are the same) ...
class Pnl(BaseModel): daily: float; unrealized: float
class Position(BaseModel): conId: int; description: str; position: float; avgCost: float; costBasis: float; marketValue: float; pnl: Pnl; greeks: dict; status: str
class ComboWithAnalytics(BaseModel): id: Optional[int]; name: str; createdAt: datetime; dte: int; costBasis: float = 0.0; marketValue: float = 0.0; dailyPnl: float = 0.0; unrealizedPnl: float = 0.0; delta: float = 0.0; gamma: float = 0.0; vega: float = 0.0; theta: float = 0.0; legConIds: List[int]
class ComboCreate(BaseModel): name: str; group: Optional[str] = "Default"; legConIds: List[int]
class RiskProfileRequest(BaseModel): legConIds: List[int]
@app.get("/")
def read_root(): return {"message": "TWS Dashboard Backend is running!"}
@app.get("/portfolio", response_model=List[Position])
def get_portfolio(): return portfolio_manager.get_all_positions()
@app.post("/combos", response_model=Combo)
def create_combo(combo: ComboCreate, session: Session = Depends(get_session)): db_combo = Combo.model_validate(combo); session.add(db_combo); session.commit(); session.refresh(db_combo); return db_combo
@app.get("/combos", response_model=List[ComboWithAnalytics])
def read_combos(session: Session = Depends(get_session)):
    combos_from_db = session.exec(select(Combo)).all()
    live_positions = portfolio_manager.get_all_positions()
    positions_map = {p['conId']: p for p in live_positions}
    results = []
    for db_combo in combos_from_db:
        combo_legs_data = [leg for conId in db_combo.legConIds if (leg := positions_map.get(conId)) is not None]
        exp_dates = [ datetime.strptime(leg.get('description', '').split(' ')[1], "%Y-%m-%d") for leg in combo_legs_data if ' C' in leg.get('description', '') or ' P' in leg.get('description', '') ]
        min_exp_date = min(exp_dates) if exp_dates else datetime.now()
        dte = (min_exp_date - datetime.now()).days
        combo_analytics = ComboWithAnalytics( id=db_combo.id, name=db_combo.name, createdAt=db_combo.createdAt, dte=dte, legConIds=db_combo.legConIds )
        for leg_position in combo_legs_data:
            combo_analytics.costBasis += leg_position.get('costBasis', 0.0)
            combo_analytics.marketValue += leg_position.get('marketValue', 0.0)
            combo_analytics.dailyPnl += leg_position.get('pnl', {}).get('daily', 0.0)
            combo_analytics.unrealizedPnl += leg_position.get('pnl', {}).get('unrealized', 0.0)
            leg_greeks = leg_position.get('greeks', {})
            pos_size = leg_position.get('position', 0)
            multiplier = 100 if ' C' in leg_position.get('description', '') or ' P' in leg_position.get('description', '') else 1
            combo_analytics.delta += leg_greeks.get('delta', 0.0) * pos_size * multiplier
            combo_analytics.gamma += leg_greeks.get('gamma', 0.0) * pos_size * multiplier
            combo_analytics.vega += leg_greeks.get('vega', 0.0) * pos_size * multiplier
            combo_analytics.theta += leg_greeks.get('theta', 0.0) * pos_size * multiplier
        results.append(combo_analytics)
    return results
@app.delete("/combos/{combo_id}")
def delete_combo(combo_id: int, session: Session = Depends(get_session)): combo = session.get(Combo, combo_id); session.delete(combo); session.commit(); return {"ok": True}
RISK_FREE_RATE = 0.05
def calculate_pnl_curve(legs: List[dict], price_range: np.ndarray, days_to_add: int):
    total_pnl = np.zeros_like(price_range)
    today = datetime.now()
    for leg in legs:
        pos = leg.get('position', 0); desc = leg.get('description', ''); cost_basis = leg.get('costBasis', 0.0)
        if ' C' in desc or ' P' in desc:
            parts = desc.split(' '); expiry_str, strike_str, right = parts[1], parts[2], parts[3]
            K = float(strike_str); flag = right.lower()
            expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d")
            T_sim = ((expiry_dt - today).days - days_to_add) / 365.25
            if T_sim > 1e-9:
                iv = leg.get('greeks', {}).get('iv', 0.0)
                if iv <= 0: iv = 0.25 
                option_prices = np.asarray( vectorized_black_scholes(flag, price_range, K, T_sim, RISK_FREE_RATE, iv) )
                leg_pnl = (option_prices.flatten() * pos * 100) - cost_basis
            else:
                if flag == 'c': intrinsic_value = np.maximum(0, price_range - K)
                else: intrinsic_value = np.maximum(0, K - price_range)
                leg_pnl = (intrinsic_value * pos * 100) - cost_basis
            total_pnl += leg_pnl
        else:
            avg_price = leg.get('avgCost', 0)
            leg_pnl = (price_range - avg_price) * pos
            total_pnl += leg_pnl
    return total_pnl.tolist()
@app.post("/combos/risk-profile", response_model=RiskProfileResponse)
def get_risk_profile(request: RiskProfileRequest):
    all_positions = portfolio_manager.get_all_positions()
    position_map = {p['conId']: p for p in all_positions}
    combo_legs = [position_map.get(conId) for conId in request.legConIds if position_map.get(conId) is not None]
    if not combo_legs: raise HTTPException(status_code=404, detail="No valid legs found")
    und_price = next((leg.get('greeks', {}).get('undPrice') for leg in combo_legs if leg.get('greeks', {}).get('undPrice')), None)
    if not und_price:
        pos = combo_legs[0].get('position', 0); und_price = combo_legs[0].get('marketValue', 0) / pos if pos != 0 else 0
    if not und_price: raise HTTPException(status_code=404, detail="Could not determine underlying price")
    price_range = np.linspace(und_price * 0.80, und_price * 1.20, 200)
    exp_dates = [datetime.strptime(leg.get('description', '').split(' ')[1], "%Y-%m-%d") for leg in combo_legs if ' C' in leg.get('description', '') or ' P' in leg.get('description', '')]
    min_exp_date = min(exp_dates) if exp_dates else datetime.now()
    dte = (min_exp_date - datetime.now()).days
    curves = {}
    curve_steps = np.linspace(0, max(0, dte), 5, dtype=int)
    for days_to_add in curve_steps:
        label = f"T+{days_to_add}" if days_to_add < dte else "Expiration"
        curves[label] = calculate_pnl_curve(combo_legs, price_range, int(days_to_add))
    exp_curve = curves.get("Expiration", [])
    breakevens = find_breakevens(price_range, exp_curve)
    return RiskProfileResponse( price_range=price_range.tolist(), curves=curves, breakevens_exp=breakevens, current_und_price=und_price, dte=dte)

# --- NEW 3D SURFACE ENDPOINT ---
@app.post("/combos/3d-surface", response_model=Surface3DResponse)
def get_3d_surface(request: RiskProfileRequest):
    all_positions = portfolio_manager.get_all_positions()
    position_map = {p['conId']: p for p in all_positions}
    
    combo_legs = [position_map.get(conId) for conId in request.legConIds if position_map.get(conId) is not None]

    if not combo_legs:
        raise HTTPException(status_code=404, detail="No valid combo legs found for 3D surface.")

    und_price = next((leg.get('greeks', {}).get('undPrice') for leg in combo_legs if leg.get('greeks', {}).get('undPrice')), None)
    if not und_price:
        pos = combo_legs[0].get('position', 0)
        und_price = combo_legs[0].get('marketValue', 0) / pos if pos != 0 else 0
    if not und_price:
        raise HTTPException(status_code=404, detail="Could not determine underlying price for 3D surface.")

    # 1. Define the two axes for our grid
    price_axis = np.linspace(und_price * 0.75, und_price * 1.25, 40) # X-axis
    
    exp_dates = [datetime.strptime(leg.get('description', '').split(' ')[1], "%Y-%m-%d") for leg in combo_legs if ' C' in leg.get('description', '') or ' P' in leg.get('description', '')]
    min_exp_date = min(exp_dates) if exp_dates else datetime.now()
    current_dte = (min_exp_date - datetime.now()).days
    
    time_axis = np.linspace(max(0, current_dte), 0, 30, dtype=int) # Y-axis (DTE)

    # 2. Calculate P&L for each point on the grid
    pnl_surface = []
    for dte_slice in time_axis:
        days_to_add = current_dte - dte_slice
        pnl_row = calculate_pnl_curve(combo_legs, price_axis, days_to_add)
        pnl_surface.append(pnl_row)

    return Surface3DResponse(
        price_axis=price_axis.tolist(),
        time_axis=time_axis.tolist(),
        pnl_surface=pnl_surface
    )