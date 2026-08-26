# ETH Trend Monitor — external data source contracts

Production execution is GitHub Actions. Secrets are injected through repository Actions Secrets only.

## Provider precedence

For each ETH-native dimension, data selection is:

1. explicit `ETH_*_API_URL` adapter for that dimension, when configured;
2. credential-free public baseline providers;
3. Dune as optional enrichment for metrics whose semantics are not available from the public baseline.

Enrichment fills missing fields only; it must not overwrite an already available higher-precedence baseline metric. Missing metrics are never replaced by zero. Provider failures and provenance remain explicit.

## Public baseline — Coin Metrics Community

No API key is required. The Community API is used at daily frequency for ETH:

- `CapMVRVCur` → `valuation.mvrv`;
- `FlowInExNtv - FlowOutExNtv` → `capital_flow.exchange_netflow_eth` (deposit-positive / withdrawal-negative);
- raw `FlowInExNtv`, `FlowOutExNtv`, `FlowInExUSD`, `FlowOutExUSD` are retained for audit diagnostics;
- `SplyCur` daily difference → `structural.net_issuance_eth`;
- `SplyExNtv` daily percentage change → `structural.exchange_balance_change_pct`;
- latest `SplyExNtv` is retained as `structural.exchange_balance_eth` for diagnostics;
- `AdrActCnt` → `structural.active_addresses` (descriptive only);
- `FeeTotNtv` → `structural.network_fees_eth` (descriptive only);
- `TxCnt` → `structural.transaction_count` (descriptive only);
- `IssTotNtv` → `structural.gross_issuance_eth` (descriptive only; net supply change remains the scored issuance component).

The network-activity and gross-issuance diagnostic fields are retained as evidence/provenance but do not add separate Structural Supply score votes. In particular, gross issuance must not be counted alongside net issuance as independent evidence.

The provider's source timestamp is preserved as `_observed_at`; it is not replaced by collection time.

## Public baseline — DefiLlama

No API key is required. Ethereum stablecoin circulating supply is used to derive:

- `capital_flow.stablecoin_supply_change_usd`;
- `capital_flow.stablecoin_supply_change_pct`;
- `capital_flow.stablecoin_supply_usd`.

**Semantic boundary:** stablecoin supply change is not the same metric as stablecoin CEX netflow. It must never be written into `stablecoin_flow_usd`.

The legacy macro path may also use DefiLlama ETH TVL. That TVL signal remains separate from ETH-native supply/flow metrics.

## Public enrichment — Farside ETH ETF flows

No API key is required. The published Farside Investors ETH ETF table is read on a best-effort basis and the latest complete dated row's total is mapped as:

- daily table total in US$m → `capital_flow.etf_flow_usd`;
- original US$m value → `capital_flow.etf_flow_musd`;
- table date → `capital_flow.etf_flow_date` and provider `_observed_at`.

This is a public web-table integration rather than a versioned API. The collector first requests Farside directly; if a bot-protected runner receives an HTTP/blocking failure, it may retry the same Farside page through the read-only Jina Reader transport. When that fallback is used, `_source` explicitly says `Farside Investors via Jina Reader`. The collector only accepts rows dated before the current `America/New_York` calendar day, because Farside may expose a same-day placeholder/partial row (including `0.0`) before the US trading day is complete. Parsing failure, markup change, or temporary blocking of both paths is an **optional provider warning**, not a hard Data Health failure when independent Capital Flow data remains available.

## Public baseline — beaconcha.in staking queues

No API key is required. The public Validator Queues page is read directly when possible, with the read-only Jina Reader used as transport when the page blocks automated runners. The collector parses two explicitly labeled queue values:

- `Pending Deposit Value` → `structural.staking_pending_deposit_eth`;
- `Total Withdrawal/Outflow Value` → `structural.staking_withdrawal_outflow_backlog_eth`.

It derives the bounded descriptive proxy:

`staking_queue_imbalance_pct = (pending_deposit - withdrawal_outflow) / (pending_deposit + withdrawal_outflow) * 100`.

This is **pending staking pressure**, not realized staking netflow. In Structural Supply it occupies the staking-evidence slot only when a realized `staking_netflow_eth` is unavailable. A positive value means the pending deposit queue dominates the pending withdrawal/outflow backlog; a negative value means pending outflow dominates. The queue source is independent from Coin Metrics issuance/exchange-balance fields and from DefiLlama stablecoin data.

Markup/transport failure leaves the staking slot missing and does not zero-fill it. The source remains optional for overall Data Health while Coin Metrics structural baseline remains available.

## Free baseline — Etherscan staking counters

The repository already has a free-tier `ETHERSCAN_API_KEY`; no new credential or paid plan is introduced. Etherscan is used only for two cumulative point-in-time counters:

