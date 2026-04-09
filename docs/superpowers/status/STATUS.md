# TWS Dashboard Status

## Current State
- Phase: Strategy builder option-chain reliability + risk workspace polish in progress
- Backend canonical file: `dashboard.py`
- Frontend canonical file: `dashboardClient.js`
- Branch/repo: local repo initialized in this folder

## Completed
- Renamed legacy duplicate filenames to canonical runtime names.
- Added backend health endpoint (`GET /health`).
- Added backend refresh endpoint (`POST /refresh_positions`).
- Fixed request gating lock bug (`RequestGate` now uses a persistent instance lock).
- Added runtime diagnostics (Python compatibility warnings at startup and in `/health`).
- Added combo schema normalization/validation on load/save.
- Unified key cost-basis/multiplier logic through shared helper functions in backend and frontend combo aggregation paths.
- Added snapshot compatibility for both `combo.legs` and legacy `combo.legConIds`.
- Added combo render cache key + delegated table events to reduce heavy rerender/listener churn.
- Updated visual system baseline (new typography tokens, atmospheric background, builder table styling alignment).
- Added runtime standardization files: `.python-version` and `requirements.txt`.
- Added continuity files under `docs/superpowers/`.
- Added portfolio account filter selector and client-side filtering so the positions table can be constrained to a single TWS account.
- Added deterministic backend unit tests for valuation helpers (`tests/test_valuation_helpers.py`).
- Split backend concerns into modules: `runtime.py`, `combo_schema.py`, `valuation.py`, and `routes.py`.
- Refactored key inline frontend HTML builders into smaller render helpers in `dashboardClient.js` (portfolio row renderer + combo summary/detail row builders).
- Added optional Client Portal adapter scaffolding (`client_portal_adapter.py`) and exposed adapter status in `/health`.
- Modernized Risk Profile chart presentation with richer chart shell styling, top/bottom axis context, right-side percent axis, spot band/labels, and floating overlays for curve-at-spot and selected-leg detail.
- Added Risk Table mode in the risk modal with backend `POST /get_risk_table` support and frontend graph/table toggle controls.
- Added cursor chips and compact Greek strip panels (Delta/Gamma/Vega/Theta) for richer intraday-at-a-glance risk context.
- Fixed risk modal elongation by adding hard width/height/overflow guardrails and explicit chart canvas sizing constraints in `dashboard.html`.
- Fixed risk chart ATM/annotation reliability by registering Chart.js plugins and switching the risk chart x-axis to linear coordinates.
- Updated Greek strip layout to stack vertically (Delta, Gamma, Vega, Theta) with fixed strip heights to match the expected risk-ruler style.
- Converted risk from modal popup to a dedicated full-width `Risk Workspace` tab, and wired combo/group profile actions to switch directly into this workspace.
- Added synchronized crosshair behavior between the main risk chart and bottom strip charts, including ATM fallback marker and live value badges.
- Made bottom strip Greeks dynamic with slider changes by extending `POST /get_pnl_by_date` to return shifted Greek curves and rebinding strip series client-side.
- Upgraded Risk Table into a scenario matrix (strike x time grid) with metric selector, dynamic heatmap coloring, ATM row/column highlighting, and configurable range/column depth.
- Added backend matrix payload in `POST /get_risk_table` (`matrix.price_axis`, `matrix.time_columns`, `matrix.metric_surfaces`) while keeping legacy `rows` compatibility.
- Added backend `POST /get_sgpv_sim` and frontend `SGPV Sim` workspace view with configurable NetLiq/columns/range, threshold-zone shading, and multi-horizon SGPV curves.
- Added deterministic backend unit coverage for matrix payload and SGPV short-to-absolute normalization behavior.
- Added backend `POST /get_account_risk_context` so SGPV defaults can be account-aware, returning account list, NetLiq source/value, maintenance margin (when available), and 30x/50x threshold amounts.
- Extended Client Portal adapter with optional account risk-context probing/parsing (`account_risk_context`) to ingest broker-side NetLiq/maintenance values when the local Client Portal API is enabled.
- Added SGPV account selector + context note in the risk workspace; changing account now refreshes risk-context defaults and recomputes SGPV using updated NetLiq.
- Added live TWS account-summary stream ingestion (`reqAccountSummary` callbacks) and wired `/get_account_risk_context` to prioritize TWS NetLiq/maintenance before Client Portal/estimates.
- Added backend `GET /get_portfolio_risk_digest` and frontend digest panel in Portfolio view with SGPV/NetLiq ratio pills, threshold values, and “expiring soon” option alerts (7D window).
- Rebuilt the Strategy Builder workstation around an OptionNetExplorer-style layout (option ladder, trade ticket, staged legs, payoff/greeks panel).
- Hardened option-chain and risk-workspace visual density/scale so fonts, controls, and chart containers remain proportionate when data loads.
- Fixed Strategy Builder pricing math for spread entries: SELL leg credits are now applied with correct sign in aggregate net cost.
- Improved builder breakeven/curve precision by switching to an adaptive dense builder price axis (anchors include spot + strikes).
- Added deterministic regression coverage for builder spread metrics (`tests/test_builder_profile_endpoint.py`) to lock in net cost / max profit / max loss correctness.
- Fixed strategy-builder expiry loading for non-`SPX` symbols by qualifying underlying `conId` for all symbols and retrying secdef with `conId=0` when qualified lookup returns no expiries.
- Added thread-safe request-id allocation (`allocate_req_id` + shared helper) across asynchronous IB requests to avoid request-map collisions/timeouts.
- Corrected index lookup exchanges for expiry qualification (`RUT -> RUSSELL`, `NDX -> NASDAQ`, `XSP -> CBOE`) based on direct IB API probing.
- Fixed index option-chain contract-detail lookup by requesting option contracts on `SMART` exchange (resolves `RUT` chain loading).
- Reordered strategy-builder option ladder columns to strike-centered call/put ordering with volume and open-interest fields aligned to workstation view expectations.
- Added deterministic endpoint regression coverage for expiry lookup behavior and fallback paths (`tests/test_get_expiries_endpoint.py`).

