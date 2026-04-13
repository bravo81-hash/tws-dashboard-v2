# Risk Workspace (Unified)

This app now uses a single shared risk workspace for both:

- Existing positions/combo profiles
- Modeled trades staged in Strategy Builder

## Entry Points

- `Custom Combos` -> `Profile`
- `Strategy Builder` -> `Risk` / `Risk Profile`

Both routes open the same `risk-panel` and keep the source tab active.

## Layout

The shared risk workspace is designed as a workstation-style two-column view:

- Left rail
- `Options Chain` card (symbol/expiry-derived, live fetch via `/option_chain`)
- `IV Modeling`
- `Time Modeling`
- `Adjustment Modeling`

- Right workspace
- `Modeled Portfolio Exposure` chart
- Curves/selected-leg overlays
- Greek strips and aggregate row

Additional data views remain available via toolbar tabs:

- `Risk Graph`
- `Risk Table`
- `SGPV Sim`

## Data Handling

Risk-profile APIs now support mixed leg sources:

- Live/snapshot portfolio legs
- Synthetic modeled legs (builder-generated)

If a `conId` leg is present but not live-ready, risk calculations fall back to synthetic leg fields when available.

## Option Chain in Risk Workspace

The left-rail chain panel derives context from profiled legs:

- Picks dominant option symbol from legs
- Uses nearest expiry in scope
- Requests strike window from `/option_chain`

Failures in chain loading do not block chart/risk calculations.
