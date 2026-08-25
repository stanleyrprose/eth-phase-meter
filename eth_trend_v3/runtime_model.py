from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .dataset import HORIZONS, build_labeled_rows
from .dynamic_baseline import BaselineSpec, predict_baseline
from .model_artifact import infer_model_artifact, load_model_artifact
from .promotion import reliability


def _baseline_spec(payload: Mapping[str, Any]) -> BaselineSpec:
    allowed = {"name", "window_days", "half_life_days", "regime_key", "prior_strength", "min_regime_count"}
    values = {key: value for key, value in dict(payload).items() if key in allowed}
    return BaselineSpec(**values)


def frozen_inference(
    *,
    horizon: str,
    model_state: Mapping[str, Any],
    current_features: Mapping[str, Any],
    pit_records: list[dict],
    mode: str,
) -> dict:
    if horizon not in HORIZONS:
        raise ValueError("unsupported horizon")
    if mode not in {"SHADOW", "PRODUCTION"}:
        raise ValueError("unsupported inference mode")
    artifact = load_model_artifact(str(model_state.get("artifact_hash") or ""))
    if not artifact:
        return {"available": False, "reason": "MODEL_ARTIFACT_MISSING"}
    if artifact.get("model_version") != model_state.get("model_version"):
        return {"available": False, "reason": "MODEL_VERSION_MISMATCH"}
    if artifact.get("inference_contract_hash") != model_state.get("inference_contract_hash", artifact.get("inference_contract_hash")):
        return {"available": False, "reason": "TRAIN_SERVE_SKEW"}

    rows = build_labeled_rows(pit_records, HORIZONS[horizon], timeframe="4h")
    if not rows:
        return {"available": False, "reason": "INSUFFICIENT_DATA"}
    try:
        probability = infer_model_artifact(artifact, current_features)
    except Exception:
        return {"available": False, "reason": "FEATURE_UNAVAILABLE"}

    current = dict(current_features)
    current.setdefault("feature_time", datetime.now(timezone.utc).isoformat())
    current.setdefault("timestamp", current["feature_time"])
    try:
        baseline = float(predict_baseline(rows, [current], _baseline_spec(artifact["baseline_spec"]))[0])
    except Exception:
        return {"available": False, "reason": "SOURCE_CONTRACT_FAILED"}

    evidence = model_state.get("evidence") or {}
    return {
        "available": True,
        "mode": mode,
        "horizon": horizon,
        "probability_up": probability,
        "baseline_probability": baseline,
        "status": mode,
        "state": "BULLISH" if probability >= 0.5 else "BEARISH",
        "reliability": reliability(evidence),
        "model_id": artifact["model_id"],
        "model_version": artifact["model_version"],
        "artifact_hash": artifact["artifact_hash"],
        "inference_contract_hash": artifact["inference_contract_hash"],
        "experiment_id": artifact["experiment_id"],
        "dataset_hash": artifact["dataset_hash"],
        "config_hash": artifact["config_hash"],
        "gate_version": artifact["gate_version"],
        "settlement_time": (datetime.now(timezone.utc) + timedelta(hours=HORIZONS[horizon])).isoformat(),
    }
