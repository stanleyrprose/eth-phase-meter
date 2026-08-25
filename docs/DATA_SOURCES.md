# ETH Trend Monitor — external data source contracts

Production execution is GitHub Actions. Secrets are injected through repository Actions Secrets only.

## Provider precedence

For each ETH-native dimension, data selection is:

1. explicit `ETH_*_API_URL` adapter for that dimension, when configured;
2. credential-free public baseline providers;
3. Dune as optional enrichment for metrics whose semantics are not available from the public baseline.

Missing metrics are never replaced by zero. Provider failures and provenance remain explicit.

## Public baseline — Coin Metrics Community

No API key is required. The Community API is used at daily frequency for ETH:

- `CapMVRVCur` → `valuation.mvrv`;
- `SplyCur` daily difference → `structural.net_issuance_eth`;
- `SplyExNtv` daily percentage change → `structural.exchange_balance_change_pct`;
- latest `SplyExNtv` is retained as `structural.exchange_balance_eth` for diagnostics.

The provider's source timestamp is preserved as `_observed_at`; it is not replaced by collection time.

## Public baseline — DefiLlama

No API key is required. Ethereum stablecoin circulating supply is used to derive:

- `capital_flow.stablecoin_supply_change_usd`;
- `capital_flow.stablecoin_supply_change_pct`;
- `capital_flow.stablecoin_supply_usd`.

**Semantic boundary:** stablecoin supply change is not the same metric as stablecoin CEX netflow. It must never be written into `stablecoin_flow_usd`.

The legacy macro path may also use DefiLlama ETH TVL. That TVL signal remains separate from ETH-native supply/flow metrics.

## Dune — optional enrichment

Environment: `DUNE_API_KEY`.

When the account tier permits programmatic SQL execution, Dune curated tables provide:

- `capital_flow.exchange_netflow_eth` from `cex.flows`;
- `capital_flow.stablecoin_flow_usd` from stablecoin `cex.flows`;
- `structural.staking_netflow_eth` from `staking_ethereum.flows`.

A Dune subscription/API failure is retained under `_provider_errors.dune`. It does **not** invalidate an otherwise available independent public metric in the same dimension. If no independent metric exists, the dimension remains explicitly errored/unavailable.

Dune metrics are enrichment, not substitutes for semantically different DefiLlama or Coin Metrics fields.

## ETH valuation provider — explicit adapter

Environment: `ETH_VALUATION_API_URL`, optional `ETH_VALUATION_API_TOKEN`.

Accepted JSON numeric keys (any subset):

- `mvrv`
- `nupl`
- `price_to_realized`

An explicit adapter overrides the public valuation baseline for this dimension. Missing keys reduce Market State coverage; they are never replaced by zero.

## ETH capital-flow provider — explicit adapter

Environment: `ETH_FLOW_API_URL`, optional `ETH_FLOW_API_TOKEN`.

Accepted numeric keys:

- `etf_flow_usd`
- `exchange_netflow_eth`
- `stablecoin_flow_usd`
- `stablecoin_supply_change_usd`

Positive exchange net inflow is treated as increased exchange-side liquid supply for state description. It is not hard-coded as a future-price prediction rule.

## ETH structural provider — explicit adapter

Environment: `ETH_STRUCTURAL_API_URL`, optional `ETH_STRUCTURAL_API_TOKEN`.

Accepted numeric keys:

- `staking_netflow_eth`
- `net_issuance_eth`
- `exchange_balance_change_pct`
- `l2_bridge_netflow_eth`

These feed Structural Supply state first. Predictive use is allowed only if the walk-forward model ladder shows incremental value.

## Timestamp / freshness contract

External dimensions preserve provider observation time through `_observed_at` and provider identity through `_source`. Data Health evaluates freshness from the provider timestamp where available rather than pretending a daily observation was created at collection time.

Current freshness windows remain defined in `eth_trend_v3/data_health.py` and are intentionally looser for valuation/flow/structural daily data than for candles/derivatives/options.

## Research vs production-feature boundary

The new public baseline improves descriptive Market State and Data Health. It does **not** automatically promote new forecast features.

In particular:

- `stablecoin_supply_change_usd` is descriptive until separately registered/validated as a forecast feature;
- Coin Metrics structural fields do not bypass existing feature contracts or statistical gates;
- candidate promotion remains manual and fail-closed.

## Benchmark → Proxy → Validation → Scale

A self-developed ETH cost-basis/SOPR-like proxy must remain Experimental until benchmark validation passes. `eth_trend_v3.eth_proxy_validation.validate_proxy` implements the first correlation/extreme-zone kill gate. A failed proxy must not be labeled ETH-SOPR.
