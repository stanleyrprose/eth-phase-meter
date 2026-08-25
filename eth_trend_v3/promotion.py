from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping


UNAVAILABLE_REASONS={"NO_MODEL_BEATS_BASELINE","INSUFFICIENT_DATA","INSUFFICIENT_EFFECTIVE_SAMPLE","CALIBRATION_FAILED","DATA_HEALTH_CRITICAL","MODEL_DEGRADED","MODEL_ARTIFACT_MISSING","FEATURE_UNAVAILABLE","SOURCE_CONTRACT_FAILED","SHADOW_INSUFFICIENT","REGISTRY_INCOMPLETE","LEAKAGE_DETECTED","TRAIN_SERVE_SKEW","HOLDOUT_CONTAMINATED"}


@dataclass(frozen=True)
class GateDecision:
    eligible:bool; status:str; reasons:list[str]; gate_version:str
    def to_dict(self): return asdict(self)


def promotion_gate(evidence:Mapping[str,Any], *, gate_version:str="v1") -> GateDecision:
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
    if float(evidence.get("research_brier_skill",0))<=0: reasons.append("NO_MODEL_BEATS_BASELINE")
    if float(evidence.get("shadow_brier_skill",0))<=0: reasons.append("NO_MODEL_BEATS_BASELINE")
    return GateDecision(not reasons,"PROMOTION_ELIGIBLE" if not reasons else "UNAVAILABLE",sorted(set(reasons)),gate_version)


def reliability(evidence:Mapping[str,Any])->str:
    if evidence.get("data_health")!="NORMAL": return "UNAVAILABLE"
    shadow=float(evidence.get("shadow_brier_skill",0)); research=float(evidence.get("research_brier_skill",0)); cal=float(evidence.get("calibration_error",1))
    if shadow>0.05 and research>0.05 and cal<0.05: return "HIGH"
    if shadow>0 and research>0 and cal<0.10: return "MEDIUM"
    if shadow>0 and research>0: return "LOW"
    return "UNAVAILABLE"


def demotion_decision(*, rolling_brier:float, baseline_brier:float, calibration_error:float|None, data_health:str, artifact_valid:bool=True)->dict:
    reasons=[]
    if rolling_brier>baseline_brier: reasons.append("BASELINE_SUPERIOR")
    if calibration_error is not None and calibration_error>.15: reasons.append("CALIBRATION_DRIFT")
    if data_health=="CRITICAL": reasons.append("DATA_HEALTH_CRITICAL")
    if not artifact_valid: reasons.append("MODEL_ARTIFACT_MISSING")
    return {"demote":bool(reasons),"to_state":"DEGRADED" if reasons else "PRODUCTION","reasons":reasons}


def emergency_override(action:str, *, operator:str, reason:str)->dict:
    allowed={"FREEZE","DEMOTE","DISABLE_PUBLICATION","ANNOTATE"}
    if action not in allowed: raise ValueError("manual override cannot promote a model")
    if not operator or not reason: raise ValueError("operator and reason required")
    from datetime import datetime,timezone
    return {"action":action,"operator":operator,"reason":reason,"timestamp":datetime.now(timezone.utc).isoformat(),"non_standard_flow":True}
