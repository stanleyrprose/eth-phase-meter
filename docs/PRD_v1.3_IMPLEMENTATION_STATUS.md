# PRD v1.3 implementation status

This repository is being migrated incrementally to the uploaded PRD v1.3 architecture.

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
