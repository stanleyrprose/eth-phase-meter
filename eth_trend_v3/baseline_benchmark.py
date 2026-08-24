from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .hmm_bootstrap import fetch_deribit_4h_history, build_bootstrap_features

HORIZONS = {"3d": 18, "7d": 42, "30d": 180}
BASE_FEATURES = ["log_return_24h", "realized_volatility", "log_volume_change"]
MIN_TRAIN = 1000
TEST_SIZE = 120


def _calibration_bins(y, p, bins: int = 5):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < (hi if hi < 1 else hi + 1e-9))
        if mask.any():
            out.append({
                "lo": float(lo), "hi": float(hi), "n": int(mask.sum()),
                "predicted": float(p[mask].mean()), "actual": float(y[mask].mean()),
            })
    return out


def _metrics(y, p):
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    bins = _calibration_bins(y, p)
    n = sum(b["n"] for b in bins)
    cal = float(sum(b["n"] * abs(b["predicted"] - b["actual"]) for b in bins) / n) if n else None
    return {
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(p) + (1-y) * np.log(1-p))),
        "calibration_error": cal,
        "oos_n": int(len(y)),
        "calibration": bins,
    }


def _fit_raw_logistic(X_train, y_train, X_test):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    if len(np.unique(y_train)) < 2:
        return None
    scaler = StandardScaler().fit(X_train)
    model = LogisticRegression(max_iter=1000, C=0.5).fit(scaler.transform(X_train), y_train)
    return model.predict_proba(scaler.transform(X_test))[:, 1]


def _split_fit_calibration(X_train, y_train):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    n = len(y_train)
    cal_n = max(80, int(n * 0.2))
    fit_end = n - cal_n
    if fit_end < 300 or len(np.unique(y_train[:fit_end])) < 2 or len(np.unique(y_train[fit_end:])) < 2:
        return None
    scaler = StandardScaler().fit(X_train[:fit_end])
    model = LogisticRegression(max_iter=1000, C=0.5).fit(scaler.transform(X_train[:fit_end]), y_train[:fit_end])
    raw_cal = model.predict_proba(scaler.transform(X_train[fit_end:]))[:, 1]
    return scaler, model, raw_cal, y_train[fit_end:]


def _fit_platt(X_train, y_train, X_test):
    from sklearn.linear_model import LogisticRegression
    fit = _split_fit_calibration(X_train, y_train)
    if fit is None:
        return None
    scaler, model, raw_cal, y_cal = fit
    eps = 1e-6
    logits = np.log(np.clip(raw_cal, eps, 1-eps) / np.clip(1-raw_cal, eps, 1-eps)).reshape(-1, 1)
    calibrator = LogisticRegression(max_iter=1000, C=1.0).fit(logits, y_cal)
    raw_test = model.predict_proba(scaler.transform(X_test))[:, 1]
    test_logits = np.log(np.clip(raw_test, eps, 1-eps) / np.clip(1-raw_test, eps, 1-eps)).reshape(-1, 1)
    return calibrator.predict_proba(test_logits)[:, 1]


def _fit_isotonic(X_train, y_train, X_test):
    from sklearn.isotonic import IsotonicRegression
    fit = _split_fit_calibration(X_train, y_train)
    if fit is None:
        return None
    scaler, model, raw_cal, y_cal = fit
    iso = IsotonicRegression(out_of_bounds="clip").fit(raw_cal, y_cal)
    raw_test = model.predict_proba(scaler.transform(X_test))[:, 1]
    return iso.predict(raw_test)


def _fit_momentum(X_train, y_train, X_test):
    return _fit_raw_logistic(X_train[:, [0]], y_train, X_test[:, [0]])


