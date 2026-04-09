# TWS Interactive Dashboard

Real-time IBKR/TWS portfolio, combo, risk, and strategy-builder workspace.

## Requirements
- Python `3.11` (see `.python-version`)
- Node.js (for JS syntax checks only)
- TWS or IB Gateway with API access enabled

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
### Live mode (connects to TWS on `127.0.0.1:7496`)
```bash
python3 dashboard.py
```

### Snapshot mode (read-only)
```bash
python3 dashboard.py --snapshot portfolio_snapshot.json
```

Open: `http://127.0.0.1:5001`

## Verify
```bash
python3 -m py_compile dashboard.py runtime.py combo_schema.py valuation.py routes.py client_portal_adapter.py
node --check dashboardClient.js && node --check strategyBuilder.js
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Notes
- Strategy Builder spread math and breakeven precision were recently fixed and are covered by `tests/test_builder_profile_endpoint.py`.
- Core continuity docs are in `docs/superpowers/{status,startup,plans}`.
