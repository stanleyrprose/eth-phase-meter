from __future__ import annotations
import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .run_manifest import dependency_hash

PARSER_VERSION = "pit-parser-v1.3"
FEATURE_VERSION = "features-v1.3"
MODEL_VERSION = "forecast-baseline-v1.3"
REGIME_VERSION = "hmm-regime-v1.3"
CONFIG_VERSION = "config-v1.3"


def _jsonable(value: Any):
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict(orient="records")
        except TypeError:
            return value.to_dict()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def payload_hash(payload: Any) -> str:
    data = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_pit_record(
    timeframe: str,
    raw: dict,
    result,
    *,
    market_state=None,
    clusters=None,
    feature_metadata=None,
    data_health=None,
    regime=None,
    forecasts=None,
    drift=None,
    anomalies=None,
    alerts=None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    normalized = _jsonable(raw)
    return {
        "event_time": result.timestamp,
        "observed_at": now,
        "source": "multi-source",
        "source_version": "actions-collector-v1.3",
        "raw_payload": normalized,
        "raw_payload_hash": payload_hash(normalized),
        "metric_value": {
            "price": result.price,
            "timeframe": timeframe,
            "market_state": result.state,
            "rule_regime": result.regime,
            "final_direction": result.final_direction,
            "available_bias": result.available_bias,
        },
        "market_state_vector": market_state or {},
        "feature_clusters": clusters or {},
        "feature_metadata": feature_metadata or [],
        "data_health": data_health or {},
        "regime": regime or {},
        "forecasts": forecasts or {},
        "model_drift": drift or {},
        "anomalies": anomalies or [],
        "alerts": alerts or [],
        "coverage": result.coverage,
        "stale": bool((data_health or {}).get("stale_sources")),
        "quality_flags": {
            "data_status": (data_health or {}).get("status")
            or (
                "NORMAL"
                if result.coverage >= 70
                else "DEGRADED"
                if result.coverage >= 50
                else "DATA_INSUFFICIENT"
            ),
            "persistence_mode": "POSTGRES" if os.getenv("DATABASE_URL") else "ARTIFACT_ONLY",
        },
        "parser_version": PARSER_VERSION,
        "feature_version": FEATURE_VERSION,
        "model_version": MODEL_VERSION,
        "regime_version": REGIME_VERSION,
        "config_version": CONFIG_VERSION,
        "git_commit_sha": os.getenv("GITHUB_SHA", "unknown"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
    }


def write_pit_snapshot(output_dir: Path, timeframe: str, record: dict) -> Path:
    pit_dir = output_dir / "pit"
    pit_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(record.get("observed_at", "unknown")).replace(":", "-").replace("+", "_")
    path = pit_dir / f"pit_{timeframe}_{stamp}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    latest = pit_dir / f"pit_{timeframe}_latest.json"
    latest.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def write_run_manifest(output_dir: Path, results: dict, extra: dict | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    coverage = {tf: r.coverage for tf, r in results.items()}
    manifest = {
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "git_commit_sha": os.getenv("GITHUB_SHA", "unknown"),
        "workflow_name": os.getenv("GITHUB_WORKFLOW", "local"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
        "python_version": platform.python_version(),
        "dependency_hash": dependency_hash(),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "regime_version": REGIME_VERSION,
        "config_version": CONFIG_VERSION,
        "data_snapshot_time": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "prediction_timestamp": {tf: r.timestamp for tf, r in results.items()},
        "persistence_mode": "POSTGRES" if os.getenv("DATABASE_URL") else "ARTIFACT_ONLY",
        **(extra or {}),
    }
    path = output_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
