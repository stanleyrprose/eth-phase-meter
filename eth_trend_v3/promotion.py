from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


UNAVAILABLE_REASONS={"NO_MODEL_BEATS_BASELINE","NO_PRODUCTION_MODEL_APPROVED","INSUFFICIENT_DATA","INSUFFICIENT_EFFECTIVE_SAMPLE","CALIBRATION_FAILED","DATA_HEALTH_CRITICAL","MODEL_DEGRADED","MODEL_ARTIFACT_MISSING","FEATURE_UNAVAILABLE","SOURCE_CONTRACT_FAILED","SHADOW_INSUFFICIENT","REGISTRY_INCOMPLETE","LEAKAGE_DETECTED","TRAIN_SERVE_SKEW","HOLDOUT_CONTAMINATED"}


@dataclass(frozen=True)
class GateConfig:
    version: str = "v1"
    min_research_brier_skill: float = 0.0
    min_shadow_brier_skill: float = 0.0
    max_calibration_error: float = 0.15


@dataclass(frozen=True)
class GateDecision:
    eligible:bool; status:str; reasons:list[str]; gate_version:str
    def to_dict(self): return asdict(self)


def promotion_gate(evidence:Mapping[str,Any], *, gate_version:str="v1", config: GateConfig | None = None) -> GateDecision:
    cfg = config or GateConfig(version=gate_version)
    reasons=[]
    hard={
        "leakage_free":"LEAKAGE_DETECTED",
        "pit_valid":"SOURCE_CONTRACT_FAILED",
        "registry_complete":"REGISTRY_INCOMPLETE",
        "artifact_valid":"MODEL_ARTIFACT_MISSING",
        "train_serve_parity":"TRAIN_SERVE_SKEW",
        "shadow_complete":"SHADOW_INSUFFICIENT",
        "data_health_normal":"DATA_HEALTH_CRITICAL",
        "emergency_freeze_clear":"DATA_HEALTH_CRITICAL",
    }
    for key,reason in hard.items():
        if not bool(evidence.get(key)): reasons.append(reason)
    if bool(evidence.get("holdout_contaminated", False)): reasons.append("HOLDOUT_CONTAMINATED")
    if float(evidence.get("research_brier_skill",0))<=cfg.min_research_brier_skill: reasons.append("NO_MODEL_BEATS_BASELINE")
    if float(evidence.get("shadow_brier_skill",0))<=cfg.min_shadow_brier_skill: reasons.append("NO_MODEL_BEATS_BASELINE")
    cal=evidence.get("calibration_error")
    if cal is not None and float(cal)>cfg.max_calibration_error: reasons.append("CALIBRATION_FAILED")
    return GateDecision(not reasons,"PROMOTION_ELIGIBLE" if not reasons else "UNAVAILABLE",sorted(set(reasons)),cfg.version)


def reliability(evidence:Mapping[str,Any])->str:
    if evidence.get("data_health")!="NORMAL": return "UNAVAILABLE"
    shadow=float(evidence.get("shadow_brier_skill",0)); research=float(evidence.get("research_brier_skill",0)); cal=float(evidence.get("calibration_error",1))
    if shadow>0.05 and research>0.05 and cal<0.05: return "HIGH"
    if shadow>0 and research>0 and cal<0.10: return "MEDIUM"
    if shadow>0 and research>0: return "LOW"
    return "UNAVAILABLE"


def demotion_decision(*, rolling_brier:float, baseline_brier:float, calibration_error:float|None, data_health:str, artifact_valid:bool=True, max_calibration_error: float=.15)->dict:
    reasons=[]
    if rolling_brier>baseline_brier: reasons.append("BASELINE_SUPERIOR")
    if calibration_error is not None and calibration_error>max_calibration_error: reasons.append("CALIBRATION_DRIFT")
    if data_health=="CRITICAL": reasons.append("DATA_HEALTH_CRITICAL")
    if not artifact_valid: reasons.append("MODEL_ARTIFACT_MISSING")
    return {"demote":bool(reasons),"to_state":"DEGRADED" if reasons else "PRODUCTION","reasons":reasons}


def persist_governance_event(event: Mapping[str, Any], artifact_dir: str = "eth_reports/governance") -> str:
    data = dict(event)
    data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    event_id = data.setdefault("event_id", f"gov-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}")
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS eth_model_governance_log(event_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), event_type TEXT NOT NULL, payload JSONB NOT NULL)")
                cur.execute("INSERT INTO eth_model_governance_log(event_id,event_type,payload) VALUES(%s,%s,%s::jsonb) ON CONFLICT(event_id) DO UPDATE SET payload=EXCLUDED.payload", (event_id, data.get("event_type","UNKNOWN"), json.dumps(data, default=str)))
            conn.commit()
    else:
        root=Path(artifact_dir); root.mkdir(parents=True,exist_ok=True); (root/f"{event_id}.json").write_text(json.dumps(data,indent=2,default=str),encoding="utf-8")
    return event_id


def emergency_override(action:str, *, operator:str, reason:str)->dict:
    allowed={"FREEZE","DEMOTE","DISABLE_PUBLICATION","ANNOTATE"}
    if action not in allowed: raise ValueError("manual override cannot promote a model")
    if not operator or not reason: raise ValueError("operator and reason required")
    return {"event_type":"EMERGENCY_OVERRIDE","action":action,"operator":operator,"reason":reason,"timestamp":datetime.now(timezone.utc).isoformat(),"non_standard_flow":True}


def production_output(*, horizon: str, probability: float | None, baseline_probability: float | None, status: str, reliability_level: str, data_health: str, reason: str = "") -> dict:
    if probability is None or status != "PRODUCTION":
        return {"horizon": horizon, "probability_up": None, "status": "UNAVAILABLE", "reliability": "UNAVAILABLE", "data_health": data_health, "reason": reason or "NO_PRODUCTION_MODEL_APPROVED", "baseline_probability": baseline_probability}
    return {"horizon": horizon, "probability_up": float(probability), "status": "PRODUCTION", "reliability": reliability_level, "data_health": data_health, "reason": "", "baseline_probability": baseline_probability}