## In Progress
- None.

## Next
- Continue risk workspace visual cleanup (chart readability, matrix annotations, and tighter visual parity with OptionNetExplorer-style workflow expectations).
- Add additional strategy builder validation slices (credit spreads, iron condors, ratio structures) with endpoint regression tests.
- Add optional upcoming-earnings/dividend event feeds into the portfolio risk digest area (with graceful offline fallback).

## Verification Evidence
- `python3 -m py_compile dashboard.py runtime.py combo_schema.py valuation.py routes.py client_portal_adapter.py` passed.
- `node --check dashboardClient.js && node --check strategyBuilder.js` passed.
- `python3 -m unittest discover -s tests -p 'test_*.py'` passed (`45` tests).
- Risk modal layout guardrails now enforce bounded dimensions (`#risk-modal-content`, `.risk-chart-shell`, `#risk-chart-canvas`) to prevent runaway popup growth.
- Risk chart now uses numeric x-series points for robust ATM/breakeven annotation placement and top-axis percentage labels.
- Profile actions now route into the dedicated risk tab (`Risk Workspace`) instead of opening a popup modal.
- Main chart hover now drives strip-panel marker lines and metric values; when hover leaves, marker/value falls back to ATM spot.
- `POST /get_risk_table` now returns a scenario matrix payload and the frontend renders it with dynamic metric heatmap + ATM highlighting.
- `POST /get_sgpv_sim` returns SGPV curves + warning/liquidation breach ranges; frontend renders SGPV chart and shaded threshold zones.
- `POST /get_account_risk_context` returns account-aware NetLiq/threshold defaults and rejects unknown selected accounts.
- `POST /get_account_risk_context` now prefers live TWS account summary values when available.
- `GET /get_portfolio_risk_digest` returns account-level SGPV/NetLiq summary and expiring-soon option alerts.
- `POST /get_builder_profile` now returns correct debit/credit spread entry cost math (SELL credits offset BUY debits instead of inflating cost basis).
- `POST /get_builder_profile` now uses a dense adaptive price range so narrow-spread breakevens are resolved accurately.
- `GET /get_expiries` live checks for `SPX`, `RUT`, `SPY`, `IWM` returned `200` with expiries.
- `GET /option_chain` live checks for `SPX`, `RUT`, `SPY`, `IWM` returned `200` with populated rows at selected expiry.
- Client Portal adapter tests now cover `account_risk_context` parsing path and disabled fallback behavior.
- Flask test client checks:
  - `GET /health` -> `200`
  - `GET /health` includes `client_portal` status payload (disabled by default)
  - `POST /refresh_positions` while disconnected -> `503` (`TWS not connected`)
  - `POST /get_risk_table` stock-only payload -> `200` with deterministic rows/greeks
  - `POST /get_risk_table` stock-only matrix payload -> `200` with deterministic matrix dimensions/values
  - `POST /get_sgpv_sim` short stock leg -> `200` with identical absolute curve as long leg
  - `POST /save_combos` invalid payload -> `400`
- Snapshot schema adapter present and wired for both shapes in `snapshot_template.html` (`combo.legs` and `combo.legConIds`).
- Direct `app.run()` socket bind was blocked in this sandbox (`Operation not permitted`), so endpoint verification used Flask test client.

## Notes
- Runtime target remains Python 3.11 for stable `py_vollib` behavior.
- On Python 3.13+, fallback `NUMBA_DISABLE_JIT=1` is auto-enabled in-process to avoid known import failure.
