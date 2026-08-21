# ETH Trend Monitor — external data source contracts

Production execution is GitHub Actions. Secrets are injected through repository Actions Secrets only.

## ETH valuation provider

Environment: `ETH_VALUATION_API_URL`, optional `ETH_VALUATION_API_TOKEN`.

Accepted JSON numeric keys (any subset):

- `mvrv`
- `nupl`
- `price_to_realized`

Missing keys reduce Market State coverage; they are never replaced by zero.

## ETH capital-flow provider

Environment: `ETH_FLOW_API_URL`, optional `ETH_FLOW_API_TOKEN`.

Accepted numeric keys:

- `etf_flow_usd`
- `exchange_netflow_eth`
- `stablecoin_flow_usd`

Positive exchange net inflow is treated as increased exchange-side liquid supply for state description. It is not hard-coded as a future-price prediction rule.

## ETH structural provider

Environment: `ETH_STRUCTURAL_API_URL`, optional `ETH_STRUCTURAL_API_TOKEN`.

Accepted numeric keys:

- `staking_netflow_eth`
- `net_issuance_eth`
- `exchange_balance_change_pct`
- `l2_bridge_netflow_eth`

These feed Structural Supply state first. Predictive use is allowed only if the walk-forward model ladder shows incremental value.

## Benchmark → Proxy → Validation → Scale

A self-developed ETH cost-basis/SOPR-like proxy must remain Experimental until benchmark validation passes. `eth_trend_v3.eth_proxy_validation.validate_proxy` implements the first correlation/extreme-zone kill gate. A failed proxy must not be labeled ETH-SOPR.
