# backend/utils.py

from ibapi.contract import Contract
from datetime import datetime

def get_contract_description(contract: Contract) -> str:
    """Generates a human-readable description for an IBKR contract."""
    if contract.secType == "STK":
        return contract.symbol

    if contract.secType == "OPT":
        try:
            # Format the date from 'YYYYMMDD' to 'YYYY-MM-DD'
            expiry_date = datetime.strptime(contract.lastTradeDateOrContractMonth, "%Y%m%d").strftime("%Y-%m-%d")
            right = "C" if contract.right == "C" else "P"
            strike = int(contract.strike)
            return f"{contract.symbol} {expiry_date} {strike} {right}"
        except Exception:
            # Fallback if parsing fails
            return contract.localSymbol

    if contract.secType == "FUT":
        return f"{contract.symbol} {contract.lastTradeDateOrContractMonth}"

    # Fallback for any other contract type
    return contract.localSymbol