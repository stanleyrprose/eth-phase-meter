from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from hmmlearn.hmm import GaussianHMM
from sklearn.metrics import adjusted_rand_score

DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
FEATURES = ["log_return", "realized_volatility", "log_volume_change"]
STATE_COUNTS = (3, 4, 5)
SEEDS = (7, 17, 29, 43, 71)


@dataclass
class RobustScalerState:
    median: list[float]
    scale: list[float]


def fetch_deribit_4h_history(days: int = 365, chunk_days: int = 30) -> pd.DataFrame:
    """Fetch closed ETH-PERPETUAL 4h bars from Deribit in bounded chunks."""
    end = datetime.now(timezone.utc)
    # Exclude the currently forming 4h bucket.
    end_hour = end.hour - (end.hour % 4)
    closed_boundary = end.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    start = closed_boundary - timedelta(days=days)
    frames: list[pd.DataFrame] = []
    cursor = start
    while cursor < closed_boundary:
        chunk_end = min(cursor + timedelta(days=chunk_days), closed_boundary)
        params = {
            "instrument_name": "ETH-PERPETUAL",
            "start_timestamp": int(cursor.timestamp() * 1000),
            "end_timestamp": int(chunk_end.timestamp() * 1000),
            "resolution": "240",
        }
        r = requests.get(DERIBIT_URL, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise RuntimeError(f"Deribit error: {body['error']}")
        result = body.get("result") or {}
        ticks = result.get("ticks") or []
        closes = result.get("close") or []
        volumes = result.get("volume") or []
        if ticks:
            frames.append(pd.DataFrame({"timestamp": ticks, "close": closes, "volume": volumes}))
        cursor = chunk_end
    if not frames:
        raise RuntimeError("No Deribit history returned")
    df = pd.concat(frames, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[df["timestamp"] < pd.Timestamp(closed_boundary)]
    return df.reset_index(drop=True)


def build_bootstrap_features(bars: pd.DataFrame) -> pd.DataFrame:
    df = bars.copy().sort_values("timestamp").reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce").clip(lower=0)
    df["log_return"] = np.log(close / close.shift(1))
    # 48h realized volatility = std of 12 consecutive 4h returns.
    df["realized_volatility"] = df["log_return"].rolling(12, min_periods=12).std(ddof=0)
    df["log_volume_change"] = np.log1p(volume) - np.log1p(volume.shift(1))
    return df[["timestamp", *FEATURES]].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def fit_robust_scaler(x: np.ndarray) -> RobustScalerState:
    med = np.nanmedian(x, axis=0)
    mad = np.nanmedian(np.abs(x - med), axis=0)
    scale = 1.4826 * mad
    scale = np.where((~np.isfinite(scale)) | (scale < 1e-9), 1.0, scale)
    return RobustScalerState(median=med.tolist(), scale=scale.tolist())


def apply_robust_scaler(x: np.ndarray, scaler: RobustScalerState) -> np.ndarray:
    med = np.asarray(scaler.median, dtype=float)
    scale = np.asarray(scaler.scale, dtype=float)
    return np.clip((x - med) / scale, -5.0, 5.0)


def hmm_parameter_count(n_states: int, n_features: int) -> int:
    # start probs + transition matrix + diagonal Gaussian means/variances
    return (n_states - 1) + n_states * (n_states - 1) + 2 * n_states * n_features


def bic(log_likelihood: float, n_samples: int, n_states: int, n_features: int) -> float:
    return hmm_parameter_count(n_states, n_features) * math.log(n_samples) - 2.0 * log_likelihood


def state_diagnostics(model: GaussianHMM, states: np.ndarray) -> dict:
    occupancy = [float(np.mean(states == i)) for i in range(model.n_components)]
    durations = []
    for i in range(model.n_components):
        pii = float(model.transmat_[i, i])
        durations.append(float(1.0 / max(1e-9, 1.0 - pii)))
    return {
        "occupancy": occupancy,
        "expected_duration_bars": durations,
        "min_occupancy": min(occupancy) if occupancy else 0.0,
        "min_expected_duration_bars": min(durations) if durations else 0.0,
    }


def fit_candidate(x_scaled: np.ndarray, n_states: int, seed: int) -> tuple[GaussianHMM, dict, np.ndarray]:
    model = GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=500,
        tol=1e-4,
        random_state=seed,
    )
    model.fit(x_scaled)
    ll = float(model.score(x_scaled))
    states = model.predict(x_scaled)
    diag = state_diagnostics(model, states)
    diag.update({
        "seed": seed,
        "log_likelihood": ll,
        "bic": bic(ll, len(x_scaled), n_states, x_scaled.shape[1]),
        "converged": bool(getattr(model.monitor_, "converged", False)),
    })
    return model, diag, states


def seed_stability(state_sequences: list[np.ndarray]) -> float:
    if len(state_sequences) < 2:
        return 0.0
    vals = []
    for i in range(len(state_sequences)):
        for j in range(i + 1, len(state_sequences)):
            vals.append(adjusted_rand_score(state_sequences[i], state_sequences[j]))
    return float(np.median(vals)) if vals else 0.0


def normalized_entropy(probabilities: Iterable[float]) -> float:
    p = np.asarray(list(probabilities), dtype=float)
    p = p[np.isfinite(p) & (p > 0)]
    if len(p) <= 1:
        return 0.0
    p = p / p.sum()
    return float(-np.sum(p * np.log(p)) / math.log(len(p)))


def label_state_profile(profile: dict[str, float], vol_median: float) -> str:
    r = float(profile.get("log_return", 0.0))
    vol = float(profile.get("realized_volatility", 0.0))
    vol_prefix = "High-Vol" if vol > vol_median else "Low-Vol"
    if r > 0.001:
        direction = "Bull"
    elif r < -0.001:
        direction = "Bear"
    else:
        direction = "Sideways"
    return f"{vol_prefix} {direction}"


def model_parameters(model: GaussianHMM) -> dict:
    return {
        "n_states": int(model.n_components),
        "covariance_type": model.covariance_type,
        "startprob": model.startprob_.tolist(),
        "transmat": model.transmat_.tolist(),
        "means": model.means_.tolist(),
        "covars": model.covars_.tolist(),
    }


def walk_forward_validation(x_raw: np.ndarray, n_states: int, seed: int, min_train: int = 500, test_size: int = 100) -> list[dict]:
    folds = []
    train_end = min_train
    while train_end + test_size <= len(x_raw):
        train = x_raw[:train_end]
        test = x_raw[train_end: train_end + test_size]
        scaler = fit_robust_scaler(train)
        train_z = apply_robust_scaler(train, scaler)
        test_z = apply_robust_scaler(test, scaler)
        model = GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=500,
            tol=1e-4,
            random_state=seed,
        ).fit(train_z)
        test_ll = float(model.score(test_z))
        states = model.predict(test_z)
        occ = [float(np.mean(states == i)) for i in range(n_states)]
        folds.append({
            "train_n": train_end,
            "test_n": test_size,
            "test_avg_log_likelihood": test_ll / test_size,
            "test_min_occupancy": min(occ),
            "converged": bool(getattr(model.monitor_, "converged", False)),
        })
        train_end += test_size
    return folds


