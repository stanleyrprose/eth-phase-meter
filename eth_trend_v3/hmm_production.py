from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable

import numpy as np
import pandas as pd

from .hmm_bootstrap import apply_robust_scaler, RobustScalerState, normalized_entropy
from .persistence import load_latest_record, persist_json_record

PRODUCTION_RECORD_TYPE = "hmm_production_model"
PRODUCTION_VARIANT = "return_24h"
PRODUCTION_STATES = 4


def build_production_model_record(report: dict) -> dict | None:
    """Build a serializable production-candidate record from a validated bootstrap report.

    This promotes *descriptive* HMM use only. Predictive promotion remains separate.
    """
    preferred = report.get("preferred_descriptive_variant")
    if preferred != PRODUCTION_VARIANT:
        return None
    variant = (report.get("variants") or {}).get(preferred) or {}
    winner = variant.get("winner") or {}
    directional = variant.get("winner_directional_separation") or {}
    params = variant.get("winner_model_parameters")
    profiles = variant.get("winner_state_profiles") or []
    normalization = variant.get("normalization") or {}
    if not (
        variant.get("descriptive_candidate_ready")
        and int(winner.get("n_states", 0)) == PRODUCTION_STATES
        and directional.get("passes")
        and params
        and len(profiles) == PRODUCTION_STATES
        and normalization.get("median")
        and normalization.get("scale")
    ):
        return None
    return {
        "schema_version": "hmm-production-v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_report_generated_at": report.get("generated_at"),
        "variant": preferred,
        "feature_schema": variant.get("feature_schema"),
        "n_states": PRODUCTION_STATES,
        "winner": winner,
        "directional_separation": directional,
        "normalization": normalization,
        "model_parameters": params,
        "state_profiles": profiles,
        "descriptive_production": True,
        "predictive_production": False,
        "promotion_note": "Descriptive production only. Predictive use requires separate OOS forecast ablation.",
    }


def persist_production_model(report: dict) -> bool:
    record = build_production_model_record(report)
    if record is None:
        return False
    return persist_json_record(PRODUCTION_RECORD_TYPE, record)


def load_production_model() -> dict | None:
    record = load_latest_record(PRODUCTION_RECORD_TYPE)
    if not record or not record.get("descriptive_production"):
        return None
    if record.get("variant") != PRODUCTION_VARIANT or int(record.get("n_states", 0)) != PRODUCTION_STATES:
        return None
    return record


def _diag_variances(params: dict) -> np.ndarray:
    covars = np.asarray(params["covars"], dtype=float)
    if covars.ndim == 3:
        return np.asarray([np.diag(x) for x in covars], dtype=float)
    return covars


def _emission_probabilities(x: np.ndarray, params: dict) -> np.ndarray:
    means = np.asarray(params["means"], dtype=float)
    variances = np.maximum(_diag_variances(params), 1e-8)
    diff = x[:, None, :] - means[None, :, :]
    logp = -0.5 * (
        np.sum(np.log(2.0 * math.pi * variances), axis=1)[None, :]
        + np.sum((diff * diff) / variances[None, :, :], axis=2)
    )
    logp -= np.max(logp, axis=1, keepdims=True)
    return np.exp(logp)


def causal_filter(x_scaled: np.ndarray, params: dict, initial: Iterable[float] | None = None) -> np.ndarray:
    """Causal HMM filtering p(z_t | x_1..x_t), never smoothed with future observations."""
    x = np.asarray(x_scaled, dtype=float)
    if x.ndim != 2 or len(x) == 0:
        return np.empty((0, int(params.get("n_states", 0) or len(params.get("startprob", [])))))
    trans = np.asarray(params["transmat"], dtype=float)
    start = np.asarray(list(initial), dtype=float) if initial is not None else np.asarray(params["startprob"], dtype=float)
    start = np.clip(start, 1e-12, None)
    start /= start.sum()
    emissions = _emission_probabilities(x, params)
    out = np.zeros((len(x), len(start)), dtype=float)
    prev = start
    for i, emission in enumerate(emissions):
        prior = prev if i == 0 and initial is None else prev @ trans
        post = np.clip(prior * emission, 1e-300, None)
        post /= post.sum()
        out[i] = post
        prev = post
    return out


def _live_feature_frame(candles) -> pd.DataFrame:
    if not hasattr(candles, "copy") or not hasattr(candles, "columns"):
        return pd.DataFrame()
    df = candles.copy()
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.DataFrame()
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    elif "open_time" in df.columns:
        ts = pd.to_datetime(df["open_time"], unit="ms", utc=True, errors="coerce")
    else:
        ts = pd.Series(pd.RangeIndex(len(df)), index=df.index)
    close = pd.to_numeric(df["close"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce").clip(lower=0)
    out = pd.DataFrame({"timestamp": ts, "close": close, "volume": volume})
    out["log_return"] = np.log(out["close"] / out["close"].shift(1))
    out["log_return_24h"] = np.log(out["close"] / out["close"].shift(6))
    out["realized_volatility"] = out["log_return"].rolling(12, min_periods=12).std(ddof=0)
    out["log_volume_change"] = np.log1p(out["volume"]) - np.log1p(out["volume"].shift(1))
    return out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def infer_live_regime(raw: dict, model_record: dict | None = None) -> dict:
    record = model_record or load_production_model()
    if not record:
        return {"engine": "hmm-v2", "available": False, "reason": "NO_PRODUCTION_HMM_MODEL"}
    features = _live_feature_frame((raw or {}).get("candles"))
    schema = record.get("feature_schema") or []
    if features.empty or any(c not in features.columns for c in schema) or len(features) < 2:
        return {"engine": "hmm-v2", "available": False, "reason": "INSUFFICIENT_LIVE_HMM_FEATURES"}
    x_raw = features[schema].to_numpy(dtype=float)
    norm = record["normalization"]
    scaler = RobustScalerState(median=list(norm["median"]), scale=list(norm["scale"]))
    x_scaled = apply_robust_scaler(x_raw, scaler)
    post = causal_filter(x_scaled, record["model_parameters"])
    if len(post) == 0 or not np.isfinite(post[-1]).all():
        return {"engine": "hmm-v2", "available": False, "reason": "INVALID_HMM_POSTERIOR"}
    p = post[-1]
    profiles = record.get("state_profiles") or []
    labels = {int(x["state"]): x["label"] for x in profiles if "state" in x and "label" in x}
    top = int(np.argmax(p))
    maxp = float(np.max(p))
    entropy = normalized_entropy(p)
    label = labels.get(top, f"State {top}")
    stable = maxp >= 0.55
    if not stable:
        label = "Transition"
    probability_map = {labels.get(i, f"State {i}"): round(float(p[i]), 4) for i in range(len(p))}
    return {
        "engine": "hmm-v2-production",
        "available": True,
        "regime": label,
        "probabilities": probability_map,
        "posterior": [float(v) for v in p],
        "max_posterior": maxp,
        "entropy": entropy,
        "stable": stable,
        "reason": "" if stable else "REGIME_UNSTABLE",
        "feature_schema": schema,
        "variant": record.get("variant"),
        "n_states": record.get("n_states"),
        "predictive_production": bool(record.get("predictive_production", False)),
    }
