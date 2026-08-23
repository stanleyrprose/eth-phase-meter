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
MIN_OOS_N = 300
MIN_BRIER_IMPROVEMENT = 0.005
MAX_LOGLOSS_DEGRADATION = 1e-6
MAX_CALIBRATION_DEGRADATION = 0.01
MIN_BASELINE_BRIER_LIFT = 0.005
MIN_FOLD_WIN_RATE = 0.60
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 17


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


def _paired_brier_improvement_ci(y, p_ref, p_candidate, n_boot=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED):
    y = np.asarray(y, dtype=float)
    p_ref = np.asarray(p_ref, dtype=float)
    p_candidate = np.asarray(p_candidate, dtype=float)
    if len(y) < 2:
        return {"low": None, "median": None, "high": None}
    improvement = (p_ref - y) ** 2 - (p_candidate - y) ** 2
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=float)
    n = len(improvement)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        means[i] = improvement[idx].mean()
    low, med, high = np.quantile(means, [0.025, 0.5, 0.975])
    return {"low": float(low), "median": float(med), "high": float(high)}


def _base_rate_prediction(y_train, n_test):
    rate = float(np.mean(y_train))
    rate = float(np.clip(rate, 1e-6, 1 - 1e-6))
    return np.full(int(n_test), rate, dtype=float)


def evaluate_research_gate(mb: dict, mh: dict, mbase: dict | None = None, hmm_ci: dict | None = None, fold_win_rate: float | None = None) -> dict:
    delta = float(mb["brier"] - mh["brier"])
    logloss_improvement = float(mb["log_loss"] - mh["log_loss"])
    calibration_improvement = (
        float(mb["calibration_error"] - mh["calibration_error"])
        if mb.get("calibration_error") is not None and mh.get("calibration_error") is not None
        else None
    )
    baseline_lift = float(mbase["brier"] - mb["brier"]) if mbase is not None else None
    ci_low = hmm_ci.get("low") if hmm_ci else None
    components = {
        "oos_n_ok": bool(mh["oos_n"] >= MIN_OOS_N),
        "baseline_beats_base_rate": bool(baseline_lift is not None and baseline_lift >= MIN_BASELINE_BRIER_LIFT),
        "brier_ok": bool(delta >= MIN_BRIER_IMPROVEMENT),
        "brier_ci_ok": bool(ci_low is not None and ci_low > 0.0),
        "fold_win_rate_ok": bool(fold_win_rate is not None and fold_win_rate >= MIN_FOLD_WIN_RATE),
        "log_loss_ok": bool(logloss_improvement >= -MAX_LOGLOSS_DEGRADATION),
        "calibration_ok": bool(
            calibration_improvement is not None
            and calibration_improvement >= -MAX_CALIBRATION_DEGRADATION
        ),
    }
    failed_reasons = []
    if not components["oos_n_ok"]:
        failed_reasons.append(f"OOS_N_LT_{MIN_OOS_N}")
    if not components["baseline_beats_base_rate"]:
        failed_reasons.append(f"BASELINE_BRIER_LIFT_LT_{MIN_BASELINE_BRIER_LIFT:.3f}")
    if not components["brier_ok"]:
        failed_reasons.append(f"BRIER_IMPROVEMENT_LT_{MIN_BRIER_IMPROVEMENT:.3f}")
    if not components["brier_ci_ok"]:
        failed_reasons.append("BRIER_IMPROVEMENT_CI_INCLUDES_ZERO")
    if not components["fold_win_rate_ok"]:
        failed_reasons.append(f"FOLD_WIN_RATE_LT_{MIN_FOLD_WIN_RATE:.2f}")
    if not components["log_loss_ok"]:
        failed_reasons.append("LOG_LOSS_WORSE")
    if not components["calibration_ok"]:
        failed_reasons.append(f"CALIBRATION_DEGRADATION_GT_{MAX_CALIBRATION_DEGRADATION:.3f}")
    return {
        "baseline_brier_lift_vs_base_rate": baseline_lift,
        "brier_improvement": delta,
        "brier_improvement_ci95": hmm_ci,
        "fold_win_rate": fold_win_rate,
        "log_loss_improvement": logloss_improvement,
        "calibration_improvement": calibration_improvement,
        "components": components,
        "failed_reasons": failed_reasons,
        "passes": bool(all(components.values())),
    }


