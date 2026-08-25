from __future__ import annotations

import numpy as np


def brier(y, p) -> float:
    y = np.asarray(y, dtype=float); p = np.asarray(p, dtype=float)
    return float(np.mean((p-y)**2))


def log_loss(y, p) -> float:
    y = np.asarray(y, dtype=float); p = np.clip(np.asarray(p, dtype=float), 1e-6, 1-1e-6)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))


def brier_skill_score(y, p, baseline_p) -> float:
    base = brier(y, baseline_p)
    return float(1.0 - brier(y,p)/base) if base > 0 else 0.0


def calibration_error(y, p, bins: int = 10) -> float | None:
    y=np.asarray(y,dtype=float); p=np.asarray(p,dtype=float)
    if len(y)==0: return None
    edges=np.linspace(0,1,bins+1); total=0.0; n=0
    for lo,hi in zip(edges[:-1],edges[1:]):
        mask=(p>=lo)&(p<(hi if hi<1 else hi+1e-12))
        if mask.any():
            k=int(mask.sum()); total += k*abs(float(p[mask].mean()-y[mask].mean())); n += k
    return float(total/n) if n else None


def moving_block_delta_brier_ci(y, candidate, baseline, block: int, reps: int = 1000, seed: int = 17):
    y=np.asarray(y,dtype=float); c=np.asarray(candidate,dtype=float); b=np.asarray(baseline,dtype=float)
    if len(y)==0 or len(y)!=len(c) or len(y)!=len(b): return None
    block=max(1,min(int(block),len(y))); rng=np.random.default_rng(seed); vals=[]
    starts=np.arange(0,max(1,len(y)-block+1))
    for _ in range(reps):
        idx=[]
        while len(idx)<len(y):
            s=int(rng.choice(starts)); idx.extend(range(s,min(s+block,len(y))))
        idx=np.asarray(idx[:len(y)],dtype=int)
        vals.append(brier(y[idx],b[idx])-brier(y[idx],c[idx]))
    lo,hi=np.quantile(vals,[.025,.975])
    return {"low":float(lo),"high":float(hi),"mean":float(np.mean(vals)),"block":block,"reps":reps}


def effective_sample_diagnostic(n: int, horizon_bars: int) -> dict:
    # Conservative diagnostic, not a formal ESS estimator.
    return {"raw_n":int(n),"horizon_bars":int(horizon_bars),"conservative_nonoverlap_n":int(n//max(1,horizon_bars)),"kind":"DIAGNOSTIC"}
