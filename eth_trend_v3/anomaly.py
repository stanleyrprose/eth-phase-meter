from __future__ import annotations
import numpy as np


def _robust_spike(current, history, threshold=4.0):
    vals=np.asarray([x for x in history if isinstance(x,(int,float)) and np.isfinite(x)],dtype=float)
    if len(vals)<20 or not isinstance(current,(int,float)):
        return False,None
    med=float(np.median(vals)); mad=float(np.median(np.abs(vals-med))) or 1.0
    z=abs((float(current)-med)/(1.4826*mad))
    return z>=threshold,round(z,2)


def detect(raw:dict, history:dict|None=None)->list[dict]:
    history=history or {}; out=[]; d=raw.get('derivatives') or {}
    checks=[('OI_JUMP',d.get('oi_change_window'),history.get('oi_change_window',[])),('LIQUIDATION_SPIKE',d.get('liquidation_total'),history.get('liquidation_total',[]))]
    for name,current,hist in checks:
        hit,z=_robust_spike(current,hist)
        if hit: out.append({'type':name,'severity':'HIGH','robust_z':z,'value':current})
    return out
