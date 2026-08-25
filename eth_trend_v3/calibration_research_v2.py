from __future__ import annotations

import numpy as np

from .research_metrics import brier, calibration_error, log_loss


def calibrate_predictions(raw_cal, y_cal, raw_test, method: str):
    raw_cal = np.asarray(raw_cal, dtype=float)
    y_cal = np.asarray(y_cal, dtype=int)
    raw_test = np.asarray(raw_test, dtype=float)
    if method == "none":
        return raw_test
    if len(y_cal) < 20 or len(np.unique(y_cal)) < 2:
        return None
    if method == "platt":
        from sklearn.linear_model import LogisticRegression
        eps = 1e-6
        x = np.log(np.clip(raw_cal, eps, 1-eps) / np.clip(1-raw_cal, eps, 1-eps)).reshape(-1, 1)
        xt = np.log(np.clip(raw_test, eps, 1-eps) / np.clip(1-raw_test, eps, 1-eps)).reshape(-1, 1)
        return LogisticRegression(max_iter=1000, C=1.0).fit(x, y_cal).predict_proba(xt)[:, 1]
    if method == "isotonic":
        from sklearn.isotonic import IsotonicRegression
        return IsotonicRegression(out_of_bounds="clip").fit(raw_cal, y_cal).predict(raw_test)
    raise ValueError(method)


def compare_calibration(y_test, raw_test, raw_cal, y_cal, *, eligible: bool):
    if not eligible:
        return {"available": False, "reason": "CALIBRATION_NOT_ELIGIBLE"}
    out = {}
    for method in ("none", "platt", "isotonic"):
        p = calibrate_predictions(raw_cal, y_cal, raw_test, method)
        if p is None:
            out[method] = {"available": False, "reason": "INSUFFICIENT_CALIBRATION_DATA"}
            continue
        out[method] = {
            "available": True,
            "brier": brier(y_test, p),
            "log_loss": log_loss(y_test, p),
            "calibration_error": calibration_error(y_test, p),
        }
    valid = [m for m, v in out.items() if v.get("available")]
    if not valid:
        return {"available": False, "reason": "CALIBRATION_FAILED", "methods": out}
    winner = min(valid, key=lambda m: out[m]["brier"])
    return {"available": True, "winner": winner, "methods": out, "note": "NO_CALIBRATION is a formal candidate; calibration cannot rescue an ineligible raw model."}


def calibration_stability(validation_slices, *, method: str) -> dict:
    """Evaluate a preselected calibration method across validation slices.

    This function deliberately does not select a method using a final test set.
    Each slice contains raw_cal, y_cal, raw_eval and y_eval produced before the
    untouched final evaluation period.
    """
    scores = []
    for item in validation_slices:
        p = calibrate_predictions(item["raw_cal"], item["y_cal"], item["raw_eval"], method)
        if p is None:
            continue
        scores.append({
            "brier": brier(item["y_eval"], p),
            "log_loss": log_loss(item["y_eval"], p),
            "calibration_error": calibration_error(item["y_eval"], p),
            "n": len(item["y_eval"]),
        })
    if not scores:
        return {"available": False, "reason": "INSUFFICIENT_CALIBRATION_DATA", "method": method}
    return {
        "available": True,
        "method": method,
        "slices": scores,
        "mean_brier": float(np.mean([x["brier"] for x in scores])),
        "mean_log_loss": float(np.mean([x["log_loss"] for x in scores])),
        "mean_calibration_error": float(np.mean([x["calibration_error"] for x in scores if x["calibration_error"] is not None])),
        "selection_note": "stability evidence only; final untouched test must not be used to select calibration",
    }