def run_benchmark(features: pd.DataFrame, min_train: int = MIN_TRAIN, test_size: int = TEST_SIZE) -> dict:
    df = features.copy().reset_index(drop=True)
    synthetic_log_price = np.cumsum(df["log_return"].to_numpy(dtype=float))
    methods = ["base_rate", "momentum_24h", "logistic_raw", "logistic_platt", "logistic_isotonic"]
    store = {h: {m: [] for m in methods} | {"actual": [], "folds": []} for h in HORIZONS}

    train_end = min_train
    while train_end + 1 < len(df):
        test_end = min(len(df), train_end + test_size)
        for horizon, steps in HORIZONS.items():
            train_idx = np.arange(0, max(0, train_end - steps))
            test_idx = np.arange(train_end, min(test_end, len(df) - steps))
            if len(train_idx) < 400 or len(test_idx) == 0:
                continue
            y_train = (synthetic_log_price[train_idx + steps] > synthetic_log_price[train_idx]).astype(int)
            y_test = (synthetic_log_price[test_idx + steps] > synthetic_log_price[test_idx]).astype(int)
            X_train = df[BASE_FEATURES].iloc[train_idx].to_numpy(dtype=float)
            X_test = df[BASE_FEATURES].iloc[test_idx].to_numpy(dtype=float)

            preds = {
                "base_rate": np.full(len(test_idx), np.clip(y_train.mean(), 1e-6, 1-1e-6)),
                "momentum_24h": _fit_momentum(X_train, y_train, X_test),
                "logistic_raw": _fit_raw_logistic(X_train, y_train, X_test),
                "logistic_platt": _fit_platt(X_train, y_train, X_test),
                "logistic_isotonic": _fit_isotonic(X_train, y_train, X_test),
            }
            if any(v is None for v in preds.values()):
                continue
            for m, p in preds.items():
                store[horizon][m].extend(np.asarray(p).tolist())
            store[horizon]["actual"].extend(y_test.tolist())
            fold_metrics = {m: float(np.mean((np.asarray(p)-y_test)**2)) for m, p in preds.items()}
            store[horizon]["folds"].append({"train_end": int(train_end), "n": int(len(y_test)), "brier": fold_metrics})
        train_end += test_size

    report = {
        "schema_version": "forecast-baseline-benchmark-v1",
        "method": "Expanding OOS; train-only calibration; no production changes.",
        "features": BASE_FEATURES,
        "horizons": {},
        "production_change_allowed": False,
    }
    for horizon, vals in store.items():
        y = vals["actual"]
        if not y:
            report["horizons"][horizon] = {"available": False, "reason": "NO_VALID_OOS_PREDICTIONS"}
            continue
        metrics = {m: _metrics(y, vals[m]) for m in methods}
        base_brier = metrics["base_rate"]["brier"]
        ranking = sorted(methods, key=lambda m: metrics[m]["brier"])
        for m in methods:
            metrics[m]["brier_lift_vs_base_rate"] = float(base_brier - metrics[m]["brier"])
        fold_wins = {m: 0 for m in methods}
        for fold in vals["folds"]:
            best = min(fold["brier"], key=fold["brier"].get)
            fold_wins[best] += 1
        nfolds = max(1, len(vals["folds"]))
        report["horizons"][horizon] = {
            "available": True,
            "metrics": metrics,
            "ranking_by_brier": ranking,
            "winner": ranking[0],
            "winner_beats_base_rate": bool(metrics[ranking[0]]["brier"] < base_brier - 0.002),
            "fold_win_rate": {m: float(fold_wins[m]/nfolds) for m in methods},
            "folds": vals["folds"],
        }
    return report


def render_markdown(report: dict) -> str:
    lines = ["# Forecast Baseline Benchmark", "", report["method"], ""]
    for horizon, r in report["horizons"].items():
        lines += [f"## {horizon}", ""]
        if not r.get("available"):
            lines += ["Unavailable", ""]
            continue
        lines += ["| Method | Brier | Lift vs BaseRate | LogLoss | CalErr | Fold win |", "|---|---:|---:|---:|---:|---:|"]
        for m in r["ranking_by_brier"]:
            x = r["metrics"][m]
            lines.append(f"| {m} | {x['brier']:.4f} | {x['brier_lift_vs_base_rate']:+.4f} | {x['log_loss']:.4f} | {x['calibration_error']:.4f} | {r['fold_win_rate'][m]:.1%} |")
        lines += ["", f"Winner: **{r['winner']}**; beats base rate materially: **{r['winner_beats_base_rate']}**", ""]
    lines += ["Production forecast remains unchanged. This benchmark is diagnostic only."]
    return "\n".join(lines)


def run(days: int = 365, out_dir: str = "eth_reports/baseline_benchmark") -> dict:
    bars = fetch_deribit_4h_history(days=days)
    features = build_bootstrap_features(bars)
    report = run_benchmark(features)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report
