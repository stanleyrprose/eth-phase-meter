from __future__ import annotations
import numpy as np


def correlation_audit(rows: list[dict], keys: list[str] | None = None, threshold: float = 0.8) -> dict:
    keys=keys or ["trend","valuation","capital_flow","crowding","structural_supply","volatility_risk","cluster_momentum","cluster_derivatives_positioning","cluster_order_flow","cluster_options_positioning","cluster_sentiment","cluster_macro_risk"]
    usable=[k for k in keys if sum(isinstance(r.get(k),(int,float)) for r in rows)>=30]
    if len(usable)<2:
        return {"available":False,"reason":"INSUFFICIENT_OVERLAP","pairs":[]}
    matrix=[]
    for r in rows:
        vals=[r.get(k) for k in usable]
        if all(isinstance(v,(int,float)) and np.isfinite(v) for v in vals): matrix.append(vals)
    if len(matrix)<30:
        return {"available":False,"reason":"INSUFFICIENT_COMPLETE_ROWS","pairs":[]}
    corr=np.corrcoef(np.asarray(matrix,dtype=float),rowvar=False); pairs=[]
    for i in range(len(usable)):
        for j in range(i+1,len(usable)):
            v=float(corr[i,j])
            if abs(v)>=threshold: pairs.append({"a":usable[i],"b":usable[j],"correlation":round(v,4),"action":"CLUSTER_OR_DROP"})
    return {"available":True,"n":len(matrix),"keys":usable,"pairs":pairs}
