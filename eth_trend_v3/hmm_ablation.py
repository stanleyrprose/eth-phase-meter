from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .hmm_bootstrap import apply_robust_scaler, fetch_deribit_4h_history, build_bootstrap_features, fit_robust_scaler
from .hmm_production import causal_filter

HORIZONS = {"3d": 18, "7d": 42, "30d": 180}
BASE_FEATURES = ["log_return_24h", "realized_volatility", "log_volume_change"]
N_STATES = 4
SEED = 7


def _fit_hmm(train_raw: np.ndarray):
    from hmmlearn.hmm import GaussianHMM
    scaler = fit_robust_scaler(train_raw)
    z = apply_robust_scaler(train_raw, scaler)
    model = GaussianHMM(n_components=N_STATES, covariance_type="diag", n_iter=500, tol=1e-4, random_state=SEED).fit(z)
    params = {
        "n_states": N_STATES,
        "startprob": model.startprob_.tolist(),
        "transmat": model.transmat_.tolist(),
        "means": model.means_.tolist(),
        "covars": model.covars_.tolist(),
    }
    return scaler, params


def _calibration_bins(y, p, bins=5):
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < (hi if hi < 1 else hi + 1e-9))
        n = int(mask.sum())
        if n:
            out.append({"lo": float(lo), "hi": float(hi), "n": n, "predicted": float(p[mask].mean()), "actual": float(y[mask].mean())})
    return out


def _metrics(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=int)
    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y*np.log(p) + (1-y)*np.log(1-p)))
    bins = _calibration_bins(y, p)
    n = sum(b["n"] for b in bins)
    cal = float(sum(b["n"] * abs(b["predicted"] - b["actual"]) for b in bins) / n) if n else None
    return {"brier": brier, "log_loss": logloss, "calibration_error": cal, "oos_n": int(len(y)), "calibration": bins}


def _fit_calibrated_classifier(X_train, y_train, X_test):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.isotonic import IsotonicRegression
    n = len(y_train)
    cal_n = max(40, int(n * 0.2))
    fit_end = n - cal_n
    if fit_end < 100 or len(np.unique(y_train[:fit_end])) < 2 or len(np.unique(y_train[fit_end:])) < 2:
        return None
    scaler = StandardScaler().fit(X_train[:fit_end])
    model = LogisticRegression(max_iter=1000, C=0.5).fit(scaler.transform(X_train[:fit_end]), y_train[:fit_end])
    raw_cal = model.predict_proba(scaler.transform(X_train[fit_end:]))[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip").fit(raw_cal, y_train[fit_end:])
    raw = model.predict_proba(scaler.transform(X_test))[:, 1]
    return iso.predict(raw)


def run_ablation(features: pd.DataFrame, min_train: int = 1000, test_size: int = 120) -> dict:
    df = features.copy().reset_index(drop=True)
    synthetic_log_price = np.cumsum(df["log_return"].to_numpy(dtype=float))
    results = {h: {"baseline": [], "plus_hmm": [], "actual": []} for h in HORIZONS}
    fold_summaries = []
    train_end = min_train
    while train_end + 1 < len(df):
        test_end = min(len(df), train_end + test_size)
        train_raw = df[BASE_FEATURES].iloc[:train_end].to_numpy(dtype=float)
        scaler_hmm, params = _fit_hmm(train_raw)
        all_raw = df[BASE_FEATURES].iloc[:test_end].to_numpy(dtype=float)
        all_z = apply_robust_scaler(all_raw, scaler_hmm)
        posterior = causal_filter(all_z, params)
        fold_info = {"train_end": train_end, "test_end": test_end, "horizons": {}}
        for horizon, steps in HORIZONS.items():
            train_idx = np.arange(0, max(0, train_end - steps))
            test_idx = np.arange(train_end, min(test_end, len(df) - steps))
            if len(train_idx) < 300 or len(test_idx) == 0:
                continue
            y_train = (synthetic_log_price[train_idx + steps] > synthetic_log_price[train_idx]).astype(int)
            y_test = (synthetic_log_price[test_idx + steps] > synthetic_log_price[test_idx]).astype(int)
            Xb_train = df[BASE_FEATURES].iloc[train_idx].to_numpy(dtype=float)
            Xb_test = df[BASE_FEATURES].iloc[test_idx].to_numpy(dtype=float)
            Xh_train = np.hstack([Xb_train, posterior[train_idx]])
            Xh_test = np.hstack([Xb_test, posterior[test_idx]])
            pb = _fit_calibrated_classifier(Xb_train, y_train, Xb_test)
            ph = _fit_calibrated_classifier(Xh_train, y_train, Xh_test)
            if pb is None or ph is None:
                continue
            results[horizon]["baseline"].extend(pb.tolist())
            results[horizon]["plus_hmm"].extend(ph.tolist())
            results[horizon]["actual"].extend(y_test.tolist())
            fold_info["horizons"][horizon] = int(len(y_test))
        fold_summaries.append(fold_info)
        train_end += test_size
    out = {
        "schema_version": "hmm-forecast-ablation-v1",
        "method": "Expanding OOS; HMM refit per outer fold; causal filtered posterior only; no automatic promotion.",
        "baseline_features": BASE_FEATURES,
        "hmm_features": ["p_state_0", "p_state_1", "p_state_2", "p_state_3"],
        "folds": fold_summaries,
        "horizons": {},
        "promotion_allowed": False,
    }
    for horizon, vals in results.items():
        y = vals["actual"]
        if not y:
            out["horizons"][horizon] = {"available": False, "reason": "NO_VALID_OOS_PREDICTIONS"}
            continue
        mb = _metrics(y, vals["baseline"])
        mh = _metrics(y, vals["plus_hmm"])
        delta = float(mb["brier"] - mh["brier"])
        cal_ok = (
            mh["calibration_error"] is not None
            and mb["calibration_error"] is not None
            and mh["calibration_error"] <= mb["calibration_error"] + 0.02
        )
        passes = bool(mh["oos_n"] >= 120 and delta > 0 and cal_ok)
        out["horizons"][horizon] = {
            "available": True,
            "baseline": mb,
            "plus_hmm": mh,
            "brier_improvement": delta,
            "passes_research_gate": passes,
        }
    return out


def render_markdown(report: dict) -> str:
    lines = [
        "# HMM Forecast Ablation Report", "", report["method"], "",
        "| Horizon | OOS n | Baseline Brier | +HMM Brier | Improvement | Baseline LogLoss | +HMM LogLoss | Baseline CalErr | +HMM CalErr | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for h, r in report["horizons"].items():
        if not r.get("available"):
            lines.append(f"| {h} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | FAIL |")
            continue
        b, m = r["baseline"], r["plus_hmm"]
        lines.append(
            f"| {h} | {m['oos_n']} | {b['brier']:.4f} | {m['brier']:.4f} | {r['brier_improvement']:+.4f} | "
            f"{b['log_loss']:.4f} | {m['log_loss']:.4f} | {b['calibration_error']:.4f} | {m['calibration_error']:.4f} | "
            f"{'PASS' if r['passes_research_gate'] else 'FAIL'} |"
        )
    lines += ["", "Predictive promotion remains disabled. Passing this report is necessary but not sufficient for full six-dimension forecast integration."]
    return "\n".join(lines)


def run(days: int = 365, out_dir: str = "eth_reports/hmm_ablation") -> dict:
    bars = fetch_deribit_4h_history(days=days)
    features = build_bootstrap_features(bars)
    report = run_ablation(features)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report
