from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .experiment_registry import stable_hash

HOLDOUT_STATES = {"NEVER_TOUCHED", "CONSUMED", "CONTAMINATED"}
OVERRIDE_ACTIONS = {"FREEZE", "DEMOTE", "DISABLE_PUBLICATION", "ANNOTATE", "CLEAR"}


class GateVersionConflict(ValueError):
    pass


class HoldoutGovernanceError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(subdir: str) -> Path:
    path = Path("eth_reports/governance") / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def register_gate_version(version: str, payload: Mapping[str, Any]) -> dict:
    if not version:
        raise ValueError("gate version required")
    body = dict(payload)
    body["version"] = version
    gate_hash = stable_hash(body)
    record = {"gate_version": version, "gate_hash": gate_hash, "payload": body, "created_at": _now()}
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT gate_hash,payload FROM eth_research_gate_versions WHERE gate_version=%s", (version,))
                row = cur.fetchone()
                if row and row[0] != gate_hash:
                    raise GateVersionConflict(f"gate version {version} already exists with a different hash")
                if not row:
                    cur.execute(
                        "INSERT INTO eth_research_gate_versions(gate_version,gate_hash,payload) VALUES(%s,%s,%s::jsonb)",
                        (version, gate_hash, json.dumps(body, default=str)),
                    )
            conn.commit()
    else:
        path = _root("gates") / f"{version}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("gate_hash") != gate_hash:
                raise GateVersionConflict(f"gate version {version} already exists with a different hash")
            return existing
        path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return record


def gate_version_record(version: str) -> dict | None:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT gate_hash,payload,created_at FROM eth_research_gate_versions WHERE gate_version=%s", (version,))
                row = cur.fetchone()
                if row:
                    return {"gate_version": version, "gate_hash": row[0], "payload": row[1], "created_at": row[2].isoformat()}
        return None
    path = _root("gates") / f"{version}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def register_holdout(experiment_family: str, start_time: str, end_time: str) -> dict:
    if not experiment_family or not start_time or not end_time:
        raise HoldoutGovernanceError("experiment_family/start/end required")
    record = {
        "experiment_family": experiment_family,
        "start_time": start_time,
        "end_time": end_time,
        "status": "NEVER_TOUCHED",
        "first_viewed_at": None,
        "contaminated_at": None,
        "contamination_reason": None,
        "updated_at": _now(),
    }
    return _persist_holdout(record, create_only=True)


def _persist_holdout(record: Mapping[str, Any], *, create_only: bool = False) -> dict:
    data = dict(record)
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                if create_only:
                    cur.execute("SELECT payload FROM eth_holdout_registry WHERE experiment_family=%s", (data["experiment_family"],))
                    row = cur.fetchone()
                    if row:
                        return row[0]
                cur.execute(
                    "INSERT INTO eth_holdout_registry(experiment_family,status,payload) VALUES(%s,%s,%s::jsonb) "
                    "ON CONFLICT(experiment_family) DO UPDATE SET status=EXCLUDED.status,payload=EXCLUDED.payload,updated_at=NOW()",
                    (data["experiment_family"], data["status"], json.dumps(data, default=str)),
                )
            conn.commit()
    else:
        path = _root("holdouts") / f"{data['experiment_family']}.json"
        if create_only and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data


def holdout_record(experiment_family: str) -> dict | None:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM eth_holdout_registry WHERE experiment_family=%s", (experiment_family,))
                row = cur.fetchone()
                return row[0] if row else None
    path = _root("holdouts") / f"{experiment_family}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def mark_holdout_viewed(experiment_family: str) -> dict:
    record = holdout_record(experiment_family)
    if not record:
        raise HoldoutGovernanceError("holdout not registered")
    if record.get("status") == "CONTAMINATED":
        return record
    record["status"] = "CONSUMED"
    record["first_viewed_at"] = record.get("first_viewed_at") or _now()
    record["updated_at"] = _now()
    return _persist_holdout(record)


def mark_holdout_contaminated(experiment_family: str, *, reason: str) -> dict:
    if not reason:
        raise HoldoutGovernanceError("contamination reason required")
    record = holdout_record(experiment_family)
    if not record:
        raise HoldoutGovernanceError("holdout not registered")
    record["status"] = "CONTAMINATED"
    record["first_viewed_at"] = record.get("first_viewed_at") or _now()
    record["contaminated_at"] = _now()
    record["contamination_reason"] = reason
    record["updated_at"] = _now()
    return _persist_holdout(record)


def holdout_clean(experiment_family: str) -> bool:
    record = holdout_record(experiment_family)
    return bool(record and record.get("status") in {"NEVER_TOUCHED", "CONSUMED"})


def record_override(action: str, *, operator: str, reason: str, horizon: str = "ALL") -> dict:
    action = action.upper()
    if action not in OVERRIDE_ACTIONS:
        raise ValueError("unsupported emergency action")
    if not operator or not reason:
        raise ValueError("operator and reason required")
    event = {
        "override_id": f"override-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "horizon": horizon,
        "action": action,
        "operator": operator,
        "reason": reason,
        "timestamp": _now(),
    }
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO eth_override_log(override_id,horizon,action,operator_name,reason,payload) VALUES(%s,%s,%s,%s,%s,%s::jsonb)",
                    (event["override_id"], horizon, action, operator, reason, json.dumps(event, default=str)),
                )
                cur.execute(
                    "INSERT INTO eth_model_control_state(horizon,action,payload) VALUES(%s,%s,%s::jsonb) "
                    "ON CONFLICT(horizon) DO UPDATE SET action=EXCLUDED.action,payload=EXCLUDED.payload,updated_at=NOW()",
                    (horizon, action, json.dumps(event, default=str)),
                )
            conn.commit()
    else:
        root = _root("overrides")
        (root / f"{event['override_id']}.json").write_text(json.dumps(event, indent=2), encoding="utf-8")
        state_root = _root("controls")
        (state_root / f"{horizon}.json").write_text(json.dumps(event, indent=2), encoding="utf-8")
    return event


def current_control(horizon: str) -> dict | None:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM eth_model_control_state WHERE horizon IN (%s,'ALL') ORDER BY CASE WHEN horizon=%s THEN 0 ELSE 1 END LIMIT 1", (horizon, horizon))
                row = cur.fetchone()
                return row[0] if row else None
    specific = _root("controls") / f"{horizon}.json"
    global_path = _root("controls") / "ALL.json"
    path = specific if specific.exists() else global_path
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def publication_allowed(horizon: str) -> tuple[bool, str | None]:
    control = current_control(horizon)
    action = (control or {}).get("action")
    if action == "FREEZE":
        return False, "EMERGENCY_FREEZE"
    if action == "DISABLE_PUBLICATION":
        return False, "PUBLICATION_DISABLED"
    return True, None
