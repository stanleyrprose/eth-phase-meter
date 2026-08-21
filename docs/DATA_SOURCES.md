# PRD v1.3 Data Source Contracts

Production code runs in GitHub Actions. Secrets and endpoint URLs are injected only through GitHub Secrets.

## Core sources

- Price candles: Binance first, Deribit fallback.
- Options: Deribit.
- Fear & Greed: existing Alternative.me collector.
- Macro: existing FRED/yfinance/DefiLlama collectors.

## Optional ETH-native providers

The PRD requires Valuation, Capital Flow, and Structural Supply dimensions. These are provider-neutral adapters so the repository is not locked to Glassnode/Dune/Nansen.

### `ETH_VALUATION_API_URL`
Expected JSON keys when available: `mvrv`, `nupl`, `price_to_realized`.

### `ETH_FLOW_API_URL`
Expected keys: `etf_flow_usd`, `exchange_netflow_eth`, `stablecoin_flow_usd`.

### `ETH_STRUCTURAL_API_URL`
Expected keys: `staking_netflow_eth`, `net_issuance_eth`, `exchange_balance_change_pct`, `l2_bridge_netflow_eth`.

Optional bearer tokens use the corresponding `*_API_TOKEN` secrets.

Missing providers remain N/A and reduce dimension/model coverage. The system never converts missing structural data to zero.

## ETH Cost Basis / SOPR policy

The repository implements the PRD's Benchmark → Proxy → Validation → Scale gate. A self-developed proxy must not be named ETH-SOPR until benchmark correlation, turning/extreme-zone behavior, and walk-forward incremental value pass validation.