- the Ethereum mainnet Beacon deposit-contract balance at `0x00000000219ab540356cBB839Cbe05303d7705Fa` → `structural.staking_deposit_contract_balance_eth`;
- `stats/ethsupply2.WithdrawnTotal` → `structural.beacon_withdrawn_total_eth`.

`Eth2Staking` from `ethsupply2` is documented as cumulative **staking rewards**, not active staked ETH. It is retained only as a descriptive legacy/reward field and must not be interpreted as an active-stake ratio.

The cumulative counters are persisted in each PIT snapshot. Once an earlier canonical 4h PIT exists approximately 24 hours back, the system derives:

- `staking_deposits_24h_eth = Δ deposit-contract balance`;
- `beacon_withdrawals_24h_eth = Δ WithdrawnTotal`;
- `staking_netflow_eth = staking_deposits_24h_eth - beacon_withdrawals_24h_eth`.

This is intentionally PIT-derived: the first ~24 hours after deployment remain `WAITING_FOR_24H_BASELINE`; missing history is never imputed as zero. Counter regressions fail closed. Dune staking flow, when available, remains optional parallel enrichment and does not overwrite the free baseline.

**Semantic boundary:** this is a liquid-supply structural flow, not a directional price forecast. Positive means more ETH entered validator staking than returned from Beacon withdrawals during the measured window. Predictive use still requires the existing walk-forward/ablation gates.

## Dune — optional enrichment

Environment: `DUNE_API_KEY`.

When the account tier permits programmatic SQL execution, Dune curated tables provide:

- `capital_flow.exchange_netflow_eth` from `cex.flows`;
- `capital_flow.stablecoin_flow_usd` from stablecoin `cex.flows`;
- `structural.staking_netflow_eth` from `staking_ethereum.flows` as an optional parallel/enrichment measurement when the Dune tier permits it.

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


## Forecast Research feature-depth policy (2026-08-25)

The next research priority is **observation depth first, feature depth second, provider breadth last**. The repository therefore does not add a new paid data provider in this change.

### Observation depth

Every 4h PIT snapshot remains the source of truth for what the model actually knew at that time. `system_status.json` now reports a `pit_history_depth` diagnostic with:

- raw 4h PIT count;
- first/last observation and temporal span;
- conservative non-overlap counts for 3D / 7D / 30D;
- explicit `DIAGNOSTIC` / `effective_evidence_confirmed=false` semantics.

These counters are progress telemetry only. They never grant Shadow or Production eligibility.

### Existing derivatives / options promoted to research candidates, not production features

No new derivatives provider is required for the first feature-depth step. Existing PIT payloads already contain useful independent information:

- perpetual `funding_rate`;
- provider-native `open_interest` plus `derivatives_source` provenance;
- Deribit aggregate `put_call_oi_ratio`;
- near-expiry ATM IV;
- near-expiry OTM put-call IV skew proxy;
- near-vs-next ATM IV term structure.

Deribit perpetual/inverse-futures open interest is reported in USD units, while another provider can use different amount semantics. For that reason raw OI level must **not** be treated as one continuous cross-provider numeric series. Any OI change feature must be derived within a consistent provider/unit regime or rejected as unavailable.

These fields are exposed through the PIT research dataset and registered in `external_feature_contracts()`. Registration does not add them to an approved model; incremental value must still be established through purged OOS ablation.

### FRED macro context for 7D / 30D

The enabled FRED path now explicitly records the following daily research candidates:

- `DTWEXBGS` — Nominal Broad U.S. Dollar Index; legacy `dxy` keys are retained for compatibility but the source is not ICE DXY;
- `DGS10` — 10Y nominal Treasury yield;
- `DGS2` — 2Y nominal Treasury yield;
- `DFII10` — 10Y inflation-indexed Treasury real yield;
- derived 10Y minus 2Y curve slope.

For Treasury yields, the research payload stores daily changes in **basis points** in addition to legacy relative-change fields. FRED observation dates are retained when the FRED path is used. The authoritative availability time for the forward-collected research dataset remains the PIT snapshot retrieval time, preventing later-released observations from being backfilled as if they were known earlier.

The runtime contract checks all four FRED series when `FRED_API_KEY` is configured. FRED remains a research/macro dependency with existing fallbacks where available; a missing value is marked missing rather than silently zero-filled.

### Provider-breadth decision

Do not add Glassnode/CryptoQuant-like paid on-chain providers, additional social feeds, or a paid Dune tier merely to increase feature count. A new provider becomes justified only when an ablation result identifies a missing information cluster with plausible incremental value that cannot be reconstructed from existing PIT sources.

The next candidate for a genuinely new information cluster remains exact staking / validator-flow data. It stays research-only and is intentionally deferred until the current feature set has accumulated enough real PIT history to evaluate first.
