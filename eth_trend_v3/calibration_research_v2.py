from __future__ import annotations

import numpy as np

from .research_metrics import brier, calibration_error, log_loss


def calibrate_predictions(raw_cal, y_cal, raw_test, method:str):
    raw_cal=np.asarray(raw_cal,dtype=float); y_cal=np.asarray(y_cal,dtype=int); raw_test=np.asarray(raw_test,dtype=float)
    if method=="none": return raw_test
    if len(y_cal)<20 or len(np.unique(y_cal))<2: return None
    if method=="platt":
        from sklearn.linear_model import LogisticRegression
        eps=1e-6; x=np.log(np.clip(raw_cal,eps,1-eps)/np.clip(1-raw_cal,eps,1-eps)).reshape(-1,1); xt=np.log(np.clip(raw_test,eps,1-eps)/np.clip(1-raw_test,eps,1-eps)).reshape(-1,1)
        return LogisticRegression(max_iter=1000,C=1.0).fit(x,y_cal).predict_proba(xt)[:,1]
    if method=="isotonic":
        from sklearn.isotonic import IsotonicRegression
        return IsotonicRegression(out_of_bounds="clip").fit(raw_cal,y_cal).predict(raw_test)
    raise ValueError(method)


def _method_metrics(y,p): return {"brier":brier(y,p),"log_loss":log_loss(y,p),"calibration_error":calibration_error(y,p)}


def compare_calibration(y_test, raw_test, raw_cal, y_cal, *, eligible:bool):
    if not eligible: return {"available":False,"reason":"CALIBRATION_NOT_ELIGIBLE"}
    out={}
    for method in ("none","platt","isotonic"):
        p=calibrate_predictions(raw_cal,y_cal,raw_test,method)
        if p is None: out[method]={"available":False,"reason":"INSUFFICIENT_CALIBRATION_DATA"}; continue
        out[method]={"available":True,**_method_metrics(y_test,p)}
    valid=[m for m,v in out.items() if v.get("available")]
    if not valid: return {"available":False,"reason":"CALIBRATION_FAILED","methods":out}
    winner=min(valid,key=lambda m:out[m]["brier"])
    return {"available":True,"winner":winner,"methods":out,"note":"NO_CALIBRATION is a formal candidate; calibration cannot rescue an ineligible raw model."}


def compare_calibration_windows(y, raw, *, train_end:int, test_start:int, rolling_windows=(60,120), eligible:bool=True):
    """Compare calibration windows without using final-test outcomes for fitting.

    raw[0:train_end] is model-training history (not consumed here),
    raw[train_end:test_start] is the expanding calibration pool, and
    raw[test_start:] is final evaluation only.
    """
    y=np.asarray(y,dtype=int); raw=np.asarray(raw,dtype=float)
    if not eligible: return {"available":False,"reason":"CALIBRATION_NOT_ELIGIBLE"}
    if not (0<train_end<test_start<len(y)): return {"available":False,"reason":"INVALID_CALIBRATION_SPLIT"}
    candidates={"expanding":(raw[train_end:test_start],y[train_end:test_start])}
    for w in rolling_windows:
        start=max(train_end,test_start-int(w)); candidates[f"rolling-{int(w)}"]=(raw[start:test_start],y[start:test_start])
    reports={}
    for name,(rc,yc) in candidates.items(): reports[name]=compare_calibration(y[test_start:],raw[test_start:],rc,yc,eligible=True)
    valid=[k for k,v in reports.items() if v.get("available")]
    if not valid: return {"available":False,"reason":"CALIBRATION_FAILED","windows":reports}
    winner=min(valid,key=lambda k:reports[k]["methods"][reports[k]["winner"]]["brier"])
    return {"available":True,"winner_window":winner,"windows":reports}
