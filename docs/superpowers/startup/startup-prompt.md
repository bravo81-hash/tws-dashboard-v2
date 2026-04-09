Resume TWS Dashboard modernization from local status files.

1) Read these files first:
- `docs/superpowers/status/STATUS.md`
- `docs/superpowers/status/status.json`
- `docs/superpowers/plans/2026-03-31-tws-dashboard-modernization.md`

2) Validate current baseline before any new edits:
- Use Python 3.11 (`.python-version`) and install deps from `requirements.txt`.
- Run `python3 -m py_compile dashboard.py runtime.py combo_schema.py valuation.py routes.py client_portal_adapter.py`
- Run `node --check dashboardClient.js && node --check strategyBuilder.js`
- Run `python3 -m unittest discover -s tests -p 'test_*.py'`
- Run backend snapshot smoke check and hit `/health`

3) Continue one optimization slice at a time with this order:
- correctness first
- performance second
- UI third

4) Current completed UI/risk slice:
- Dedicated `Risk Workspace` tab now hosts risk analysis (selected combo/group profile actions route here).
- Risk workspace supports `Risk Graph` + `Risk Table` + `SGPV Sim` views.
- Risk graph includes richer overlays, cursor chips, and Greek mini-strip panels.
- Risk chart uses linear x-axis series with explicit plugin registration for ATM/breakeven annotations.
- Greek strips are vertically stacked with fixed strip heights.
- Main chart crosshair/ATM marker syncs into bottom strip markers and live metric values.
- `POST /get_pnl_by_date` now returns Greek curves so strip metrics update with Date/IV slider shifts.
- Risk modal has explicit width/height/overflow guardrails to prevent runaway popup elongation.
- `POST /get_risk_table` now returns both legacy spot rows and matrix payloads (`matrix.price_axis`, `matrix.time_columns`, `matrix.metric_surfaces`) for heatmap/table rendering.
- `POST /get_sgpv_sim` now provides absolute-exposure SGPV curves and warning/liquidation breach ranges.
- `POST /get_account_risk_context` now provides account-aware NetLiq defaults, maintenance margin (if available), threshold values, and account validation for SGPV controls.
- `POST /get_account_risk_context` now prioritizes live TWS account-summary values (NetLiq/maintenance) when available, then falls back to Client Portal/estimates.
- Client Portal adapter now includes optional `account_risk_context` probing/parsing for broker-side NetLiq/maintenance ingestion.
- Added `GET /get_portfolio_risk_digest` + Portfolio UI digest panel (SGPV/NetLiq ratio pills, threshold bands, 7-day expiry alerts).
- Strategy Builder workstation has been rebuilt into an OptionNetExplorer-inspired layout with ladder/ticket/staged-legs/payoff sections.
- Builder spread math fix landed in `POST /get_builder_profile`: SELL credits now offset BUY debits correctly in aggregate entry cost.
- Builder payoff computation now uses a denser adaptive price axis to improve breakeven accuracy for narrow spreads.
- `GET /get_expiries` now supports reliable non-`SPX` loading via underlying qualification + secdef retry with `conId=0` fallback when needed.
- Index qualification mappings are now symbol-specific (`RUT -> RUSSELL`, `NDX -> NASDAQ`, `XSP -> CBOE`) and backed by direct IB API probe evidence.
- `GET /option_chain` now requests option contracts on `SMART`, fixing `RUT` chain contract lookup.
- Strategy-builder ladder column order is now strike-centered with call/put volume and OI columns aligned to the requested workstation flow.
- Backend tests currently total `45`.

5) Next slice target:
- Continue risk workspace visual/detail parity:
  - chart readability and matrix row/column annotation density
  - tighter interaction/visual consistency with the builder workstation style
- Expand strategy-builder regression coverage:
  - credit spread, iron condor, and mixed-width structures
- Optional earnings/dividend event integration into portfolio risk digest panel (graceful offline fallback)

6) Update both status artifacts after each completed slice:
- `docs/superpowers/status/STATUS.md`
- `docs/superpowers/status/status.json`

7) Do not refactor order submission flows beyond critical bug/safety fixes unless explicitly requested.
