# ETH Trend Engine V3

## Runtime constraint

V3 is designed first for GitHub Actions. It is a stateless batch job, not a 24/7 daemon.

Each run performs:

1. restore cached research history;
2. collect one current market snapshot;
3. validate data availability and fallback sources;
4. compute feature families;
5. calculate Direction, Available Bias, Coverage, Crowding, Volatility and Regime;
6. persist JSON snapshot and CSV research history;
7. backfill future 4h/24h returns for older observations when their horizons mature;
8. send Telegram output;
9. upload `eth_reports/` as an Actions artifact;
10. exit.

Do not introduce Redis, ClickHouse, FastAPI or long-lived WebSocket loops into the Actions path unless the deployment model changes.

## Modules

- `eth_trend_v3/collectors.py`: public/API collection with Binance -> Deribit fallback.
- `eth_trend_v3/features.py`: pure feature/factor calculation.
- `eth_trend_v3/quality.py`: missing-data semantics, family coverage and stable 100-point evidence scale.
- `eth_trend_v3/engine.py`: Direction, Crowding, Volatility, Regime and market state.
- `eth_trend_v3/storage.py`: CSV research history and delayed outcome backfill.
- `eth_trend_v3/notify.py`: Telegram presentation only.
- `eth_trend_v3/runner.py`: orchestration for one GitHub Actions run.

## Score semantics

`Final Direction` is the net signed contribution on the complete nominal 100-weight model. Missing factors contribute zero evidence and reduce Coverage; they are not renormalized into false confidence.

`Available Bias` is a diagnostic showing directional bias only among currently available factors.

Neither score is a probability. A later calibration phase will use recorded outcomes to estimate `P(Bull)`, `P(Neutral)` and `P(Bear)`.

## Persistence

`eth_reports/v3_history.csv` is restored/saved with `actions/cache` and included in uploaded artifacts. It records current state plus delayed `future_4h_return` and `future_24h_return` labels as later runs arrive.
