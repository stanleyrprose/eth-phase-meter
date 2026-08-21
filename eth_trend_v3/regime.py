from __future__ import annotations
import numpy as np

def deterministic(result)->dict:
    mapping={"TREND_UP":"Low-Vol Bull" if result.volatility<60 else "High-Vol Bull","TREND_DOWN":"High-Vol Bear","RANGE":"Low-Vol Sideways","VOL_EXPANSION":"High-Vol Bull" if result.final_direction>=0 else "High-Vol Bear","TRANSITION":"Transition","DATA_DEGRADED":"Data Degraded"}
    return {"engine":"deterministic-fallback","available":True,"regime":mapping.get(result.regime,result.regime),"probabilities":{},"stable":True,"reason":"HMM not validated/available"}

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
    return {"engine":"hmm","available":True,"regime":labels[top],"probabilities":pmap,"stable":stable,"reason":"" if stable else "REGIME_UNSTABLE","model_score":float(model.score(x))}
