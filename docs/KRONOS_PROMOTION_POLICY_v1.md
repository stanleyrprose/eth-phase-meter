# Kronos Promotion Policy v1

## Purpose

This policy is preregistered before prospective Kronos PIT evidence matures. Its purpose is to prevent post-hoc tuning and to define what evidence would be required before Kronos can even be considered for production activation.

Kronos remains `SHADOW / RESEARCH_ONLY` until a future explicit human approval. Passing this policy never changes production automatically.

## Primary evaluation horizon

The primary promotion horizon is:

- timeframe: 4h
- forecast horizon: 18 bars = 72 hours
- model: Kronos-small
- production-shadow configuration remains frozen unless a separately preregistered experiment changes it

The 1h / 12h horizon remains diagnostic and secondary.

## Independence rule

All raw PIT forecasts are retained permanently.

Statistical evaluation must use only canonical non-overlapping forecast windows.

For a 72h forecast:

- a later forecast whose source time falls before the previous selected forecast's endpoint is excluded from effective sample statistics;
- it remains in raw PIT for audit purposes;
- raw collection volume must never be presented as independent evidence.

The report therefore distinguishes:

- `raw_matured_n`
- `effective_nonoverlap_n`
- `overlap_discarded_n`

Only `effective_nonoverlap_n` enters promotion gates.

## Promotion gates

All gates must pass simultaneously on the primary 4h / 72h horizon:

1. effective non-overlapping matured observations >= 100;
2. effective Phase/Kronos conflict observations >= 30;
3. Kronos direction hit rate >= 55%;
4. exact two-sided binomial test against 50% has p < 0.05;
5. Spearman Rank IC > 0;
6. Kronos terminal-price MAE is lower than persistence MAE.

Failure of any single gate means:

`eligible = false`

Passing all gates means only:

`eligible = true; requires_human_approval = true`

It does not mean:

`kronos_decision_active = true`

## Why these gates

Direction hit rate alone is insufficient because a model can appear directionally useful while producing poor price-path estimates.

The persistence MAE gate requires Kronos to beat a trivial no-change forecast on terminal price error.

Rank IC requires at least some monotonic relationship between forecast strength and realized return.

The conflict sample gate is important because Kronos is intended to add independent information to Phase Meter. If there are too few genuine disagreements, we cannot evaluate whether Kronos improves decisions when the systems differ.

The binomial significance gate prevents small-sample directional noise from being promoted.

## No probability promotion

Kronos sample directional agreement is not a calibrated market probability.

No value such as "3 of 3 paths down" may be converted into a 3D/7D/30D probability without a separate calibration study and explicit production approval.

## Parameter freeze

Observed OOS results must not be used to repeatedly tune lookback, sampling parameters, temperature, top-p, thresholds, or model size until one configuration appears to pass.

The previously observed lookback-90 result is recorded only as a future preregistered candidate. Current production-shadow lookback remains unchanged.

Any future parameter experiment must:

1. define the candidate before seeing its evaluation outcome;
2. use a holdout or future prospective sample not used to select the candidate;
3. remain research-only until separately reviewed.

## Governance

Engineering implemented != statistically validated != production eligible != production active.

Even if all statistical gates pass, activation requires explicit human approval and a separate PR changing `kronos_decision_active`.

No automated workflow may make that activation on its own.
