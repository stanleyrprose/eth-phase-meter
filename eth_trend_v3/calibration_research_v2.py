from __future__ import annotations

import numpy as np

from .research_metrics import brier, calibration_error, log_loss


def calibrate_predictions(raw_cal, y_cal, raw_test, method: str, sample_weight=None):
    raw_cal = np.asarray(raw_cal, dtype=float)
    y_cal = np.asarray(y_cal, dtype=int)
    raw_test = np.asarray(raw_test, dtype=float)
    if method == "none":
        return raw_test
    if len(y_cal) < 20 or len(np.unique(y_cal)) < 2:
        return None
    weights = None if sample_weight is None else np.asarray(sample_weight, dtype=float)
    if method == "platt":
        from sklearn.linear_model import LogisticRegression

        eps = 1e-6
        x = np.log(np.clip(raw_cal, eps, 1 - eps) / np.clip(1 - raw_cal, eps, 1 - eps)).reshape(-1, 1)
        xt = np.log(np.clip(raw_test, eps, 1 - eps) / np.clip(1 - raw_test, eps, 1 - eps)).reshape(-1, 1)
        model = LogisticRegression(max_iter=1000, C=1.0)
        model.fit(x, y_cal, sample_weight=weights)
        return model.predict_proba(xt)[:, 1]
    if method == "isotonic":
        from sklearn.isotonic import IsotonicRegression

        return IsotonicRegression(out_of_bounds="clip").fit(raw_cal, y_cal, sample_weight=weights).predict(raw_test)
    raise ValueError(method)


def _metrics(y, p):
    return {
        "brier": brier(y, p),
        "log_loss": log_loss(y, p),
        "calibration_error": calibration_error(y, p),
    }


def compare_calibration(y_test, raw_test, raw_cal, y_cal, *, eligible: bool):
    if not eligible:
        return {"available": False, "reason": "CALIBRATION_NOT_ELIGIBLE"}
    out = {}
    for method in ("none", "platt", "isotonic"):
        p = calibrate_predictions(raw_cal, y_cal, raw_test, method)
        if p is None:
            out[method] = {"available": False, "reason": "INSUFFICIENT_CALIBRATION_DATA"}
            continue
        out[method] = {"available": True, **_metrics(y_test, p)}
    valid = [m for m, v in out.items() if v.get("available")]
    if not valid:
        return {"available": False, "reason": "CALIBRATION_FAILED", "methods": out}
    winner = min(valid, key=lambda m: out[m]["brier"])
    return {
        "available": True,
        "winner": winner,
        "methods": out,
        "note": "NO_CALIBRATION is a formal candidate; calibration cannot rescue an ineligible raw model.",
    }


def calibration_stability_report(
    raw_fit,
    y_fit,
    raw_validation,
    y_validation,
    raw_test,
    y_test,
    *,
    eligible: bool,
    rolling_sizes=(60, 120),
    recency_half_life: float = 60.0,
):
    """Select calibration on a validation split, then evaluate the selected candidate once on test.

    The final test is never used to choose method or window. This keeps calibration model selection
    inside the train/calibration/validation region and preserves the test as OOS evidence.
    """
    if not eligible:
        return {"available": False, "reason": "CALIBRATION_NOT_ELIGIBLE"}

    raw_fit = np.asarray(raw_fit, dtype=float)
    y_fit = np.asarray(y_fit, dtype=int)
    raw_validation = np.asarray(raw_validation, dtype=float)
    y_validation = np.asarray(y_validation, dtype=int)
    raw_test = np.asarray(raw_test, dtype=float)
    y_test = np.asarray(y_test, dtype=int)

    windows = [("expanding", np.arange(len(y_fit)), None)]
    for size in rolling_sizes:
        if len(y_fit) >= size:
            idx = np.arange(len(y_fit) - size, len(y_fit))
            windows.append((f"rolling-{size}", idx, None))
    if len(y_fit):
        age = np.arange(len(y_fit) - 1, -1, -1, dtype=float)
        weights = np.exp(-np.log(2) * age / max(recency_half_life, 1e-9))
        windows.append((f"recency-hl{recency_half_life:g}", np.arange(len(y_fit)), weights))

    validation_results = {}
    for window_name, idx, weights in windows:
        for method in ("none", "platt", "isotonic"):
            p = calibrate_predictions(raw_fit[idx], y_fit[idx], raw_validation, method, sample_weight=weights)
            key = f"{window_name}:{method}"
            if p is None:
                validation_results[key] = {"available": False, "reason": "INSUFFICIENT_CALIBRATION_DATA"}
            else:
                validation_results[key] = {"available": True, **_metrics(y_validation, p)}

    valid = [key for key, result in validation_results.items() if result.get("available")]
    if not valid:
        return {"available": False, "reason": "CALIBRATION_FAILED", "validation": validation_results}
    selected = min(valid, key=lambda key: validation_results[key]["brier"])
    window_name, method = selected.split(":", 1)
    selected_window = next(item for item in windows if item[0] == window_name)
    _, idx, weights = selected_window
    p_test = calibrate_predictions(raw_fit[idx], y_fit[idx], raw_test, method, sample_weight=weights)
    if p_test is None:
        return {"available": False, "reason": "CALIBRATION_FAILED", "validation": validation_results}
    return {
        "available": True,
        "selected": selected,
        "validation": validation_results,
        "test": _metrics(y_test, p_test),
        "selection_used_test": False,
    }



def calibration_decision(report: dict) -> str:
    """Return the PRD v2.3 explicit calibration state."""
    if not report.get("available"):
        return "FAIL"
    selected = str(report.get("selected") or report.get("winner") or "")
    method = selected.rsplit(":", 1)[-1] if selected else ""
    return "NO_CALIBRATION" if method == "none" else "PASS"
