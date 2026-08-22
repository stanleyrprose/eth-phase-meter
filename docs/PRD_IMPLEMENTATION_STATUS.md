# PRD v1.3 implementation status

This repository implements the engineering and quantitative framework from the ETH / crypto trend-monitoring PRD v1.3. Statistical claims remain data-gated.

## Implemented

- GitHub Repository as code/config/test/workflow source of truth.
- GitHub Actions reference execution and verification environment.
- PIT recorder with raw payload hash, versions, Git SHA and workflow run ID.
- PostgreSQL JSONB external persistence hook; artifact-only mode explicitly degraded.
- Data-health model: coverage, stale flags, errors, source status.
- Six-dimensional Market State Vector: Trend, Valuation, Capital Flow, Crowding, Structural Supply, Volatility/Risk.
- Feature clustering to prevent MA/MACD/RSI-style duplicated evidence from entering the forecast as separate model layers.
- Normalization utilities: rolling percentile, robust z-score, expanding percentile.
- HMM Regime Engine with deterministic fallback and observation schema: return, realized volatility, volume change, OI change.
- 3D / 7D / 30D forecast framework.
- Historical base-rate → momentum → technical/risk → +regime → +flow → +structural → +valuation model ladder.
- Walk-forward evaluation and time-respecting calibration split.
- Probability calibration using isotonic calibration.
- Brier Score, Log Loss, Accuracy, Precision, Recall, Calibration Error, Base Rate lift.
- Ablation and feature-correlation reporting.
- Kill criteria utilities for HMM complexity and ETH proxy validation.
- Model/feature drift checks.
- Level 1 structural, Level 2 probability-shift, Level 3 risk/data alerts.
- Four-page static Dashboard artifact: Overview, State Explorer, Model Lab, Data Health.
- CI, Scheduled Monitor, Backtest, and Model Validation workflows.
- Candidate model promotion remains manual through PR/review even after statistical gates pass.

## Intentionally gated by real data

The following are implemented but must remain `UNAVAILABLE`, `GATED`, or descriptive until empirical gates pass:

- calibrated 3D/7D/30D production probabilities before enough PIT observations exist;
- HMM participation in prediction before regime ablation proves incremental OOS value;
- ETH-native valuation/flow/structural dimensions until corresponding providers are configured;
- self-developed ETH cost-basis/SOPR-like proxy before benchmark validation;
- automatic candidate-model promotion (prohibited; human-reviewed PR is required).

This is not an incomplete implementation: fail-closed behavior is part of the PRD. The system must not manufacture probability or reliability when evidence is insufficient.
