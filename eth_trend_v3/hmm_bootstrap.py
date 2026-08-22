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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from hmmlearn.hmm import GaussianHMM
from sklearn.metrics import adjusted_rand_score

DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
FEATURE_SETS = {
    "return_4h": ["log_return", "realized_volatility", "log_volume_change"],
    "return_24h": ["log_return_24h", "realized_volatility", "log_volume_change"],
}
STATE_COUNTS = (3, 4, 5)
SEEDS = (7, 17, 29, 43, 71)


@dataclass
class RobustScalerState:
    median: list[float]
    scale: list[float]


def _http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, connect=4, read=4, status=4, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET"]))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_deribit_4h_history(days: int = 365, chunk_days: int = 30) -> pd.DataFrame:
    """Fetch Deribit 1h candles, aggregate to strict closed 4h ETH-PERPETUAL bars."""
    end = datetime.now(timezone.utc)
    end_hour = end.hour - (end.hour % 4)
    closed_boundary = end.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    start = closed_boundary - timedelta(days=days)
    frames: list[pd.DataFrame] = []
    cursor = start
    session = _http_session()

    # Deribit does not support a native 240-minute resolution.
    # Fetch supported 60-minute candles and aggregate locally to 4h.
    while cursor < closed_boundary:
        chunk_end = min(cursor + timedelta(days=chunk_days), closed_boundary)
        params = {
            "instrument_name": "ETH-PERPETUAL",
            "start_timestamp": int(cursor.timestamp() * 1000),
            "end_timestamp": int(chunk_end.timestamp() * 1000),
            "resolution": "60",
        }
        r = session.get(DERIBIT_URL, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise RuntimeError(f"Deribit error: {body['error']}")
        result = body.get("result") or {}
        ticks = result.get("ticks") or []
        closes = result.get("close") or []
        volumes = result.get("volume") or []
        if ticks:
            if not (len(ticks) == len(closes) == len(volumes)):
                raise RuntimeError(
                    f"Deribit candle length mismatch: ticks={len(ticks)} close={len(closes)} volume={len(volumes)}"
                )
            frames.append(pd.DataFrame({"timestamp": ticks, "close": closes, "volume": volumes}))
        cursor = chunk_end

    if not frames:
        raise RuntimeError("No Deribit history returned")

    hourly = pd.concat(frames, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
    hourly["timestamp"] = pd.to_datetime(hourly["timestamp"], unit="ms", utc=True)
    hourly = hourly[hourly["timestamp"] < pd.Timestamp(closed_boundary)].copy()
    hourly["close"] = pd.to_numeric(hourly["close"], errors="coerce")
    hourly["volume"] = pd.to_numeric(hourly["volume"], errors="coerce")
    hourly = hourly.dropna(subset=["close", "volume"])

    # Strict UTC 4h buckets. Keep only buckets with exactly four hourly candles;
    # this prevents incomplete or gapped 4h observations from entering the HMM.
    hourly["bucket_4h"] = hourly["timestamp"].dt.floor("4h")
    grouped = (
        hourly.groupby("bucket_4h", as_index=False)
        .agg(
            timestamp=("bucket_4h", "first"),
            close=("close", "last"),
            volume=("volume", "sum"),
            hourly_count=("timestamp", "count"),
        )
    )
    four_hour = grouped[
        (grouped["hourly_count"] == 4)
        & (grouped["timestamp"] < pd.Timestamp(closed_boundary))
    ][["timestamp", "close", "volume"]]

    if four_hour.empty:
        raise RuntimeError("No complete 4h bars could be aggregated from Deribit 1h history")
    return four_hour.reset_index(drop=True)


def build_bootstrap_features(bars: pd.DataFrame) -> pd.DataFrame:
    df = bars.copy().sort_values("timestamp").reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce").clip(lower=0)
    df["log_return"] = np.log(close / close.shift(1))
    df["log_return_24h"] = np.log(close / close.shift(6))
    # 48h realized volatility = std of 12 consecutive 4h returns.
    df["realized_volatility"] = df["log_return"].rolling(12, min_periods=12).std(ddof=0)
    df["log_volume_change"] = np.log1p(volume) - np.log1p(volume.shift(1))
    cols = ["timestamp", "log_return", "log_return_24h", "realized_volatility", "log_volume_change"]
    return df[cols].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


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


def _state_profiles(model: GaussianHMM, states: np.ndarray, x_raw: np.ndarray, feature_cols: list[str]) -> list[dict]:
    profiles = []
    for i in range(model.n_components):
        mask = states == i
        raw_mean = np.mean(x_raw[mask], axis=0) if np.any(mask) else np.full(x_raw.shape[1], np.nan)
        profiles.append({feature_cols[j]: float(raw_mean[j]) for j in range(len(feature_cols))})
    return profiles


def _profile_signature(profiles: list[dict], feature_cols: list[str]) -> np.ndarray:
    """Order-free profile summary used to compare folds after label switching."""
    rows = []
    for p in profiles:
        rows.append([float(p.get(c, np.nan)) for c in feature_cols])
    arr = np.asarray(rows, dtype=float)
    if not np.isfinite(arr).all() or len(arr) == 0:
        return np.empty((0, len(feature_cols)))
    # Sort by volatility first, then first feature. This gives a stable economic ordering.
    vol_idx = feature_cols.index("realized_volatility") if "realized_volatility" in feature_cols else 0
    first_idx = 0
    order = np.lexsort((arr[:, first_idx], arr[:, vol_idx]))
    return arr[order]


def _profile_distance(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or a.size == 0:
        return float("inf")
    stacked = np.vstack([a, b])
    scale = np.nanmedian(np.abs(stacked - np.nanmedian(stacked, axis=0)), axis=0)
    scale = np.where((~np.isfinite(scale)) | (scale < 1e-9), 1.0, scale)
    return float(np.nanmedian(np.abs((a - b) / scale)))


def walk_forward_validation(
    x_raw: np.ndarray,
    feature_cols: list[str],
    n_states: int,
    seed: int,
    min_train: int = 500,
    test_size: int = 100,
) -> list[dict]:
    folds = []
    train_end = min_train
    prev_signature = None
    prev_transmat = None
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
        test_states = model.predict(test_z)
        train_states = model.predict(train_z)
        occ = [float(np.mean(test_states == i)) for i in range(n_states)]
        profiles = _state_profiles(model, train_states, train, feature_cols)
        signature = _profile_signature(profiles, feature_cols)
        profile_drift = _profile_distance(prev_signature, signature) if prev_signature is not None else 0.0
        transmat_drift = (
            float(np.mean(np.abs(model.transmat_ - prev_transmat)))
            if prev_transmat is not None and prev_transmat.shape == model.transmat_.shape
            else 0.0
        )
        folds.append({
            "train_n": train_end,
            "test_n": test_size,
            "test_avg_log_likelihood": test_ll / test_size,
            "test_min_occupancy": min(occ),
            "converged": bool(getattr(model.monitor_, "converged", False)),
            "profile_drift": profile_drift,
            "transmat_drift": transmat_drift,
        })
        prev_signature = signature
        prev_transmat = model.transmat_.copy()
        train_end += test_size
    return folds


def _directional_separation(profiles: list[dict], direction_feature: str) -> dict:
    vals = np.asarray([float(p.get(direction_feature, np.nan)) for p in profiles], dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 2:
        return {"spread": 0.0, "bullish_states": 0, "bearish_states": 0, "passes": False}
    threshold = 0.003 if direction_feature == "log_return_24h" else 0.001
    bullish = int(np.sum(vals > threshold))
    bearish = int(np.sum(vals < -threshold))
    spread = float(np.max(vals) - np.min(vals))
    return {
        "spread": spread,
        "bullish_states": bullish,
        "bearish_states": bearish,
        "passes": bool(bullish >= 1 and bearish >= 1),
    }


def train_candidates(features: pd.DataFrame, feature_set_name: str, feature_cols: list[str]) -> dict:
    x_raw = features[feature_cols].to_numpy(dtype=float)
    if len(x_raw) < 500:
        raise ValueError(f"Need at least 500 observations; got {len(x_raw)}")
    scaler = fit_robust_scaler(x_raw)
    x_scaled = apply_robust_scaler(x_raw, scaler)
    candidates = []
    selected_models: dict[int, GaussianHMM] = {}
    selected_states: dict[int, np.ndarray] = {}
    for n_states in STATE_COUNTS:
        runs, seqs, models, successful_seeds, seed_errors = [], [], [], [], []
        for seed in SEEDS:
            try:
                model, diag, states = fit_candidate(x_scaled, n_states, seed)
                runs.append(diag); seqs.append(states); models.append(model); successful_seeds.append(seed)
            except Exception as exc:
                seed_errors.append({"seed": seed, "error_type": type(exc).__name__, "message": str(exc)[:500]})
        if not runs:
            candidates.append({
                "n_states": n_states,
                "successful_seed_count": 0,
                "failed_seed_count": len(seed_errors),
                "seed_errors": seed_errors,
                "passes_descriptive_gate": False,
                "failure_reason": "ALL_SEEDS_FAILED",
            })
            continue
        best_idx = int(np.argmin([r["bic"] for r in runs]))
        best = runs[best_idx]
        best_seed = successful_seeds[best_idx]
        stability = seed_stability(seqs) if len(seqs) >= 2 else 0.0
        try:
            wf = walk_forward_validation(x_raw, feature_cols, n_states, best_seed)
            wf_error = None
        except Exception as exc:
            wf = []
            wf_error = {"error_type": type(exc).__name__, "message": str(exc)[:500]}
        wf_basic_ok = len(wf) >= 2 and all(f["converged"] and np.isfinite(f["test_avg_log_likelihood"]) for f in wf)
        profile_drifts = [f["profile_drift"] for f in wf[1:] if np.isfinite(f["profile_drift"])]
        trans_drifts = [f["transmat_drift"] for f in wf[1:] if np.isfinite(f["transmat_drift"])]
        wf_profile_stability = float(np.median(profile_drifts)) if profile_drifts else float("inf")
        wf_transition_stability = float(np.median(trans_drifts)) if trans_drifts else float("inf")
        wf_structure_ok = bool(wf_profile_stability <= 2.5 and wf_transition_stability <= 0.15)
        wf_ok = bool(wf_basic_ok and wf_structure_ok)
        occupancy_ok = best["min_occupancy"] >= 0.03
        duration_ok = best["min_expected_duration_bars"] >= 2.0
        stability_ok = len(seqs) >= 2 and stability >= 0.60
        best_model = models[best_idx]
        best_states = seqs[best_idx]
        profiles = _state_profiles(best_model, best_states, x_raw, feature_cols)
        direction_feature = "log_return_24h" if "log_return_24h" in feature_cols else "log_return"
        direction = _directional_separation(profiles, direction_feature)
        candidate = {
            "n_states": n_states,
            "best_seed": best_seed,
            "best_bic": best["bic"],
            "best_log_likelihood": best["log_likelihood"],
            "successful_seed_count": len(successful_seeds),
            "failed_seed_count": len(seed_errors),
            "seed_errors": seed_errors,
            "seed_stability_ari_median": stability,
            "occupancy_ok": occupancy_ok,
            "duration_ok": duration_ok,
            "seed_stability_ok": stability_ok,
            "walk_forward_basic_ok": wf_basic_ok,
            "walk_forward_profile_drift_median": wf_profile_stability,
            "walk_forward_transmat_drift_median": wf_transition_stability,
            "walk_forward_structure_ok": wf_structure_ok,
            "walk_forward_ok": wf_ok,
            "walk_forward_error": wf_error,
            "directional_separation": direction,
            "passes_descriptive_gate": bool(occupancy_ok and duration_ok and stability_ok and wf_ok),
            "best_run": best,
            "walk_forward": wf,
        }
        candidates.append(candidate)
        selected_models[n_states] = best_model
        selected_states[n_states] = best_states
    passing = [c for c in candidates if c.get("passes_descriptive_gate")]
    winner = min(passing, key=lambda c: c["best_bic"]) if passing else None
    winner_model = selected_models[winner["n_states"]] if winner else None
    state_profiles = posterior = transition = None
    latest_entropy = latest_max_posterior = latest_state = latest_label = None
    directional = None
    if winner_model is not None:
        states = selected_states[winner["n_states"]]
        raw_profiles = _state_profiles(winner_model, states, x_raw, feature_cols)
        direction_feature = "log_return_24h" if "log_return_24h" in feature_cols else "log_return"
        vol_median = float(np.nanmedian([p["realized_volatility"] for p in raw_profiles]))
        state_profiles = []
        for i, profile in enumerate(raw_profiles):
            direction_value = float(profile.get(direction_feature, 0.0))
            label_profile = {"log_return": direction_value, "realized_volatility": profile["realized_volatility"]}
            state_profiles.append({"state": i, "label": label_state_profile(label_profile, vol_median), **profile})
        posterior = winner_model.predict_proba(x_scaled)[-1].tolist()
        transition = winner_model.transmat_.tolist()
        latest_entropy = normalized_entropy(posterior)
        latest_max_posterior = max(posterior)
        latest_state = int(np.argmax(posterior))
        latest_label = state_profiles[latest_state]["label"]
        if latest_max_posterior < 0.55:
            latest_label = "Transition"
        directional = _directional_separation(raw_profiles, direction_feature)
    observation_count = len(x_raw)
    maturity = "UNAVAILABLE" if observation_count < 500 else ("EXPERIMENTAL" if observation_count < 1000 else "CANDIDATE")
    descriptive_ready = bool(winner is not None and observation_count >= 1000)
    return {
        "feature_set": feature_set_name,
        "feature_schema": feature_cols,
        "observation_count": observation_count,
        "maturity": maturity,
        "descriptive_candidate_ready": descriptive_ready,
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
        "winner_directional_separation": directional,
        "winner_model_parameters": model_parameters(winner_model) if winner_model is not None else None,
    }


def run_comparative(features: pd.DataFrame) -> dict:
    variants = {
        name: train_candidates(features, name, cols)
        for name, cols in FEATURE_SETS.items()
    }
    eligible = []
    for name, v in variants.items():
        if v.get("descriptive_candidate_ready") and v.get("winner"):
            directional = (v.get("winner_directional_separation") or {}).get("passes", False)
            eligible.append((1 if directional else 0, -float(v["winner"]["best_bic"]), name))
    preferred = max(eligible)[2] if eligible else None
    return {
        "schema_version": "hmm-comparative-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history_start": features["timestamp"].iloc[0].isoformat(),
        "history_end": features["timestamp"].iloc[-1].isoformat(),
        "observation_count": len(features),
        "variants": variants,
        "preferred_descriptive_variant": preferred,
        "promotion_allowed": False,
        "promotion_note": "Comparison is descriptive validation only. Predictive use requires separate OOS forecast ablation.",
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# HMM v2 Comparative Bootstrap Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Observations: {report['observation_count']}",
        f"History: {report['history_start']} → {report['history_end']}",
        f"Preferred descriptive variant: {report.get('preferred_descriptive_variant') or 'None'}",
        "",
    ]
    for name, variant in report["variants"].items():
        lines += [
            f"## Variant: {name}",
            "",
            f"Features: {', '.join(variant['feature_schema'])}",
            f"Maturity: {variant['maturity']}",
            f"Descriptive candidate ready: {variant['descriptive_candidate_ready']}",
            "",
            "| States | BIC | Seed ARI | Occupancy | Duration | WF basic | WF structure | Profile drift | Trans drift | Directional | Gate |",
            "|---:|---:|---:|---|---|---|---|---:|---:|---|---|",
        ]
        for c in variant["candidates"]:
            if c.get("failure_reason"):
                lines.append(f"| {c['n_states']} | n/a | n/a | FAIL | FAIL | FAIL | FAIL | n/a | n/a | n/a | FAIL |")
                continue
            d = c.get("directional_separation") or {}
            lines.append(
                f"| {c['n_states']} | {c['best_bic']:.1f} | {c['seed_stability_ari_median']:.3f} | "
                f"{'PASS' if c['occupancy_ok'] else 'FAIL'} | {'PASS' if c['duration_ok'] else 'FAIL'} | "
                f"{'PASS' if c['walk_forward_basic_ok'] else 'FAIL'} | {'PASS' if c['walk_forward_structure_ok'] else 'FAIL'} | "
                f"{c['walk_forward_profile_drift_median']:.3f} | {c['walk_forward_transmat_drift_median']:.3f} | "
                f"{'PASS' if d.get('passes') else 'NO'} | {'PASS' if c['passes_descriptive_gate'] else 'FAIL'} |"
            )
        lines += ["", "### Winner", ""]
        if variant.get("winner"):
            lines.append(f"{variant['winner']['n_states']}-state HMM passed the descriptive gate.")
            lines.append(
                f"Latest regime: {variant['winner_latest_label']} "
                f"(max posterior={variant['winner_latest_max_posterior']:.3f}, entropy={variant['winner_latest_entropy']:.3f})."
            )
            ds = variant.get("winner_directional_separation") or {}
            lines.append(
                f"Directional separation: {'PASS' if ds.get('passes') else 'NO'} "
                f"(bullish_states={ds.get('bullish_states', 0)}, bearish_states={ds.get('bearish_states', 0)}, spread={ds.get('spread', 0.0):.5f})."
            )
            lines.append("")
            for p in variant.get("winner_state_profiles") or []:
                parts = [f"State {p['state']}: {p['label']}"]
                for col in variant['feature_schema']:
                    parts.append(f"{col}={p[col]:.5f}")
                lines.append("- " + " | ".join(parts))
        else:
            lines.append("No candidate passed the descriptive gate.")
        lines.append("")
    lines += [
        "## Decision",
        "",
        "No HMM variant is automatically promoted into Forecast. A separate walk-forward forecast ablation must prove OOS Brier improvement before predictive use.",
    ]
    return "\n".join(lines) + "\n"


def run(days: int = 365, out_dir: str = "eth_reports/hmm_bootstrap") -> dict:
    bars = fetch_deribit_4h_history(days=days)
    features = build_bootstrap_features(bars)
    report = run_comparative(features)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    features.to_csv(out / "features.csv", index=False)
    return report
