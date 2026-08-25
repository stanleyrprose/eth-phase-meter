from __future__ import annotations

import itertools
import numpy as np

from .dynamic_baseline import BaselineSpec, predict_baseline
from .hmm_production import causal_filter
from .probabilistic_research import evaluate_logistic
from .research_metrics import brier, brier_skill_score, calibration_error, log_loss, moving_block_delta_brier_ci, moving_block_sensitivity


def align_states(reference_profiles: list[dict], new_profiles: list[dict], keys=("mean_return", "volatility")) -> dict[int, int]:
    if len(reference_profiles) != len(new_profiles): raise ValueError("state counts differ")
    k=len(reference_profiles); best=None; best_cost=float("inf")
    for perm in itertools.permutations(range(k)):
        cost=sum((float(reference_profiles[i].get(key,0))-float(new_profiles[j].get(key,0)))**2 for i,j in enumerate(perm) for key in keys)
        if cost<best_cost: best_cost=cost; best=perm
    return {j:i for i,j in enumerate(best)}


def assert_causal_filter(params:dict,x:np.ndarray,extension:np.ndarray,atol:float=1e-10)->bool:
    base=causal_filter(x,params); ext=causal_filter(np.vstack([x,extension]),params)
    if not np.allclose(base,ext[:len(base)],atol=atol,rtol=0): raise AssertionError("HMM posterior is not causal")
    return True


def shrunk_regime_probability(y,regimes,current_regime,prior_strength:float=20.0)->float:
    y=np.asarray(y,dtype=float); r=np.asarray(regimes); global_p=float(y.mean()) if len(y) else .5; mask=r==current_regime; n=int(mask.sum())
    if n==0:return global_p
    regime_p=float(y[mask].mean()); lam=n/(n+prior_strength); return float(lam*regime_p+(1-lam)*global_p)


def regime_latency(regimes:list[str],stable_flags:list[bool])->dict:
    delays=[]; last=regimes[0] if regimes else None; pending=None
    for i,(regime,stable) in enumerate(zip(regimes,stable_flags)):
        if regime!=last and pending is None:pending=i
        if pending is not None and stable and regime!=last:delays.append(i-pending);last=regime;pending=None
    return {"switches_measured":len(delays),"mean_delay_bars":float(np.mean(delays)) if delays else None,"delays":delays}


def _evaluate_regime_baseline(folds,spec:BaselineSpec,horizon_bars:int,bootstrap_reps:int)->dict:
    ys=[];ps=[];globals_=[];oos=[]
    for fold_no,fold in enumerate(folds,start=1):
        train,test=fold["train"],fold["test"];y=np.asarray([int(r["target_up"]) for r in test],dtype=int);p=predict_baseline(train,test,spec);bp=predict_baseline(train,test,BaselineSpec("expanding"))
        ys.extend(y.tolist());ps.extend(p.tolist());globals_.extend(bp.tolist())
        for i,row in enumerate(test):oos.append({"key":str(row.get("feature_time") or row.get("timestamp") or f"fold{fold_no}-{i}"),"fold":fold_no,"target_up":int(y[i]),"probability":float(p[i])})
    if not ys:return {"available":False,"reason":"NO_VALID_FOLDS"}
    y=np.asarray(ys);p=np.asarray(ps);bp=np.asarray(globals_);ci=moving_block_delta_brier_ci(y,p,bp,horizon_bars,reps=bootstrap_reps);sensitivity=moving_block_sensitivity(y,p,bp,horizon_bars,reps=bootstrap_reps)
    return {"available":True,"metrics":{"brier":brier(y,p),"baseline_brier":brier(y,bp),"brier_skill":brier_skill_score(y,p,bp),"log_loss":log_loss(y,p),"calibration_error":calibration_error(y,p),"delta_brier_ci":ci,"block_sensitivity":sensitivity,"oos_n":len(y)},"oos_predictions":oos,"passes_vs_expanding":bool(brier(y,p)<brier(y,bp) and sensitivity.get("stable_positive"))}


def _paired_increment(candidate:dict|None,reference:dict|None,*,horizon_bars:int,bootstrap_reps:int)->dict:
    if not candidate or not reference or not candidate.get("available") or not reference.get("available"):return {"available":False,"reason":"MISSING_OOS_PREDICTIONS"}
    c={r["key"]:r for r in candidate.get("oos_predictions",[])};r={x["key"]:x for x in reference.get("oos_predictions",[])};keys=[k for k in c if k in r]
    if not keys:return {"available":False,"reason":"NO_COMMON_OOS_SAMPLES"}
    if any(c[k]["target_up"]!=r[k]["target_up"] for k in keys):return {"available":False,"reason":"OOS_TARGET_MISMATCH"}
    y=np.asarray([c[k]["target_up"] for k in keys]);cp=np.asarray([c[k]["probability"] for k in keys]);rp=np.asarray([r[k]["probability"] for k in keys]);delta=brier(y,rp)-brier(y,cp);ci=moving_block_delta_brier_ci(y,cp,rp,horizon_bars,reps=bootstrap_reps);sensitivity=moving_block_sensitivity(y,cp,rp,horizon_bars,reps=bootstrap_reps)
    return {"available":True,"oos_n":len(keys),"delta_brier_vs_no_regime":float(delta),"delta_brier_ci_vs_no_regime":ci,"block_sensitivity_vs_no_regime":sensitivity,"passes_incremental_gate":bool(delta>0 and sensitivity.get("stable_positive"))}


def evaluate_regime_conditioning(folds,base_features:list[str],*,posterior_features:list[str]|None,horizon_bars:int,regime_key:str="regime",bootstrap_reps:int=300)->dict:
    no_regime=evaluate_logistic(folds,base_features,horizon_bars=horizon_bars,bootstrap_reps=bootstrap_reps)
    hard=_evaluate_regime_baseline(folds,BaselineSpec("hard_regime",regime_key=regime_key),horizon_bars,bootstrap_reps)
    shrunk=_evaluate_regime_baseline(folds,BaselineSpec("shrunk_regime",regime_key=regime_key),horizon_bars,bootstrap_reps)
    soft=evaluate_logistic(folds,base_features+posterior_features,horizon_bars=horizon_bars,bootstrap_reps=bootstrap_reps) if posterior_features else None
    candidates={"hard_regime":hard,"shrunk_regime":shrunk,"soft_posterior":soft}
    incremental={name:_paired_increment(result,no_regime,horizon_bars=horizon_bars,bootstrap_reps=bootstrap_reps) for name,result in candidates.items() if result is not None}
    passing=[name for name,result in incremental.items() if result.get("passes_incremental_gate")]
    return {"no_regime":no_regime,"candidates":candidates,"incremental_vs_no_regime":incremental,"passing":passing,"forecast_role":"PREDICTIVE_CANDIDATE" if passing else "DESCRIPTIVE_ONLY","decision_rule":"Regime is predictive only if it beats the paired no-regime OOS model under stable 0.5H/1.0H/1.5H moving-block sensitivity."}
