# GitHub Actions setup

## Required Secrets

For scheduled Telegram output:

- `TG_BOT_TOKEN`
- `TG_CHAT_ID`

For authoritative PIT history and future probability calibration:

- `DATABASE_URL` — PostgreSQL DSN

For Binance market-data egress from GitHub-hosted runners:

- `BINANCE_EGRESS_SSH_KEY` — dedicated forwarding-only SSH private key for the Bangkok VPS. The matching server key is restricted to `api.binance.com:443` and `fapi.binance.com:443`; it cannot execute shell commands. If the tunnel cannot be established, the monitor continues without `BINANCE_PROXY_URL` and existing provider fallbacks remain active.

Optional existing providers:

- `FRED_API_KEY`
- `FINNHUB_API_KEY`
- `CRYPTOPANIC_API_KEY`
- `ETHERSCAN_API_KEY`

Optional ETH-native state providers:

- `ETH_VALUATION_API_URL`
- `ETH_VALUATION_API_TOKEN`
- `ETH_FLOW_API_URL`
- `ETH_FLOW_API_TOKEN`
- `ETH_STRUCTURAL_API_URL`
- `ETH_STRUCTURAL_API_TOKEN`

## Workflows

- `ci.yml`: compile and complete unit/regression test gate.
- `scheduled-monitor.yml`: production market observation; runs only merged `main` on schedule or manual dispatch.
- `backtest.yml`: manual walk-forward, calibration, ablation and correlation reports.
- `model-validation.yml`: manual candidate eligibility gate; never auto-promotes a model.

If `DATABASE_URL` is absent, the monitor can still run and send state observations, but PIT persistence is `ARTIFACT_ONLY`. Calibrated forecast history must not treat runner-local cache as authoritative state.
