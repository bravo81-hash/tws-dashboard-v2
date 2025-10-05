# backend/strategies_router.py

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
import asyncio
from ibapi.contract import Contract

from database import engine
from models import SavedStrategy, StrategyCreate, StrategyTrackedData
from options_router import get_ib_app # Import the dependency from options_router

router = APIRouter(prefix="/strategies", tags=["strategies"])

def get_session():
    with Session(engine) as session:
        yield session

@router.post("/", response_model=SavedStrategy)
def create_strategy(strategy: StrategyCreate, session: Session = Depends(get_session)):
    db_strategy = SavedStrategy.model_validate(strategy)
    session.add(db_strategy)
    session.commit()
    session.refresh(db_strategy)
    return db_strategy

@router.get("/", response_model=List[SavedStrategy])
def read_strategies(ticker: str = None, session: Session = Depends(get_session)):
    query = select(SavedStrategy)
    if ticker:
        query = query.where(SavedStrategy.ticker == ticker.upper())
    strategies = session.exec(query).all()
    return strategies

@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: int, session: Session = Depends(get_session)):
    strategy = session.get(SavedStrategy, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    session.delete(strategy)
    session.commit()
    return {"ok": True, "message": "Strategy deleted successfully"}

# --- NEW: Live Tracking Endpoint ---
@router.post("/{strategy_id}/track", response_model=StrategyTrackedData)
async def track_strategy(strategy_id: int, session: Session = Depends(get_session), ib_app = Depends(get_ib_app)):
    # 1. Fetch the saved strategy from the database
    db_strategy = session.get(SavedStrategy, strategy_id)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # 2. Create tasks to fetch live data for each leg
    tasks = []
    for leg in db_strategy.legs:
        c = leg['contract']
        opt_contract = Contract()
        opt_contract.symbol = c['symbol']
        opt_contract.secType = "OPT"
        opt_contract.currency = c['currency']
        opt_contract.exchange = c['exchange']
        opt_contract.lastTradeDateOrContractMonth = c['lastTradeDateOrContractMonth']
        opt_contract.strike = c['strike']
        opt_contract.right = c['right']
        tasks.append(ib_app.fetch_option_data(opt_contract))

    # 3. Run all TWS requests concurrently
    live_leg_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 4. Aggregate the results
    totals = StrategyTrackedData(bid=0, ask=0, mid=0, delta=0, gamma=0, vega=0, theta=0)
    multiplier = 100

    for i, result in enumerate(live_leg_results):
        if isinstance(result, dict) and 'data' in result:
            leg_data = result['data']
            saved_leg = db_strategy.legs[i]
            quantity = saved_leg['quantity']
            
            # Aggregate prices
            if quantity > 0: # Bought leg, contributes to total ask
                totals.ask += (leg_data.get('ask', 0) or 0) * quantity * multiplier
                totals.bid += (leg_data.get('bid', 0) or 0) * quantity * multiplier
            else: # Sold leg, contributes to total bid
                totals.ask += (leg_data.get('bid', 0) or 0) * quantity * multiplier
                totals.bid += (leg_data.get('ask', 0) or 0) * quantity * multiplier

            # Aggregate greeks
            totals.delta += (leg_data.get('delta', 0) or 0) * quantity * multiplier
            totals.gamma += (leg_data.get('gamma', 0) or 0) * quantity * multiplier
            totals.vega += (leg_data.get('vega', 0) or 0) * quantity * multiplier
            totals.theta += (leg_data.get('theta', 0) or 0) * quantity * multiplier
    
    totals.mid = (totals.bid + totals.ask) / 2

    return totals