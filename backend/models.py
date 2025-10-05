# backend/models.py

from sqlmodel import SQLModel, Field, JSON, Column
from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel
import numpy as np

# --- Database Models ---

class Combo(SQLModel, table=True):
    # ... (unchanged)
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    group: str | None = Field(default="Default")
    legConIds: List[int] = Field(sa_column=Column(JSON))
    createdAt: datetime = Field(default_factory=datetime.utcnow, nullable=False)

class SavedStrategy(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    ticker: str = Field(index=True)
    legs: List[dict] = Field(sa_column=Column(JSON))
    cost_basis: float = Field(default=0.0) # <-- NEW FIELD
    createdAt: datetime = Field(default_factory=datetime.utcnow, nullable=False)


# --- API Models ---
# ... (All Option... and RiskProfile... models are unchanged) ...
class OptionContractData(BaseModel):
    conId: int; symbol: str; lastTradeDateOrContractMonth: str; strike: float; right: str; multiplier: str; exchange: str; currency: str; localSymbol: str
class OptionMarketData(BaseModel):
    bid: Optional[float] = None; ask: Optional[float] = None; iv: Optional[float] = None; delta: Optional[float] = None; gamma: Optional[float] = None; vega: Optional[float] = None; theta: Optional[float] = None; undPrice: Optional[float] = None
class OptionLegData(BaseModel):
    contract: OptionContractData; data: OptionMarketData
class OptionChainRow(BaseModel):
    strike: float; call: Optional[OptionLegData] = None; put: Optional[OptionLegData] = None
class OptionChainResponse(BaseModel):
    chain: List[OptionChainRow]; undPrice: float
class RiskProfileResponse(BaseModel):
    price_range: List[float]; curves: dict; breakevens_exp: List[float]; current_und_price: float; dte: int
class TheoreticalLeg(BaseModel):
    quantity: int; strike: float; right: str; expiry: str; iv: float
class TheoreticalProfileRequest(BaseModel):
    legs: List[TheoreticalLeg]; undPrice: float

class StrategyCreate(BaseModel):
    name: str
    ticker: str
    legs: List[Any]
    cost_basis: float # <-- NEW FIELD
# backend/models.py

# ... (keep all existing models: Combo, SavedStrategy, all API models, etc.) ...

# NEW: Pydantic model for the 3D surface data response
class Surface3DResponse(BaseModel):
    price_axis: List[float]
    time_axis: List[int]
    pnl_surface: List[List[float]] # A 2D array (list of lists) of P&L values

# --- Helper Functions ---
# ... (find_breakevens function is unchanged) ...

# --- Helper Functions ---
def find_breakevens(prices, pnls):
    # ... (unchanged)
    prices = np.array(prices); pnls = np.array(pnls); indices = np.where(np.diff(np.sign(pnls)))[0]; breakevens = []
    for i in indices:
        p1, p2, v1, v2 = prices[i], prices[i+1], pnls[i], pnls[i+1]
        if (v2 - v1) != 0:
            breakeven = p1 - v1 * (p2 - p1) / (v2 - v1)
            breakevens.append(round(float(breakeven), 2))
    return breakevens
# backend/models.py

# ... (keep all existing models: Combo, SavedStrategy, all API models, etc.) ...

# NEW: Pydantic model for the response from the tracking endpoint
class StrategyTrackedData(BaseModel):
    bid: float
    ask: float
    mid: float
    delta: float
    gamma: float
    vega: float
    theta: float

# --- Helper Functions ---
# ... (find_breakevens function is unchanged) ...