def train_candidates(features: pd.DataFrame) -> dict:
    x_raw = features[FEATURES].to_numpy(dtype=float)
    if len(x_raw) < 500:
        raise ValueError(f"Need at least 500 observations; got {len(x_raw)}")
    scaler = fit_robust_scaler(x_raw)
    x_scaled = apply_robust_scaler(x_raw, scaler)
    candidates = []
    selected_models: dict[int, GaussianHMM] = {}
    for n_states in STATE_COUNTS:
        runs = []
        seqs = []
        models = []
        for seed in SEEDS:
            model, diag, states = fit_candidate(x_scaled, n_states, seed)
            runs.append(diag)
            seqs.append(states)
            models.append(model)
        best_idx = int(np.argmin([r["bic"] for r in runs]))
        best = runs[best_idx]
        stability = seed_stability(seqs)
        wf = walk_forward_validation(x_raw, n_states, SEEDS[best_idx])
        wf_ok = len(wf) >= 2 and all(f["converged"] and np.isfinite(f["test_avg_log_likelihood"]) for f in wf)
        occupancy_ok = best["min_occupancy"] >= 0.03
        duration_ok = best["min_expected_duration_bars"] >= 2.0
        stability_ok = stability >= 0.60
        candidate = {
            "n_states": n_states,
            "best_seed": SEEDS[best_idx],
            "best_bic": best["bic"],
            "best_log_likelihood": best["log_likelihood"],
            "seed_stability_ari_median": stability,
            "occupancy_ok": occupancy_ok,
            "duration_ok": duration_ok,
            "seed_stability_ok": stability_ok,
            "walk_forward_ok": wf_ok,
            "passes_descriptive_gate": bool(occupancy_ok and duration_ok and stability_ok and wf_ok),
            "best_run": best,
            "walk_forward": wf,
        }
        candidates.append(candidate)
        selected_models[n_states] = models[best_idx]
    passing = [c for c in candidates if c["passes_descriptive_gate"]]
    winner = min(passing, key=lambda c: c["best_bic"]) if passing else None
    winner_model = selected_models[winner["n_states"]] if winner else None
    state_profiles = None
    posterior = None
    transition = None
    if winner_model is not None:
        states = winner_model.predict(x_scaled)
        profiles = []
        raw_profiles = []
        for i in range(winner_model.n_components):
            mask = states == i
            raw_mean = np.mean(x_raw[mask], axis=0) if np.any(mask) else np.full(x_raw.shape[1], np.nan)
            raw_profiles.append({FEATURES[j]: float(raw_mean[j]) for j in range(len(FEATURES))})
        vol_median = float(np.nanmedian([p["realized_volatility"] for p in raw_profiles]))
        for i, profile in enumerate(raw_profiles):
            profiles.append({"state": i, "label": label_state_profile(profile, vol_median), **profile})
        state_profiles = profiles
        posterior = winner_model.predict_proba(x_scaled)[-1].tolist()
        transition = winner_model.transmat_.tolist()
    latest_entropy = normalized_entropy(posterior or []) if posterior else None
    latest_max_posterior = max(posterior) if posterior else None
    latest_state = int(np.argmax(posterior)) if posterior else None
    latest_label = None
    if latest_state is not None and state_profiles:
        latest_label = state_profiles[latest_state]["label"]
        if latest_max_posterior is not None and latest_max_posterior < 0.55:
            latest_label = "Transition"
    observation_count = len(x_raw)
    if observation_count < 500:
        maturity = "UNAVAILABLE"
    elif observation_count < 1000:
        maturity = "EXPERIMENTAL"
    else:
        maturity = "CANDIDATE"
    descriptive_ready = bool(winner is not None and observation_count >= 1000)
    return {
        "schema_version": "hmm-bootstrap-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_schema": FEATURES,
        "observation_count": observation_count,
        "maturity": maturity,
        "descriptive_production_ready": descriptive_ready,
        "history_start": features["timestamp"].iloc[0].isoformat(),
        "history_end": features["timestamp"].iloc[-1].isoformat(),
        "normalization": {"type": "robust_z", "clip": [-5, 5], "median": scaler.median, "scale": scaler.scale},
        "candidate_states": list(STATE_COUNTS),
        "seeds": list(SEEDS),
        "candidates": candidates,
        "winner": winner,
        "winner_transition_matrix": transition,
        "winner_state_profiles": state_profiles,
        "winner_latest_posterior": posterior,
        "winner_latest_max_posterior": latest_max_posterior,
        "winner_latest_entropy": latest_entropy,
        "winner_latest_state": latest_state,
        "winner_latest_label": latest_label,
        "winner_model_parameters": model_parameters(winner_model) if winner_model is not None else None,
        "promotion_allowed": False,
        "promotion_note": "Bootstrap is descriptive candidate validation only. Production promotion requires explicit review and forecast ablation.",
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# HMM Historical Bootstrap Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Observations: {report['observation_count']}",
        f"History: {report['history_start']} → {report['history_end']}",
        f"Features: {', '.join(report['feature_schema'])}",
        f"Maturity: {report['maturity']}",
        f"Descriptive production ready: {report['descriptive_production_ready']}",
        "",
        "| States | BIC | Seed stability (ARI) | Occupancy | Duration | Walk-forward | Gate |",
        "|---:|---:|---:|---|---|---|---|",
    ]
    for c in report["candidates"]:
        lines.append(
            f"| {c['n_states']} | {c['best_bic']:.1f} | {c['seed_stability_ari_median']:.3f} | "
            f"{'PASS' if c['occupancy_ok'] else 'FAIL'} | {'PASS' if c['duration_ok'] else 'FAIL'} | "
            f"{'PASS' if c['walk_forward_ok'] else 'FAIL'} | {'PASS' if c['passes_descriptive_gate'] else 'FAIL'} |"
        )
    lines += ["", "## Winner", ""]
    if report["winner"]:
        lines.append(f"Candidate: {report['winner']['n_states']}-state HMM (descriptive gate passed).")
        lines.append(
            f"Latest regime: {report['winner_latest_label']} "
            f"(max posterior={report['winner_latest_max_posterior']:.3f}, entropy={report['winner_latest_entropy']:.3f})."
        )
        lines.append("")
        lines.append("### State profiles")
        lines.append("")
        for p in report.get("winner_state_profiles") or []:
            lines.append(
                f"- State {p['state']}: {p['label']} | return={p['log_return']:.5f}, "
                f"RV={p['realized_volatility']:.5f}, dlogV={p['log_volume_change']:.5f}"
            )
    else:
        lines.append("No candidate passed the descriptive production gate.")
    lines += [
        "",
        "Promotion is intentionally disabled. Forecast ablation must prove OOS value before HMM can be used predictively.",
    ]
    return "\n".join(lines) + "\n"


def run(days: int = 365, out_dir: str = "eth_reports/hmm_bootstrap") -> dict:
    bars = fetch_deribit_4h_history(days=days)
    features = build_bootstrap_features(bars)
    report = train_candidates(features)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    features.to_csv(out / "features.csv", index=False)
    return report
