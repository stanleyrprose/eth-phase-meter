from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .experiment_registry import stable_hash
from .probabilistic_research import predict_artifact

ARTIFACT_SCHEMA_VERSION = "forecast-model-artifact-v1"


class ModelArtifactError(ValueError):
    pass


def inference_contract_hash(*, base_features: list[str], interactions: list[list[str]] | list[tuple[str, str]], calibration: Mapping[str, Any]) -> str:
    return stable_hash({
        "artifact_schema": ARTIFACT_SCHEMA_VERSION,
        "model_type": "logistic",
        "base_features": list(base_features),
        "interactions": [list(x) for x in interactions],
        "calibration_method": (calibration or {}).get("method", "none"),
    })


def build_model_artifact(
    *,
    model_id: str,
    model_version: str,
    experiment_id: str,
    horizon: str,
    git_sha: str,
    dataset_hash: str,
    config_hash: str,
    gate_version: str,
    baseline_spec: Mapping[str, Any],
    base_features: list[str],
    logistic_artifact: Mapping[str, Any],
    calibration: Mapping[str, Any] | None = None,
) -> dict:
    calibration = dict(calibration or {"method": "none"})
    if calibration.get("method", "none") != "none":
        raise ModelArtifactError("only frozen no-calibration artifacts are currently production-serializable")
    body = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_id": model_id,
        "model_version": model_version,
        "experiment_id": experiment_id,
        "horizon": horizon,
        "git_sha": git_sha,
        "dataset_hash": dataset_hash,
        "config_hash": config_hash,
        "gate_version": gate_version,
        "baseline_spec": dict(baseline_spec),
        "base_features": list(base_features),
        "logistic_artifact": dict(logistic_artifact),
        "calibration": calibration,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    body["inference_contract_hash"] = inference_contract_hash(
        base_features=body["base_features"],
        interactions=body["logistic_artifact"].get("interactions", []),
        calibration=calibration,
    )
    body["artifact_hash"] = stable_hash(body)
    validate_model_artifact(body)
    return body


def validate_model_artifact(artifact: Mapping[str, Any]) -> None:
    required = (
        "schema_version", "model_id", "model_version", "experiment_id", "horizon", "git_sha",
        "dataset_hash", "config_hash", "gate_version", "baseline_spec", "base_features",
        "logistic_artifact", "calibration", "inference_contract_hash", "artifact_hash",
    )
    missing = [key for key in required if artifact.get(key) in (None, "")]
    if missing:
        raise ModelArtifactError("missing model artifact fields: " + ",".join(missing))
    body = dict(artifact)
    claimed = body.pop("artifact_hash")
    if stable_hash(body) != claimed:
        raise ModelArtifactError("model artifact hash mismatch")
    expected_contract = inference_contract_hash(
        base_features=list(artifact["base_features"]),
        interactions=(artifact["logistic_artifact"] or {}).get("interactions", []),
        calibration=artifact["calibration"],
    )
    if artifact.get("inference_contract_hash") != expected_contract:
        raise ModelArtifactError("inference contract hash mismatch")
    if (artifact.get("calibration") or {}).get("method", "none") != "none":
        raise ModelArtifactError("unsupported frozen calibration method")


def infer_model_artifact(artifact: Mapping[str, Any], features: Mapping[str, Any]) -> float:
    validate_model_artifact(artifact)
    row = {name: features.get(name) for name in artifact["base_features"]}
    kept, probabilities = predict_artifact(
        artifact["logistic_artifact"],
        [row],
        base_features=list(artifact["base_features"]),
    )
    if len(kept) != 1 or len(probabilities) != 1:
        raise ModelArtifactError("required production features unavailable")
    p = float(probabilities[0])
    if not 0.0 <= p <= 1.0:
        raise ModelArtifactError("probability outside [0,1]")
    return p


def persist_model_artifact(artifact: Mapping[str, Any], artifact_dir: str = "eth_reports/model-artifacts") -> str:
    validate_model_artifact(artifact)
    data = dict(artifact)
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO eth_model_artifacts(artifact_hash,model_id,model_version,horizon,payload) "
                    "VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(artifact_hash) DO NOTHING",
                    (data["artifact_hash"], data["model_id"], data["model_version"], data["horizon"], json.dumps(data, default=str)),
                )
            conn.commit()
    else:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{data['artifact_hash']}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if stable_hash(existing) != stable_hash(data):
                raise ModelArtifactError("immutable artifact hash collision")
        else:
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data["artifact_hash"]


def load_model_artifact(artifact_hash: str, artifact_dir: str = "eth_reports/model-artifacts") -> dict | None:
    if not artifact_hash:
        return None
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM eth_model_artifacts WHERE artifact_hash=%s", (artifact_hash,))
                row = cur.fetchone()
                data = row[0] if row else None
    else:
        path = Path(artifact_dir) / f"{artifact_hash}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if data:
        validate_model_artifact(data)
    return data
