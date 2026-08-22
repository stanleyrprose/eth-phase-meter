# HMM Historical Bootstrap

This workflow bootstraps a descriptive ETH 4h regime HMM from public Deribit history without inventing missing open-interest history.

## Bootstrap feature schema

- 4h close-to-close log return
- 48h realized volatility (12 x 4h returns)
- log volume change

Historical OI is intentionally excluded from bootstrap v1 because a sufficiently reliable long-history public source is not guaranteed by the production stack. Missing OI must never be encoded as zero.

## Candidate search

The workflow evaluates 3, 4 and 5-state diagonal Gaussian HMMs with five random seeds per state count. Inputs use train-derived robust z normalization and are clipped to [-5, 5]. Candidate diagnostics include BIC, state occupancy, expected duration, label-invariant seed stability (Adjusted Rand Index), and expanding walk-forward test likelihood.

## Gates

A descriptive candidate must satisfy all of the following:

- minimum state occupancy >= 3%
- minimum expected state duration >= 2 four-hour bars
- median seed stability ARI >= 0.60
- at least two valid walk-forward folds

Passing these gates does **not** promote the model. The bootstrap report always sets `promotion_allowed=false`.

## Promotion policy

A candidate may become a frozen production descriptive HMM only after explicit review. It may enter the 3D/7D/30D forecast feature set only if separate out-of-sample ablation shows an improvement in Brier score/calibration versus the same forecast without HMM regime features.

## Workflow

Run **HMM Historical Bootstrap** manually from GitHub Actions or allow the weekly Sunday schedule to execute. Artifacts are uploaded under `hmm-bootstrap-report` and include `report.json`, `report.md`, and `features.csv`.
