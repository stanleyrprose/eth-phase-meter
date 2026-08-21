from __future__ import annotations
import math
import numpy as np


def correlation_report(rows: list[dict], keys: list[str]) -> dict:
    usable=[]
    for r in rows:
        if all(isinstance(r.get(k),(int,float)) and np.isfinite(r.get(k)) for k in keys):
            usable.append([float(r[k]) for k in keys])
    if len(usable)<20:
        return {"available":False,"reason":"INSUFFICIENT_HISTORY","n":len(usable)}
    x=np.asarray(usable,dtype=float); corr=np.corrcoef(x,rowvar=False); pairs=[]
    for i in range(len(keys)):
        for j in range(i+1,len(keys)):
            c=float(corr[i,j])
            if abs(c)>=.8:pairs.append({"a":keys[i],"b":keys[j],"correlation":round(c,4),"redundant":True})
    return {"available":True,"n":len(usable),"keys":keys,"matrix":corr.round(4).tolist(),"high_correlation_pairs":pairs}


def validate_proxy(proxy: list[float], benchmark: list[float]) -> dict:
    n=min(len(proxy),len(benchmark))
    if n<30:return {"status":"GATED","kill":False,"reason":"INSUFFICIENT_BENCHMARK_HISTORY","n":n}
    p=np.asarray(proxy[-n:],dtype=float); b=np.asarray(benchmark[-n:],dtype=float); mask=np.isfinite(p)&np.isfinite(b); p=p[mask]; b=b[mask]
    if len(p)<30:return {"status":"GATED","kill":False,"reason":"INSUFFICIENT_VALID_PAIRS","n":len(p)}
    corr=float(np.corrcoef(p,b)[0,1]); p_hi=p>=np.quantile(p,.9); b_hi=b>=np.quantile(b,.9); p_lo=p<=np.quantile(p,.1); b_lo=b<=np.quantile(b,.1); extreme_overlap=float(((p_hi&b_hi)|(p_lo&b_lo)).sum()/max(1,(p_hi|p_lo).sum()))
    passed=bool(corr>=.6 and extreme_overlap>=.4)
    return {"status":"PASS" if passed else "KILL","kill":not passed,"correlation":corr,"extreme_overlap":extreme_overlap,"n":len(p),"reason":"" if passed else "Proxy failed benchmark correlation/extreme-zone gate"}


def kill_criteria(*, hmm_incremental_brier=None, regime_stable=True, sentiment_incremental_brier=None, proxy_validation=None) -> dict:
    return {
      "hmm":{"kill":bool(hmm_incremental_brier is not None and hmm_incremental_brier<=0) or not regime_stable,"reason":"No incremental forecast value or unstable regimes"},
      "social_sentiment":{"kill":bool(sentiment_incremental_brier is not None and sentiment_incremental_brier<=0),"reason":"No stable incremental Brier improvement"},
      "eth_cost_basis_proxy":{"kill":bool((proxy_validation or {}).get("kill")),"reason":(proxy_validation or {}).get("reason","Not validated")},
    }
