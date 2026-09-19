# Kronos Shadow Integration

## Purpose

Kronos is integrated as an independent forward-path model alongside ETH Phase Meter and TradingAgents.

- Phase Meter: current market-state estimator.
- Kronos-small: learned K-line forward-path evidence.
- TradingAgents: qualitative/multi-agent research judgment.
- Meta Decision: deterministic fusion layer.

Kronos is **SHADOW ONLY** in v0.1. It cannot change ADD/HOLD/REDUCE, generate forecast probabilities, change production model state, or place orders.

## Runtime flow

```text
Latest Phase Meter artifact
        |
        v
TradingAgents Trigger Gate
        |
        +---- Kronos shadow refresh (on TA RUN or every <=12h)
        |       |
        |       +-- closed ETHUSDT 1h candles -> next 12 bars
        |       +-- closed ETHUSDT 4h candles -> next 18 bars
        |       +-- Kronos-small / MPS / 3 independent sampled paths
        |       +-- kronos_evidence.json
        |
        +---- TradingAgents RUN/REUSE
                |
                v
            Meta Decision
                |
                +-- production recommendation: existing rules only
                +-- shadow_evidence.kronos_alignment:
                    SUPPORTS / CONFLICTS / MIXED / UNAVAILABLE
```

## Kronos evidence contract

Contract: `kronos-evidence-v1`.

Key fields per horizon:

- `median_terminal_return_pct`
- `terminal_return_std_pct`
- `up_sample_share_pct`
- `sample_directional_agreement_pct`
- `direction_score`
- `lookback`
- `pred_len`

`direction_score` is a bounded research heuristic, not a calibrated probability.
`sample_directional_agreement_pct` is sampling agreement, not the probability of price moving up/down.

## Default configuration

- Model: `NeoQuasar/Kronos-small`
- Codec: `NeoQuasar/Kronos-Tokenizer-base`
- Device: auto-detect; MPS is used on Apple Silicon when available
- 1h lookback: 160 closed bars
- 1h forecast: 12 bars
- 4h lookback: 120 closed bars
- 4h forecast: 18 bars
- Independent paths: 3
- Refresh: whenever TradingAgents trigger is RUN, otherwise at most 12h stale
- Failure policy: fail open; write unusable shadow evidence and continue Phase Meter + TradingAgents

## Production auto-detection

The normal production state directory `~/.eth-meta-pipeline` automatically enables Kronos when this runtime exists:

`~/.openclaw/workspace/tools/eth-meta-runtime/Kronos`

Temporary/test state directories do not auto-enable it. The CLI flag `--enable-kronos` can enable it explicitly.

## Promotion gate

Kronos must remain shadow until a PIT-safe post-2024-07 OOS benchmark demonstrates incremental value relative to:

1. persistence,
2. simple momentum,
3. Phase Meter alone,
4. Phase Meter + TradingAgents.

Promotion requires pre-defined statistical criteria, stability by regime/horizon, and explicit human approval. Only after promotion may Kronos affect the production recommendation.

No sample ratio from Kronos may be published as a 3D/7D/30D forecast probability without a separate calibration and production-approval process.
