# Forecast Research Operations

This repository is now in an observation-first operating phase. The goal is to accumulate real point-in-time evidence without allowing workflow retries, feature proliferation, or automation to manufacture statistical confidence.

## Canonical PIT sampling

The scheduled monitor nominal cadence is minute 15 every four hours. Research datasets use at most one canonical PIT observation per nominal 4h bucket:

1. prefer a record whose `github_event` is `schedule`;
2. otherwise use the earliest valid legacy/manual record in that bucket;
3. later workflow retries or manual dispatches in the same bucket are excluded from research samples.

New PIT records preserve `github_event`, workflow/run identifiers, run attempt, and `schedule_nominal_time`. The raw database remains append-only; canonicalization happens at the research dataset boundary so operational evidence is never deleted.

## Research readiness

`Forecast Research Readiness` runs weekly and checks real canonical labeled rows. The minimum software readiness threshold is 144 labeled rows for a horizon, matching the current walk-forward implementation's first usable 120-row train + 24-row OOS block. This is only permission to run a benchmark, not statistical proof.

When no horizon is ready, the workflow records `WAIT_FOR_MORE_PIT` and exits successfully. When one or more horizons become ready, it runs the research benchmark and candidate-eligibility report automatically. It never activates SHADOW or PRODUCTION. Those remain manual reviewed state transitions.

### ETH single-asset sizing research checkpoint

The same weekly workflow also produces `eth_reports/sizing-research/sizing_research.json` directly from the durable PIT store. It does not use `v3_history.csv` as an authoritative evidence source.

The sizing report:

- canonicalizes to one 4h observation per scheduled bucket;
- rejects missing-bucket gaps from one-period sizing comparisons;
- aligns the current PIT rule direction only to the next canonical 4h price;
- computes trailing volatility from prior realized intervals only;
- compares fixed exposure, absolute-conviction sizing, and volatility-targeted conviction sizing on identical rows;
- reports an all-PIT-clean cohort plus a `coverage >= 80` cohort;
- reports conviction monotonicity, moving-block uncertainty, regime slices, and 5/10/20 bps transaction-cost sensitivity.

A default checkpoint of 250 clean 4h intervals only changes the report status from `WAIT_FOR_MORE_PIT_SIZING_EVIDENCE` to `READY_FOR_HUMAN_SIZING_REVIEW`. It is a review cadence threshold, not a statistical or production gate. The report hard-codes all of the following to false:

- automatic sizing promotion;
- automatic SHADOW;
- automatic PRODUCTION;
- paper execution;
- live execution.

A favorable sizing snapshot can therefore trigger human review only; it cannot alter model state or capital allocation.

### Unified research gate snapshot

After forecast readiness and sizing readiness are computed, the weekly workflow writes one monitor-facing artifact:

`eth_reports/research-gates/research-gates.json`

This is the canonical compact status surface for automation and human triage. It includes:

- 3D / 7D / 30D labeled-row counts and research-readiness state;
- effective Production Approval presence per horizon;
- canonical 4h / clean sizing interval counts and human-review checkpoint state;
- latest durable 4h PIT freshness, coverage, data-health status, and workflow provenance;
- one decision status: `OBSERVE_AND_ACCUMULATE`, `FORECAST_RESEARCH_READY`, `HUMAN_SIZING_REVIEW_AVAILABLE`, `PRODUCTION_FORECAST_APPROVAL_PRESENT`, or `ENGINEERING_ATTENTION_REQUIRED`.

The PIT freshness threshold is five hours, matching the Scheduled Monitor watchdog stale threshold. A stale/degraded PIT condition takes priority over research milestones so data-collection failures are repaired before research conclusions are acted on.

The snapshot is strictly observational. It cannot promote a model, activate SHADOW/PRODUCTION, authorize sizing, or enable paper/live execution.


## Meta Action forward-outcome research

The Meta Decision layer now accumulates prospective forward evidence rather than being judged from anecdotal Telegram messages.

For every newly processed 4H monitor run, the Mac bridge freezes one non-secret `meta-action-v1` event containing:

