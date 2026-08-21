from __future__ import annotations
import numpy as np

def detect_feature_drift(history,current,keys=None):
    keys=keys or ["trend","valuation","capital_flow","crowding","structural_supply","volatility_risk"]; flags=[]
    for k in keys:
        vals=np.asarray([r.get(k) for r in history[-180:] if isinstance(r.get(k),(int,float))],dtype=float); v=current.get(k)
        if len(vals)<40 or not isinstance(v,(int,float)): continue
        med=float(np.median(vals)); mad=float(np.median(np.abs(vals-med))) or 1.; rz=abs((float(v)-med)/(1.4826*mad))
        if rz>4: flags.append({"feature":k,"robust_z":round(rz,2)})
    return {"status":"MODEL_DEGRADED" if flags else "NORMAL","flags":flags}
