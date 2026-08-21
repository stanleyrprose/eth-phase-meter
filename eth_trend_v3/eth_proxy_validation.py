from __future__ import annotations
import numpy as np


def validate_proxy(benchmark: list[float], proxy: list[float], min_n: int = 60) -> dict:
    n=min(len(benchmark),len(proxy)); a=np.asarray(benchmark[-n:],dtype=float); b=np.asarray(proxy[-n:],dtype=float)
    mask=np.isfinite(a)&np.isfinite(b); a=a[mask]; b=b[mask]
    if len(a)<min_n: return {"available":False,"kill":False,"reason":"INSUFFICIENT_VALIDATION_SAMPLE","n":len(a)}
    corr=float(np.corrcoef(a,b)[0,1]); da=np.diff(a); db=np.diff(b); turning=float(np.mean(np.sign(da)==np.sign(db))) if len(da) else 0
    qa=np.quantile(a,[.1,.9]); qb=np.quantile(b,[.1,.9]); ea=(a<=qa[0])|(a>=qa[1]); eb=(b<=qb[0])|(b>=qb[1]); overlap=float(np.sum(ea&eb)/max(1,np.sum(ea|eb)))
    passed=bool(corr>=.6 and turning>=.55 and overlap>=.35)
    return {"available":True,"n":len(a),"correlation":corr,"turning_point_agreement":turning,"extreme_zone_overlap":overlap,"validation_passed":passed,"kill":not passed,"label_allowed":"ETH-SOPR" if passed else "EXPERIMENTAL_PROXY_ONLY"}
