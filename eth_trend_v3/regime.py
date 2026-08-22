from __future__ import annotations
import math
import numpy as np


def deterministic(result)->dict:
    mapping={"TREND_UP":"Low-Vol Bull" if result.volatility<60 else "High-Vol Bull","TREND_DOWN":"High-Vol Bear","RANGE":"Low-Vol Sideways","VOL_EXPANSION":"High-Vol Bull" if result.final_direction>=0 else "High-Vol Bear","TRANSITION":"Transition","DATA_DEGRADED":"Data Degraded"}
    return {"engine":"deterministic-fallback","available":True,"regime":mapping.get(result.regime,result.regime),"probabilities":{},"stable":True,"reason":"HMM not validated/available"}


def _latest_candle(record):
    raw=record.get('raw_payload') or {}; candles=raw.get('candles')
    if isinstance(candles,list) and candles:
        return candles[-1]
    return None


def build_observations_from_pit(records:list[dict], current_raw:dict|None=None)->tuple[list[list[float]],list[float]|None]:
    points=[]
    for r in records:
        mv=r.get('metric_value') or {}
        if mv.get('timeframe')!='4h': continue
        c=_latest_candle(r); raw=r.get('raw_payload') or {}; deriv=raw.get('derivatives') or {}
        price=mv.get('price'); volume=(c or {}).get('volume'); oi=deriv.get('OI')
        if isinstance(price,(int,float)) and price>0:
            points.append((float(price),float(volume) if isinstance(volume,(int,float)) else None,float(oi) if isinstance(oi,(int,float)) else None))
    if current_raw:
        candles=current_raw.get('candles'); c=candles.iloc[-1].to_dict() if hasattr(candles,'iloc') and len(candles) else None; deriv=current_raw.get('derivatives') or {}
        price=(c or {}).get('close'); volume=(c or {}).get('volume'); oi=deriv.get('OI')
        if isinstance(price,(int,float)) and price>0:
            points.append((float(price),float(volume) if isinstance(volume,(int,float)) else None,float(oi) if isinstance(oi,(int,float)) else None))
    if len(points)<3: return [],None
    obs=[]; returns=[]
    for i in range(1,len(points)):
        p0,v0,o0=points[i-1]; p1,v1,o1=points[i]
        ret=math.log(p1/p0); returns.append(ret); rv=float(np.std(returns[-12:])) if len(returns)>=2 else 0.0
        vchg=(v1/v0-1) if v0 not in (None,0) and v1 is not None else 0.0
        oichg=(o1/o0-1) if o0 not in (None,0) and o1 is not None else 0.0
        obs.append([ret,rv,max(-5,min(5,vchg)),max(-5,min(5,oichg))])
    return obs[:-1],obs[-1]


def fit_hmm(observations:list[list[float]],current:list[float],n_states:int=4,random_state:int=7)->dict:
    if len(observations)<150: return {"engine":"hmm","available":False,"reason":"INSUFFICIENT_HISTORY"}
    try: from hmmlearn.hmm import GaussianHMM
    except Exception: return {"engine":"hmm","available":False,"reason":"HMMLEARN_UNAVAILABLE"}
    x=np.asarray(observations,dtype=float)
    if x.ndim!=2 or np.any(~np.isfinite(x)): return {"engine":"hmm","available":False,"reason":"INVALID_OBSERVATIONS"}
    model=GaussianHMM(n_components=n_states,covariance_type="diag",n_iter=300,random_state=random_state).fit(x)
    probs=model.predict_proba(np.asarray([current],dtype=float))[0]; means=model.means_; med=np.median(means[:,1]); order=np.argsort(means[:,0]); bear=int(order[0]); bull=int(order[-1]); labels={}
    labels[bear]="High-Vol Bear" if means[bear,1]>=med else "Low-Vol Bear"; labels[bull]="High-Vol Bull" if means[bull,1]>=med else "Low-Vol Bull"
    for i in range(n_states):
        if i not in labels: labels[i]="High-Vol Sideways" if means[i,1]>=med else "Low-Vol Sideways"
    top=max(range(n_states),key=lambda i:probs[i]); pmap={labels[i]:round(float(probs[i]),4) for i in range(n_states)}; stable=float(max(probs))>=.55
    return {"engine":"hmm","available":True,"regime":labels[top],"probabilities":pmap,"stable":stable,"reason":"" if stable else "REGIME_UNSTABLE","model_score":float(model.score(x)),"observation_schema":["log_return","realized_volatility","volume_change","oi_change"]}
