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

- **Left rail** (`295–335px`)
  - `Options Chain` card (symbol/expiry-derived, live fetch via `/option_chain`)
  - `IV Modeling`
  - `Time Modeling` — per-curve date rows (not a single slider); appears after chart loads
  - `Adjustment Modeling` — BASE/ADD compare table at cursor price

- **Right workspace**
  - `Modeled Portfolio Exposure` chart (`clamp(440px, 62vh, 800px)` tall)
  - `Selected Legs` overlay — absolute-positioned top-right corner of the chart; visible on all screens ≥769px wide
  - Greek strips (P&L, Delta, Theta, Vega) — full-width sparklines with meta overlay
  - Aggregate row (hidden when fewer than 2 combos selected)
  - Position strip (Portfolio / Stats tabs)

Additional data views remain available via toolbar tabs:

- `Risk Graph`
- `Risk Table`
- `SGPV Sim`

## Overlay Panels

Only the **Selected Legs** overlay (`#risk-legs-panel`) remains — it sits absolute top-right on the chart canvas and does not reduce chart height.

The former **Curves @ Spot** overlay (`#risk-curve-panel`) was removed; identical values are already shown in the interactive tooltip.

## Theme

The app uses a neutral dark charcoal theme throughout:
- `--bg-primary: #0d1117` / `--bg-secondary: #13191f` / `--bg-tertiary: #1a2130`
- Body background-image gradients are near-invisible (4–5% opacity)
- Risk curve colors: T+0 coral `#f87171`, T+1 amber `#fbbf24`, T+2 emerald `#34d399`, T+3 sky `#60a5fa`

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
