from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .model_lifecycle import transition


def _artifact_path(horizon: str) -> Path:
    root = Path("eth_reports/governance/model-states")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{horizon}.json"


def current_model_state(horizon: str) -> dict | None:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM eth_model_states WHERE horizon=%s", (horizon,))
                row = cur.fetchone()
                return row[0] if row else None
    path = _artifact_path(horizon)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def persist_model_state(record: Mapping[str, Any]) -> dict:
    data = dict(record)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO eth_model_states(horizon,status,payload) VALUES(%s,%s,%s::jsonb) "
                    "ON CONFLICT(horizon) DO UPDATE SET status=EXCLUDED.status,payload=EXCLUDED.payload,updated_at=NOW()",
                    (data["horizon"], data["status"], json.dumps(data, default=str)),
                )
            conn.commit()
    else:
        _artifact_path(data["horizon"]).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data


def persist_transition(model_id: str, event) -> dict:
    data = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    data["model_id"] = model_id
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO eth_model_transition_log(model_id,from_state,to_state,reason,trigger,operator_or_system,gate_version,payload) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                    (model_id, data["from_state"], data["to_state"], data["reason"], data["trigger"], data["operator_or_system"], data["gate_version"], json.dumps(data, default=str)),
                )
            conn.commit()
    else:
        root = Path("eth_reports/governance/transitions")
        root.mkdir(parents=True, exist_ok=True)
        stamp = str(data.get("timestamp", "")).replace(":", "-")
        (root / f"{model_id}-{stamp}.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data


def transition_model(
    horizon: str,
    to_state: str,
    *,
    reason: str,
    trigger: str = "manual",
    operator_or_system: str = "system",
    gate_version: str = "v1",
    patch: Mapping[str, Any] | None = None,
) -> dict:
    current = current_model_state(horizon)
    if not current:
        raise ValueError("model state not initialized")
    event = transition(
        current["status"], to_state, reason=reason, trigger=trigger,
        operator_or_system=operator_or_system, gate_version=gate_version,
    )
    persist_transition(str(current.get("model_id") or horizon), event)
    updated = dict(current)
    updated.update(dict(patch or {}))
    updated["status"] = to_state
    updated["last_transition"] = event.to_dict()
    return persist_model_state(updated)


def initialize_model_state(*, horizon: str, status: str, model_id: str, model_version: str, artifact_hash: str, experiment_id: str, gate_version: str) -> dict:
    if current_model_state(horizon):
        raise ValueError("model state already exists")
    if status not in {"EXPERIMENTAL", "CANDIDATE"}:
        raise ValueError("forecast state must initialize as EXPERIMENTAL or CANDIDATE")
    return persist_model_state({
        "horizon": horizon,
        "status": status,
        "model_id": model_id,
        "model_version": model_version,
        "artifact_hash": artifact_hash,
        "experiment_id": experiment_id,
        "gate_version": gate_version,
    })



def activate_shadow_candidate(horizon: str, *, operator_or_system: str = "reviewer") -> dict:
    from .experiment_registry import load_experiment, validate_experiment
    from .model_artifact import load_model_artifact

    state = current_model_state(horizon)
    if not state or state.get("status") != "CANDIDATE":
        raise ValueError("shadow activation requires CANDIDATE state")
    artifact = load_model_artifact(str(state.get("artifact_hash") or ""))
    if not artifact:
        raise ValueError("candidate artifact missing")
    experiment = load_experiment(str(state.get("experiment_id") or ""))
    if not experiment:
        raise ValueError("candidate experiment missing")
    validate_experiment(experiment)
    if experiment.get("model_artifact_hash") not in (None, artifact.get("artifact_hash")):
        raise ValueError("candidate experiment/artifact mismatch")
    return transition_model(
        horizon,
        "SHADOW",
        reason="candidate approved for shadow observation",
        trigger="manual_review",
        operator_or_system=operator_or_system,
        gate_version=str(state.get("gate_version") or "v1"),
        patch={"inference_contract_hash": artifact.get("inference_contract_hash")},
    )
