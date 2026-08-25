# PRD v1.3 implementation status — HISTORICAL / SUPERSEDED

This file is a historical migration snapshot and MUST NOT be used as the current implementation status. See `PRD_IMPLEMENTATION_STATUS.md`, `FORECAST_RESEARCH_PRD_v2.3.md`, and `FORECAST_RESEARCH_IMPLEMENTATION_PLAN_v1.0.md`.

## Implemented in this change

- GitHub Repository remains the source of truth.
- GitHub Actions remains the standard execution and verification environment.
- PIT snapshot recorder with raw payload, deterministic payload hash, versions and quality flags.
- Run manifest with Git SHA, Actions run id, workflow name, model/feature/config versions and coverage.
- Explicit persistence mode: `POSTGRES` when `DATABASE_URL` exists, otherwise `ARTIFACT_ONLY` and therefore degraded for calibration purposes.
- Separate CLI entrypoints for monitor, backtest and model validation.
- Dedicated CI / scheduled monitor / backtest / model-validation workflows.
- No calibrated probability is emitted until walk-forward + calibration gates exist.

## Not yet claimed complete

- Full PostgreSQL schema/migrations and PIT replay queries.
- 3D / 7D / 30D probability model.
- Brier score / log loss / calibration curve.
- HMM regime engine.
- Feature cluster / correlation de-duplication.
- Ablation automation.
- ETH structural/on-chain intelligence.

These remain gated phases rather than being represented as completed functionality.