- `ADD`, `HOLD`, `REDUCE`, or `AVOID`;
- evidence alignment and reason codes;
- TradingAgents decision;
- Phase 1H/4H direction, regimes, momentum, order flow, options positioning, and volatility risk;
- entry price plus monitor run id and Git SHA;
- local Telegram delivery status.

The event is dispatched to the `ETH Meta Action Outcomes` GitHub workflow. That workflow applies versioned migrations when BKK PostgreSQL is available, persists the immutable event, and settles due +4H/+12H/+24H/+72H outcomes against exact canonical 1H PIT buckets. Missing future PIT is left unsettled; it is never interpolated.

The report presents action cohorts and three explicitly descriptive reference-alignment views:

- Meta directional: `ADD=+1`, `REDUCE=-1`; `HOLD/AVOID` have no directional aligned return;
- Phase reference: 4H direction >= +20 is +1, <= -20 is -1, otherwise 0;
- TradingAgents reference: BUY-family +1, SELL-family -1, HOLD-family 0.

These are evidence surfaces, not competing models with an automatic winner. There is no auto-retuning, automatic sizing change, model promotion, or execution.

If the Mac cannot deliver the Action-first Telegram message because local Telegram credentials are absent, the same GitHub workflow can deliver that frozen message using the existing GitHub Telegram Secrets. This fallback does not copy secrets to the Mac or place them in the event payload.


## Formal 3D research review

Once 3D reaches the research-readiness threshold, the weekly readiness workflow also runs a formal real-PIT review at:

`eth_reports/forecast-research/3d-formal-review/review.json`

This formal review is distinct from the legacy/lightweight `model_lab` benchmark. It enforces the PRD v2.3 research methodology:

- Purged Walk-Forward with any training label ending at or after the test start removed;
- 4-hour embargo;
- 3D = 18 bars for overlapping-label diagnostics and moving-block bootstrap;
- dynamic baseline selection with 0.5H / 1.0H / 1.5H block-sensitivity;
- candidate Brier Skill relative to the selected dynamic baseline;
- regime conditioning evaluated as incremental paired OOS evidence;
- calibration deferred unless the raw candidate first passes the incremental gate.

A 3D horizon becoming `READY_FOR_RESEARCH` only authorizes this review. It does not imply candidate eligibility, SHADOW activation, Production Approval, sizing approval, or execution.

## Registered feature-group ablation

Existing PIT data now supports research-only group ablation for:

- derivatives: funding + provider-consistent open interest;
- options: put/call OI, ATM IV, IV skew proxy, IV term structure;
- macro rates: Broad USD, 2Y/10Y nominal changes, 10Y real-yield change, 10Y-2Y curve;
- crypto beta: BTC and ETH/BTC relative returns.

Raw open-interest level is not assumed comparable across providers. A mixed provider regime is explicitly reported and non-dominant OI observations are marked missing for the group ablation.

### HMM execution policy

The standalone `HMM Historical Bootstrap` and `HMM Forecast Ablation` workflows remain available for explicit diagnostics, but they no longer run on an independent weekly schedule. HMM work is automatically executed from `Forecast Research Readiness` only after at least one horizon has enough canonical labeled PIT rows to justify a benchmark. This prevents weekly HMM churn while evidence is still structurally insufficient.

## PIT database backup

`PIT Database Backup` creates a daily PostgreSQL custom-format logical backup from `DATABASE_URL` using a pinned PostgreSQL 18 client container (matching the current server major), verifies the archive is readable with the same major `pg_restore --list`, writes a SHA-256 checksum, and uploads the backup as a private GitHub Actions artifact for 90 days. A client/server major mismatch is treated as a hard backup failure, not silently ignored.

This secondary backup does not replace managed-database PITR. If the database provider offers longer retention/PITR, that remains the preferred primary disaster-recovery layer. No database dump is committed to this public repository.

## Operating rule

After this research-operations closure, feature/provider development should normally freeze. Continue collecting real PIT observations and let weekly readiness determine when research is worth rerunning. New paid providers should only be considered if they supply reliable historical immutable PIT or a clearly missing information cluster demonstrated by ablation evidence.
