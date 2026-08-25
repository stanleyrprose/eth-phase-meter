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
