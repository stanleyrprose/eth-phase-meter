# Kronos OOS Evidence v0.1

## Scope

Research-only evaluation of Kronos-small as a forward-path evidence layer for ETH.

This evidence does **not** change Phase Meter, TradingAgents, Meta Decision, forecast-model promotion, or order execution.

Historical source:

- ETHUSDT Binance spot
- closed 4h candles
- OOS start: 2024-07-01 UTC
- last sampled source timestamp: 2026-09-16 UTC
- forecast horizon: 18 x 4h = 72h
- targets are non-overlapping
- 120 points selected across the full OOS period
- 3 stochastic Kronos paths per point
- Kronos repo SHA: `67b630e67f6a18c9e9be918d9b4337c960db1e9a`
- Apple MPS inference

The OOS boundary is chosen because Kronos documentation/paper states that its pretraining data ends around June 2024. This benchmark therefore avoids knowingly scoring on the stated pretraining period.

## Results

| Metric | Lookback 120 | Lookback 90 |
|---|---:|---:|
| OOS n | 120 | 120 |
| Kronos direction hit rate | 55.83% | 58.33% |
| Momentum direction hit rate | 50.00% | 50.00% |
| Exact two-sided binomial p | 0.2352 | 0.0824 |
| Spearman Rank IC | -0.0161 | +0.0576 |
| Kronos terminal-price MAE | 5.3117% | 5.1826% |
| Persistence terminal-price MAE | 4.9710% | 4.9710% |
| Momentum terminal-price MAE | 5.5027% | 5.5027% |
| Kronos MAE lift vs persistence | -0.3406 pp | -0.2116 pp |

## Interpretation

The evidence is mixed.

Kronos shows some directional signal in this sample:

- 120-bar lookback: 55.8% direction hit rate.
- 90-bar lookback: 58.3% direction hit rate.

However, neither result reaches a conventional 5% significance threshold in the exact two-sided binomial test. The 90-bar sensitivity run is closer (`p=0.082`) but remains insufficient evidence for production promotion.

Price-level forecasting is not better than a persistence baseline in either configuration. Kronos terminal-price MAE remains above persistence MAE. Rank IC is essentially zero for lookback 120 and only weakly positive for lookback 90.

Therefore the current evidence supports:

`Kronos = SHADOW / RESEARCH_ONLY`

It does **not** support:

`kronos_decision_active = true`

and does not support generating calibrated 3D/7D/30D probabilities.

## Why production lookback remains unchanged

The 90-bar sensitivity check performed better on directional hit rate than the current 120-bar production-shadow configuration. The production shadow is intentionally not changed from 120 to 90 based on this same OOS sample.

Changing the parameter after observing the result would introduce selection bias. Lookback 90 is instead recorded as a candidate for a future preregistered holdout/prospective comparison.

## Prospective PIT evidence

Historical OHLCV can evaluate Kronos, persistence, and momentum.

It cannot honestly reconstruct the full historical Phase Meter + TradingAgents state unless contemporaneous PIT records exist. Therefore cross-system questions such as:

- when Phase Meter and Kronos conflict, which one is more often correct?
- does agreement between Phase + Kronos improve outcomes?
- does TradingAgents add incremental information?

must be answered from append-only prospective PIT records, not reconstructed hindsight.

The production pipeline therefore records `kronos_pit.jsonl` and resolves each 12h/72h outcome after maturity.

Research readiness targets are diagnostic only:

- >=100 matured observations per horizon
- >=30 matured Phase/Kronos conflict observations

Meeting those counts does not automatically promote Kronos. Promotion still requires evidence review and explicit approval.

## Current conclusion

Kronos is interesting enough to keep collecting, but current OOS evidence does not prove stable incremental forecasting value.

The correct next action is continued shadow collection and outcome resolution, not tuning the model until it passes.
