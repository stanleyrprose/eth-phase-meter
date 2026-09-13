# ETH Meta Decision Layer v1

## Purpose

The Meta Decision Layer combines two independent evidence systems without merging their statistical claims:

1. `TradingAgents` supplies a machine-readable portfolio judgment (`BUY`, `HOLD`, `SELL`, etc.).
2. `eth-phase-meter` supplies 1h/4h rule direction, data health, momentum, order flow, options positioning, and volatility risk.

The layer produces one deterministic decision-support recommendation:

- `ADD`
- `HOLD`
- `REDUCE`
- `AVOID`

It does **not** create a probability, promote a model, change production forecast state, or place an order.

## Why this is separate from forecasting

`rule_direction`, `TradingAgents` judgment, and evidence alignment are not calibrated probabilities. The existing 3D/7D/30D forecast publication gates remain authoritative and fail closed when production approval is absent.

The Meta Decision Layer is therefore an orchestration layer, not a new forecasting model.

## TradingAgents contract

`TradingAgents/scripts/run_tradingagents.py` emits `tradingagents-decision-v1` JSON after a successful graph run. By default it is written as `decision.json` beside `complete_report.md`; callers can override the path with `--decision-json`.

Required fields used by this layer:

```json
{
  "contract_version": "tradingagents-decision-v1",
  "canonical_symbol": "ETH-USD",
  "analysis_date": "2026-09-13",
  "generated_at": "2026-09-13T01:00:00+00:00",
  "decision": "Hold",
  "decision_normalized": "HOLD",
  "report_path": "/path/to/complete_report.md"
}
```

Unknown decision values fail closed instead of being silently treated as neutral.

## Freshness contract

Both source systems must be fresh. The default maximum artifact age is 24 hours:

- `TradingAgents.generated_at` must be parseable and fresh.
- Phase Meter 1h and 4h `timestamp` values must both be parseable and fresh.

A stale or invalid timestamp produces `AVOID`. The CLI can tighten or relax the window with `--max-source-age-hours`.

## Decision policy

### ADD

Requires all of the following:

- TradingAgents is bullish (`BUY`, `STRONG BUY`, `ADD`, or `ACCUMULATE`).
- 4h direction >= +25.
- 1h direction >= +15.
- 4h momentum >= +20.
- 4h order flow > 0.
- 4h options positioning is not strongly blocking (>= -25).
- both Phase Meter snapshots pass data-health, coverage, and freshness gates.

### REDUCE

Requires all of the following:

- TradingAgents is bearish (`SELL`, `STRONG SELL`, `REDUCE`, or `EXIT`).
- 4h direction <= -20.
- 1h direction <= -10.
- 4h momentum or order flow is non-positive.
- data-health and freshness gates pass.

### AVOID

Fail closed when any material trust/conflict condition is present, including:

- invalid TradingAgents contract;
- unknown TradingAgents decision value;
- asset mismatch;
- stale/invalid TradingAgents or Phase Meter timestamp;
- Phase Meter coverage/data-health failure;
- extreme volatility risk >= 75;
- strong 1h/4h directional conflict;
- TradingAgents and 4h Phase Meter strongly disagree.

### HOLD

Default when evidence is usable but does not meet the full confirmation criteria for `ADD` or `REDUCE`.

This is deliberate: the layer requires confirmation rather than turning a weak single-system signal into an action recommendation.

## CLI

After both source artifacts exist:

```bash
python scripts/run_meta_decision.py \
  --monitor eth_reports/latest_monitor.json \
  --tradingagents /path/to/decision.json \
  --output eth_reports/meta_decision.json
```

Output contract: `eth-meta-decision-v1`.

## Guardrails

The output always declares:

```json
{
  "forecast_probability_generated": false,
  "production_model_state_changed": false,
  "order_execution_allowed": false
}
```

This preserves the repository's research-truth vs production-truth separation and keeps the new layer outside automated capital allocation or order execution.
