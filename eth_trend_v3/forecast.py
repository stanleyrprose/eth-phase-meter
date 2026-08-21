from __future__ import annotations
import numpy as np

DEFAULT_FEATURES=["trend","valuation","capital_flow","crowding","structural_supply","volatility_risk"]

def _matrix(rows,features):
    usable=[]
    for r in rows:
        vals=[r.get(f) for f in features]
        if any(v is None or not np.isfinite(v) for v in vals): continue
        usable.append(r)
    return usable,np.asarray([[r[f] for f in features] for r in usable],dtype=float),np.asarray([r["target_up"] for r in usable],dtype=int)

def _brier(y,p): return float(np.mean((p-y)**2))
def _logloss(y,p):
    p=np.clip(p,1e-6,1-1e-6)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def calibration_bins(y,p,bins=5):
    out=[]; edges=np.linspace(0,1,bins+1)
    for lo,hi in zip(edges[:-1],edges[1:]):
        mask=(p>=lo)&(p<(hi if hi<1 else hi+1e-9)); n=int(mask.sum())
        if n: out.append({"lo":round(float(lo),2),"hi":round(float(hi),2),"n":n,"predicted":round(float(p[mask].mean()),4),"actual":round(float(y[mask].mean()),4)})
    return out

def expanding_walk_forward(rows,features=None,min_train=120,test_size=24):
    features=features or DEFAULT_FEATURES; usable,X,y=_matrix(rows,features)
    if len(y)<min_train+test_size: return {"available":False,"reason":"INSUFFICIENT_CALIBRATION_DATA","sample_size":len(y)}
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.isotonic import IsotonicRegression
        from sklearn.preprocessing import StandardScaler
    except Exception:
        return {"available":False,"reason":"SKLEARN_UNAVAILABLE","sample_size":len(y)}
    pred=[]; actual=[]; base=[]
    for start in range(min_train,len(y),test_size):
        end=min(len(y),start+test_size); cal_n=max(20,int(start*.2)); fit_end=start-cal_n
        if fit_end<50: continue
        scaler=StandardScaler().fit(X[:fit_end]); model=LogisticRegression(max_iter=1000,C=.5).fit(scaler.transform(X[:fit_end]),y[:fit_end]); raw_cal=model.predict_proba(scaler.transform(X[fit_end:start]))[:,1]
        iso=IsotonicRegression(out_of_bounds="clip").fit(raw_cal,y[fit_end:start]); raw=model.predict_proba(scaler.transform(X[start:end]))[:,1]; pp=iso.predict(raw)
        pred.extend(pp.tolist()); actual.extend(y[start:end].tolist()); base.extend([float(y[:start].mean())]*(end-start))
    if not pred: return {"available":False,"reason":"NO_VALID_WALK_FORWARD_SPLITS","sample_size":len(y)}
    p=np.asarray(pred); yy=np.asarray(actual); bp=np.asarray(base); b=_brier(yy,p); bb=_brier(yy,bp)
    metrics={"brier":b,"log_loss":_logloss(yy,p),"accuracy":float(np.mean((p>=.5)==yy)),"base_rate_brier":bb,"base_rate_accuracy":float(np.mean((bp>=.5)==yy)),"brier_lift":float(bb-b),"calibration":calibration_bins(yy,p),"oos_n":len(yy)}
    metrics["passes_baseline_gate"]=bool(metrics["brier_lift"]>0 and metrics["oos_n"]>=60)
    return {"available":True,"sample_size":len(y),"metrics":metrics,"features":features}

def fit_live_probability(rows,current_features:dict,features=None):
    features=features or DEFAULT_FEATURES; wf=expanding_walk_forward(rows,features)
    if not wf.get("available") or not wf.get("metrics",{}).get("passes_baseline_gate"):
        return None,wf,wf.get("reason") or "MODEL_NOT_BETTER_THAN_BASE_RATE"
    usable,X,y=_matrix(rows,features); vals=[current_features.get(f) for f in features]
    if any(v is None or not np.isfinite(v) for v in vals): return None,wf,"CURRENT_FEATURE_COVERAGE_INSUFFICIENT"
    from sklearn.linear_model import LogisticRegression
    from sklearn.isotonic import IsotonicRegression
    from sklearn.preprocessing import StandardScaler
    cal_n=max(30,int(len(y)*.2)); fit_end=len(y)-cal_n; scaler=StandardScaler().fit(X[:fit_end]); model=LogisticRegression(max_iter=1000,C=.5).fit(scaler.transform(X[:fit_end]),y[:fit_end]); raw_cal=model.predict_proba(scaler.transform(X[fit_end:]))[:,1]; iso=IsotonicRegression(out_of_bounds="clip").fit(raw_cal,y[fit_end:]); raw=model.predict_proba(scaler.transform(np.asarray([vals],dtype=float)))[:,1]
    return float(iso.predict(raw)[0]),wf,""