def run_ablation(features: pd.DataFrame, min_train: int = 1000, test_size: int = 120) -> dict:
    df = features.copy().reset_index(drop=True)
    synthetic_log_price = np.cumsum(df["log_return"].to_numpy(dtype=float))
    results = {h: {"base_rate": [], "baseline": [], "plus_hmm": [], "actual": [], "fold_deltas": []} for h in HORIZONS}
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
            pbase = _base_rate_prediction(y_train, len(y_test))
            results[horizon]["base_rate"].extend(pbase.tolist())
            results[horizon]["baseline"].extend(pb.tolist())
            results[horizon]["plus_hmm"].extend(ph.tolist())
            results[horizon]["actual"].extend(y_test.tolist())
            fold_delta = float(np.mean((pb - y_test) ** 2) - np.mean((ph - y_test) ** 2))
            results[horizon]["fold_deltas"].append(fold_delta)
            fold_info["horizons"][horizon] = {"n": int(len(y_test)), "brier_delta_baseline_minus_hmm": fold_delta}
        fold_summaries.append(fold_info)
        train_end += test_size
    out = {
        "schema_version": "hmm-forecast-ablation-v3",
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
        mbase = _metrics(y, vals["base_rate"])
        mb = _metrics(y, vals["baseline"])
        mh = _metrics(y, vals["plus_hmm"])
        hmm_ci = _paired_brier_improvement_ci(y, vals["baseline"], vals["plus_hmm"])
        fold_deltas = np.asarray(vals["fold_deltas"], dtype=float)
        fold_win_rate = float(np.mean(fold_deltas > 0)) if len(fold_deltas) else None
        gate = evaluate_research_gate(mb, mh, mbase=mbase, hmm_ci=hmm_ci, fold_win_rate=fold_win_rate)
        out["horizons"][horizon] = {
            "available": True,
            "base_rate": mbase,
            "baseline": mb,
            "plus_hmm": mh,
            "baseline_brier_lift_vs_base_rate": gate["baseline_brier_lift_vs_base_rate"],
            "brier_improvement": gate["brier_improvement"],
            "brier_improvement_ci95": gate["brier_improvement_ci95"],
            "fold_win_rate": gate["fold_win_rate"],
            "log_loss_improvement": gate["log_loss_improvement"],
            "calibration_improvement": gate["calibration_improvement"],
            "research_gate": {
                "thresholds": {
                    "min_oos_n": MIN_OOS_N,
                    "min_baseline_brier_lift": MIN_BASELINE_BRIER_LIFT,
                    "min_brier_improvement": MIN_BRIER_IMPROVEMENT,
                    "min_fold_win_rate": MIN_FOLD_WIN_RATE,
                    "brier_ci_low_must_exceed": 0.0,
                    "max_log_loss_degradation": MAX_LOGLOSS_DEGRADATION,
                    "max_calibration_degradation": MAX_CALIBRATION_DEGRADATION,
                },
                "components": gate["components"],
                "failed_reasons": gate["failed_reasons"],
            },
            "passes_research_gate": gate["passes"],
        }
    return out


def render_markdown(report: dict) -> str:
    lines = [
        "# HMM Forecast Ablation Report", "",
        report["method"], "",
        "| Horizon | OOS n | BaseRate Brier | Baseline Brier | +HMM Brier | Baseline lift | HMM ΔBrier | 95% CI | Fold win | ΔLogLoss | ΔCal | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|",
    ]
    for h, r in report["horizons"].items():
        if not r.get("available"):
            lines.append(f"| {h} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | FAIL |")
            continue
        br, b, m = r["base_rate"], r["baseline"], r["plus_hmm"]
        ci = r.get("brier_improvement_ci95") or {}
        ci_text = f"[{ci.get('low', float('nan')):+.4f}, {ci.get('high', float('nan')):+.4f}]"
        lines.append(
            f"| {h} | {m['oos_n']} | {br['brier']:.4f} | {b['brier']:.4f} | {m['brier']:.4f} | "
            f"{r['baseline_brier_lift_vs_base_rate']:+.4f} | {r['brier_improvement']:+.4f} | {ci_text} | "
            f"{r['fold_win_rate']:.1%} | {r['log_loss_improvement']:+.4f} | {r['calibration_improvement']:+.4f} | "
            f"{'PASS' if r['passes_research_gate'] else 'FAIL'} |"
        )
    lines += ["", "## Research gate details", ""]
    for h, r in report["horizons"].items():
        if not r.get("available"):
            continue
        comps = r.get("research_gate", {}).get("components", {})
        reasons = r.get("research_gate", {}).get("failed_reasons", [])
        lines.append(
            f"- **{h}**: OOS={'PASS' if comps.get('oos_n_ok') else 'FAIL'}, "
            f"BaseRate={'PASS' if comps.get('baseline_beats_base_rate') else 'FAIL'}, "
            f"Brier={'PASS' if comps.get('brier_ok') else 'FAIL'}, "
            f"BrierCI={'PASS' if comps.get('brier_ci_ok') else 'FAIL'}, "
            f"FoldWin={'PASS' if comps.get('fold_win_rate_ok') else 'FAIL'}, "
            f"LogLoss={'PASS' if comps.get('log_loss_ok') else 'FAIL'}, "
            f"Calibration={'PASS' if comps.get('calibration_ok') else 'FAIL'}"
            + (f"; reasons={','.join(reasons)}" if reasons else "")
        )
    lines += [
        "",
        "Interpretation: a predictive candidate must first beat the historical base rate, then show a material HMM Brier improvement whose paired 95% bootstrap CI stays above zero, win on enough outer folds, and avoid material LogLoss/calibration degradation.",
        "",
        "Predictive promotion remains disabled. Passing this report is necessary but not sufficient for full six-dimension forecast integration.",
    ]
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
