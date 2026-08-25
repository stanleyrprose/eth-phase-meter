from __future__ import annotations

from typing import Any, Mapping

from .experiment_registry import stable_hash
from .persistence import load_latest_record
from .probabilistic_research import predict_artifact
from .promotion import promotion_gate, reliability


def load_production_model(horizon: str) -> dict | None:
    return load_latest_record(f"production_forecast_model_{horizon}")


def runtime_forecast(horizon: str, current_features: Mapping[str, Any], data_health: Mapping[str, Any], model_record: Mapping[str, Any] | None = None) -> dict:
    record = dict(model_record) if model_record is not None else load_production_model(horizon)
    if not record:
        return {"probability_up":None,"state":"UNAVAILABLE","status":"UNAVAILABLE","reliability":"UNAVAILABLE","reason":"NO_MODEL_BEATS_BASELINE","selected_model":None,"baseline_probability":None}
    if record.get("status") != "PRODUCTION":
        return {"probability_up":None,"state":"UNAVAILABLE","status":"UNAVAILABLE","reliability":"UNAVAILABLE","reason":"MODEL_NOT_PRODUCTION","selected_model":record.get("model_version"),"baseline_probability":record.get("baseline_probability")}
    artifact=record.get("artifact")
    artifact_hash=record.get("artifact_hash")
    if not artifact or not artifact_hash or stable_hash(artifact)!=artifact_hash:
        return {"probability_up":None,"state":"UNAVAILABLE","status":"UNAVAILABLE","reliability":"UNAVAILABLE","reason":"MODEL_ARTIFACT_MISSING","selected_model":record.get("model_version"),"baseline_probability":record.get("baseline_probability")}
    evidence=dict(record.get("promotion_evidence") or {})
    evidence["data_health_normal"]=data_health.get("status") in {"NORMAL","OK"}
    evidence["data_health"]="NORMAL" if evidence["data_health_normal"] else "CRITICAL"
    decision=promotion_gate(evidence,gate_version=record.get("gate_version","v1"))
    if not decision.eligible:
        return {"probability_up":None,"state":"UNAVAILABLE","status":"UNAVAILABLE","reliability":"UNAVAILABLE","reason":decision.reasons[0] if decision.reasons else "MODEL_DEGRADED","selected_model":record.get("model_version"),"baseline_probability":record.get("baseline_probability")}
    kept,p=predict_artifact(artifact,[current_features],record.get("base_features"))
    if not kept or len(p)!=1:
        return {"probability_up":None,"state":"UNAVAILABLE","status":"UNAVAILABLE","reliability":"UNAVAILABLE","reason":"FEATURE_UNAVAILABLE","selected_model":record.get("model_version"),"baseline_probability":record.get("baseline_probability")}
    prob=float(p[0])
    return {"probability_up":prob,"state":"UP" if prob>=.5 else "DOWN","status":"PRODUCTION","reliability":reliability(evidence),"reason":"","selected_model":record.get("model_version"),"baseline_probability":record.get("baseline_probability"),"gate_version":decision.gate_version,"experiment_id":record.get("experiment_id")}
