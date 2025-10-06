// frontend/src/mockData.js

export const mockOptionChain = {
  "undPrice": 550.50,
  "chain": [
    {
      "strike": 548,
      "call": { "contract": { "conId": 1001, "symbol": "SPY", "lastTradeDateOrContractMonth": "20251017", "strike": 548, "right": "C", "multiplier": "100", "exchange": "SMART", "currency": "USD", "localSymbol": "SPY   251017C00548000" }, "data": { "bid": 5.20, "ask": 5.25, "iv": 0.15, "delta": 0.58, "gamma": 0.02, "vega": 0.21, "theta": -0.15, "undPrice": 550.50 } },
      "put": { "contract": { "conId": 1002, "symbol": "SPY", "lastTradeDateOrContractMonth": "20251017", "strike": 548, "right": "P", "multiplier": "100", "exchange": "SMART", "currency": "USD", "localSymbol": "SPY   251017P00548000" }, "data": { "bid": 2.70, "ask": 2.75, "iv": 0.14, "delta": -0.42, "gamma": 0.02, "vega": 0.21, "theta": -0.14, "undPrice": 550.50 } }
    },
    {
      "strike": 550,
      "call": { "contract": { "conId": 1003, "symbol": "SPY", "lastTradeDateOrContractMonth": "20251017", "strike": 550, "right": "C", "multiplier": "100", "exchange": "SMART", "currency": "USD", "localSymbol": "SPY   251017C00550000" }, "data": { "bid": 4.10, "ask": 4.15, "iv": 0.145, "delta": 0.51, "gamma": 0.025, "vega": 0.22, "theta": -0.16, "undPrice": 550.50 } },
      "put": { "contract": { "conId": 1004, "symbol": "SPY", "lastTradeDateOrContractMonth": "20251017", "strike": 550, "right": "P", "multiplier": "100", "exchange": "SMART", "currency": "USD", "localSymbol": "SPY   251017P00550000" }, "data": { "bid": 3.60, "ask": 3.65, "iv": 0.142, "delta": -0.49, "gamma": 0.025, "vega": 0.22, "theta": -0.15, "undPrice": 550.50 } }
    },
    {
      "strike": 552,
      "call": { "contract": { "conId": 1005, "symbol": "SPY", "lastTradeDateOrContractMonth": "20251017", "strike": 552, "right": "C", "multiplier": "100", "exchange": "SMART", "currency": "USD", "localSymbol": "SPY   251017C00552000" }, "data": { "bid": 3.15, "ask": 3.20, "iv": 0.14, "delta": 0.44, "gamma": 0.023, "vega": 0.20, "theta": -0.14, "undPrice": 550.50 } },
      "put": { "contract": { "conId": 1006, "symbol": "SPY", "lastTradeDateOrContractMonth": "20251017", "strike": 552, "right": "P", "multiplier": "100", "exchange": "SMART", "currency": "USD", "localSymbol": "SPY   251017P00552000" }, "data": { "bid": 4.80, "ask": 4.85, "iv": 0.15, "delta": -0.56, "gamma": 0.023, "vega": 0.20, "theta": -0.13, "undPrice": 550.50 } }
    }
  ]
};

// NEW: Mock data for the /options/analytics endpoint
export const mockTickerAnalytics = {
  iv_rank: 45.5,
  iv_percentile: 60.2,
  expiries: [
    { expiry: "20251017", dte: 11, expected_move: 5.50 },
    { expiry: "20251121", dte: 46, expected_move: 11.20 },
    { expiry: "20260116", dte: 102, expected_move: 18.75 }
  ]
};