from __future__ import annotations
import numpy as np


def detect_feature_drift(history, current, keys=None, current_versions=None):
    keys = keys or [
        "trend",
        "valuation",
        "capital_flow",
        "crowding",
        "structural_supply",
        "volatility_risk",
    ]
    flags = []
    for key in keys:
        current_version = (current_versions or {}).get(key)
        vals = np.asarray(
            [
                r.get(key)
                for r in history[-180:]
                if isinstance(r.get(key), (int, float))
                and (
                    current_version is None
                    or (r.get("_dimension_versions") or {}).get(key) == current_version
                )
            ],
            dtype=float,
        )
        value = current.get(key)
        if len(vals) < 40 or not isinstance(value, (int, float)):
            continue
        median = float(np.median(vals))
        mad = float(np.median(np.abs(vals - median))) or 1.0
        robust_z = abs((float(value) - median) / (1.4826 * mad))
        if robust_z > 4:
            flags.append({
                "feature": key,
                "feature_version": current_version,
                "baseline_n": int(len(vals)),
                "robust_z": round(robust_z, 2),
            })
    return {"status": "MODEL_DEGRADED" if flags else "NORMAL", "flags": flags}


def assess_model_health(feature_drift: dict, forecasts: dict, regime: dict) -> dict:
    flags = []
    severe = []

    for item in feature_drift.get("flags", []):
        flags.append({"type": "FEATURE_DRIFT", **item})

    if regime.get("available") and not regime.get("stable", True):
        flags.append({"type": "REGIME_UNSTABLE", "reason": regime.get("reason", "")})

    for horizon, forecast in (forecasts or {}).items():
        metrics = forecast.get("metrics") or {}
        if not metrics:
            continue
        calibration_error = metrics.get("calibration_error")
        brier_lift = metrics.get("brier_lift")
        if isinstance(calibration_error, (int, float)) and calibration_error > 0.15:
            severe.append({
                "type": "CALIBRATION_DEGRADED",
                "horizon": horizon,
                "calibration_error": calibration_error,
            })
        if isinstance(brier_lift, (int, float)) and brier_lift <= 0:
            severe.append({
                "type": "MODEL_NO_LONGER_BEATS_BASE_RATE",
                "horizon": horizon,
                "brier_lift": brier_lift,
            })

    if severe:
        status = "MODEL_UNRELIABLE"
    elif flags:
        status = "MODEL_DEGRADED"
    else:
        status = "NORMAL"

    return {"status": status, "flags": flags, "severe": severe}
