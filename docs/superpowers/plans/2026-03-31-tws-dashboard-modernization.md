# TWS Dashboard Incremental Modernization Plan

> Goal: modernize one thing at a time while improving stability, correctness, and efficiency before deeper visual polish.

## Phase Order

- [x] Foundation: local git repo + canonical filenames (`dashboard.py`, `dashboardClient.js`)
- [x] Continuity: `docs/superpowers/{plans,status,startup}` handoff artifacts
- [x] Stability baseline: `/refresh_positions`, `/health`, RequestGate lock fix, startup diagnostics
- [x] Snapshot compatibility: support both `combo.legs` and legacy `combo.legConIds`
- [x] Accuracy baseline: shared cost-basis/multiplier helpers; combo schema normalization on load/save
- [x] Performance baseline: combo render cache key + event delegation (reduced unnecessary redraw/listener churn)
- [x] UI modernization baseline: updated design tokens, modern type system, atmospheric background, builder visual alignment

## Public Interface Changes

- Added `GET /health`
- Added `POST /refresh_positions`
- Standardized canonical runtime files:
  - backend entrypoint: `dashboard.py`
  - frontend entrypoint: `dashboardClient.js`
- Standardized combo schema at API boundary:
  - combo: `name`, `group`, `createdAt`, `legs[]`
  - leg: `conId`, `qty`, `status`, `costBasis`, `realizedPnl`, optional `closingPrice`

## Verification Targets

- Runtime: backend starts, `/health` responds, snapshot mode safe
- API: `/refresh_positions` connected/disconnected behavior
- Accuracy: consistent multiplier/cost-basis usage in risk/surface/builder/combo aggregation paths
- Snapshot: legacy and current combo shapes render
- Frontend: module load on canonical filename + combo update loop no longer forces full redraw every poll when state key unchanged

## Next Optimization Loop (post-baseline)

- [x] Add deterministic backend unit tests for valuation helper functions
- [x] Split `dashboard.py` into modules (`runtime`, `combo_schema`, `valuation`, `routes`)
- [x] Replace inline HTML builders in `dashboardClient.js` with smaller render units
- [x] Introduce optional Client Portal API adapter for redundancy and historical fallback
- [x] Upgrade Risk Profile graph UI with richer overlays, axis context, and higher visual fidelity
- [x] Add Risk Table mode (`POST /get_risk_table`) and frontend graph/table risk modal switch
- [x] Add cursor chips and Greek mini-strip panels for richer visual risk diagnostics
- [x] Fix risk modal runaway sizing/elongation with explicit CSS bounds and overflow guardrails
- [x] Fix ATM annotation visibility via linear x-axis risk plotting + plugin registration and stack Greek strips vertically
- [x] Convert risk from popup modal to dedicated full-width Risk Workspace tab for selected combo/group workflows
- [x] Add shared risk crosshair synchronization and ATM fallback markers across main and strip charts
- [x] Update bottom strip metrics dynamically with Date/IV slider shifts via backend Greek-curve response
- [x] Upgrade Risk Table to a scenario matrix grid (time columns x strike rows) with metric heatmap rendering
- [x] Add `SGPV Sim` mode in Risk Workspace with backend simulation endpoint and threshold-zone visualization
- [x] Add account-aware SGPV context endpoint/defaults (`/get_account_risk_context`) and wire Risk Workspace account selector + context note
- [x] Prioritize live TWS account-summary NetLiq/maintenance in account risk context (with CP/estimate fallback chain)
- [x] Add Portfolio risk digest panel + endpoint for SGPV/NetLiq thresholds and near-expiry option alerts
- [x] Rebuild Strategy Builder tab into a workstation layout (option ladder + ticket + staged legs + payoff)
- [x] Tighten option-chain and risk-workspace typography/layout density for stable loaded-state proportions
- [x] Fix spread entry-cost sign logic in `POST /get_builder_profile` (SELL credits correctly reduce net debit)
- [x] Add adaptive/dense builder price axis to improve narrow-spread breakeven precision
- [x] Add deterministic regression coverage for builder spread metrics (`tests/test_builder_profile_endpoint.py`)
- [x] Fix non-`SPX` expiry loading in `GET /get_expiries` (qualify underlying for all symbols + retry secdef with `conId=0` fallback)
- [x] Add thread-safe IB request-id allocation to reduce async request-map collision risk
- [x] Correct index qualification exchange mappings (`RUT -> RUSSELL`, `NDX -> NASDAQ`, `XSP -> CBOE`)
- [x] Fix index option-chain contract detail requests by using `SMART` option exchange
- [x] Reorder builder ladder columns to strike-centered call/put market-depth layout
- [x] Add deterministic expiry-endpoint tests for fallback + index-mapping behavior (`tests/test_get_expiries_endpoint.py`)

## Active Next Slices

- [ ] Risk workspace finishing pass (chart readability polish + matrix annotation clarity)
- [ ] Builder regression expansion (credit spread / condor / asymmetric structures)
- [ ] Optional earnings/dividend feed integration in portfolio digest with graceful fallback
