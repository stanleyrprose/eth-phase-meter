from __future__ import annotations
import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PARSER_VERSION = "pit-parser-v0.1"
FEATURE_VERSION = "features-v3.1"
MODEL_VERSION = "baseline-rule-v3.1"
CONFIG_VERSION = "config-v1"


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
    data = json.dumps(_jsonable(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_pit_record(timeframe: str, raw: dict, result) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    normalized = _jsonable(raw)
    return {
        "event_time": result.timestamp,
        "observed_at": now,
        "source": "multi-source",
        "source_version": "actions-collector-v3.1",
        "raw_payload": normalized,
        "raw_payload_hash": payload_hash(normalized),
        "metric_value": {
            "price": result.price,
            "timeframe": timeframe,
            "market_state": result.state,
            "regime": result.regime,
            "final_direction": result.final_direction,
            "available_bias": result.available_bias,
        },
        "coverage": result.coverage,
        "stale": result.coverage < 50,
        "quality_flags": {
            "data_status": "NORMAL" if result.coverage >= 70 else "DEGRADED" if result.coverage >= 50 else "DATA_INSUFFICIENT",
            "persistence_mode": "POSTGRES" if os.getenv("DATABASE_URL") else "ARTIFACT_ONLY",
        },
        "parser_version": PARSER_VERSION,
        "feature_version": FEATURE_VERSION,
        "model_version": MODEL_VERSION,
        "config_version": CONFIG_VERSION,
    }


def write_pit_snapshot(output_dir: Path, timeframe: str, raw: dict, result) -> Path:
    pit_dir = output_dir / "pit"
    pit_dir.mkdir(parents=True, exist_ok=True)
    path = pit_dir / f"pit_{timeframe}.json"
    path.write_text(json.dumps(build_pit_record(timeframe, raw, result), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def write_run_manifest(output_dir: Path, results: dict) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    coverage = {tf: r.coverage for tf, r in results.items()}
    manifest = {
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "git_commit_sha": os.getenv("GITHUB_SHA", "unknown"),
        "workflow_name": os.getenv("GITHUB_WORKFLOW", "local"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "config_version": CONFIG_VERSION,
        "data_snapshot_time": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "prediction_timestamp": {tf: r.timestamp for tf, r in results.items()},
        "persistence_mode": "POSTGRES" if os.getenv("DATABASE_URL") else "ARTIFACT_ONLY",
    }
    path = output_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
