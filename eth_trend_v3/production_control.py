from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

import numpy as np

from .governance import register_gate_version
from .model_artifact import load_model_artifact
from .model_state import current_model_state
from .promotion import demotion_decision, record_demotion
from .shadow_forecast import load_shadow_records


@dataclass(frozen=True)
class DemotionConfig:
    version: str = "demotion-v1"
    min_settled: int = 20
    max_calibration_error: float = 0.15


def _rolling_evidence(horizon: str, minimum: int) -> dict | None:
    rows = [
        r for r in load_shadow_records(mode="PRODUCTION")
        if r.get("horizon") == horizon and r.get("settled") and r.get("data_health") == "NORMAL"
    ]
    if len(rows) < minimum:
        return None
    rows = rows[-minimum:]
    return {
        "rolling_brier": float(np.mean([float(r["brier_loss"]) for r in rows])),
        "baseline_brier": float(np.mean([float(r["baseline_brier_loss"]) for r in rows])),
        "settled_n": len(rows),
    }


def evaluate_runtime_demotion(horizon: str, *, data_health: str, config: DemotionConfig | None = None) -> dict:
    config = config or DemotionConfig()
    state = current_model_state(horizon)
    if not state or state.get("status") != "PRODUCTION":
        return {"active": False, "demoted": False, "reason": "NO_PRODUCTION_MODEL"}
    register_gate_version(config.version, {"type": "DEMOTION_HEURISTIC", **asdict(config)})
    artifact_valid = bool(load_model_artifact(str(state.get("artifact_hash") or "")))
    rolling = _rolling_evidence(horizon, config.min_settled)
    rolling_brier = (rolling or {}).get("rolling_brier", 0.0)
    baseline_brier = (rolling or {}).get("baseline_brier", 1.0)
    calibration_error = (state.get("evidence") or {}).get("calibration_error")
    decision = demotion_decision(
        rolling_brier=float(rolling_brier),
        baseline_brier=float(baseline_brier),
        calibration_error=calibration_error,
        data_health=data_health,
        artifact_valid=artifact_valid,
        max_calibration_error=config.max_calibration_error,
    )
    # Rolling performance is only actionable once the configured minimum real settled evidence exists.
    if rolling is None:
        decision["reasons"] = [r for r in decision["reasons"] if r != "BASELINE_SUPERIOR"]
        decision["demote"] = bool(decision["reasons"])
        decision["to_state"] = "DEGRADED" if decision["reasons"] else "PRODUCTION"
    if decision["demote"]:
        updated = record_demotion(horizon, approval=state, reasons=decision["reasons"])
        return {"active": True, "demoted": True, "decision": decision, "state": updated, "rolling": rolling}
    return {"active": True, "demoted": False, "decision": decision, "state": state, "rolling": rolling}
