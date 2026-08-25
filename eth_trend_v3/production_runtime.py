from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .probabilistic_research import predict_artifact
from .promotion import production_output


REQUIRED_MODEL_FIELDS = {"status", "horizon", "experiment_id", "gate_version", "artifact_hash", "artifact", "base_features"}


def _valid_record(record: Mapping[str, Any] | None, horizon: str) -> tuple[bool, str]:
    if not record:
        return False, "NO_PRODUCTION_MODEL_APPROVED"
    if record.get("status") != "PRODUCTION" or record.get("horizon") != horizon:
        return False, "NO_PRODUCTION_MODEL_APPROVED"
    if any(record.get(k) in (None, "") for k in REQUIRED_MODEL_FIELDS):
        return False, "REGISTRY_INCOMPLETE"
    return True, ""


def load_production_model(horizon: str, artifact_dir: str = "eth_reports/production_models") -> dict | None:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        try:
            import psycopg
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT payload FROM eth_model_governance_log WHERE payload->>'event_type'='MODEL_PROMOTED' AND payload->>'horizon'=%s ORDER BY created_at DESC LIMIT 1", (horizon,))
                    row = cur.fetchone()
                    return row[0] if row else None
        except Exception:
            return None
    path = Path(artifact_dir) / f"{horizon}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def infer_approved_probability(record: Mapping[str, Any], current_features: Mapping[str, Any]) -> tuple[float | None, str]:
    horizon = str(record.get("horizon", ""))
    valid, reason = _valid_record(record, horizon)
    if not valid:
        return None, reason
    base_features = list(record["base_features"])
    if any(current_features.get(f) is None or not np.isfinite(float(current_features.get(f))) for f in base_features):
        return None, "FEATURE_UNAVAILABLE"
    kept, p = predict_artifact(record["artifact"], [dict(current_features)], base_features)
    if not kept or len(p) != 1:
        return None, "TRAIN_SERVE_SKEW"
    return float(p[0]), ""


def production_forecast(horizon: str, current_features: Mapping[str, Any], data_health: str) -> dict:
    record = load_production_model(horizon)
    valid, reason = _valid_record(record, horizon)
    if not valid:
        return production_output(horizon=horizon, probability=None, baseline_probability=None, status="UNAVAILABLE", reliability_level="UNAVAILABLE", data_health=data_health, reason=reason)
    p, reason = infer_approved_probability(record, current_features)
    if p is None:
        return production_output(horizon=horizon, probability=None, baseline_probability=record.get("baseline_probability"), status="UNAVAILABLE", reliability_level="UNAVAILABLE", data_health=data_health, reason=reason)
    if data_health not in {"NORMAL", "OK"}:
        return production_output(horizon=horizon, probability=None, baseline_probability=record.get("baseline_probability"), status="UNAVAILABLE", reliability_level="UNAVAILABLE", data_health=data_health, reason="DATA_HEALTH_CRITICAL")
    return production_output(horizon=horizon, probability=p, baseline_probability=record.get("baseline_probability"), status="PRODUCTION", reliability_level=record.get("reliability", "LOW"), data_health=data_health)
