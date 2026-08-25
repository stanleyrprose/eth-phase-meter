from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

import numpy as np

from .research_contract import parse_utc
from .research_metrics import brier, brier_skill_score, calibration_error, log_loss, moving_block_delta_brier_ci


@dataclass(frozen=True)
class BaselineSpec:
    name: str
    window_days: int | None = None
    half_life_days: float | None = None
    prior_strength: float = 20.0
    min_regime_count: int = 10


def _targets(rows): return np.asarray([int(r["target_up"]) for r in rows],dtype=int)


def _times(rows): return [parse_utc(r.get("feature_time",r.get("timestamp"))) for r in rows]


def _regime_value(row):
    if row.get("regime") is not None: return row.get("regime")
    return row.get("regime_code")


def predict_baseline(train: Sequence[Mapping[str,Any]], test: Sequence[Mapping[str,Any]], spec: BaselineSpec) -> np.ndarray:
    if not train: raise ValueError("baseline requires training observations")
    y=_targets(train); times=_times(train); global_p=float(y.mean()); p=global_p
    if spec.name=="expanding":
        pass
    elif spec.name=="rolling":
        if not spec.window_days: raise ValueError("rolling baseline requires window_days")
        cutoff=max(times)-timedelta(days=spec.window_days); mask=np.asarray([t>=cutoff for t in times])
        if mask.any(): p=float(y[mask].mean())
    elif spec.name=="ewma":
        if not spec.half_life_days: raise ValueError("ewma baseline requires half_life_days")
        age=np.asarray([(max(times)-t).total_seconds()/86400 for t in times]); w=np.exp(-np.log(2)*age/spec.half_life_days)
        p=float(np.average(y,weights=w))
    elif spec.name in {"regime","shrunk-regime"}:
        train_reg=np.asarray([_regime_value(r) for r in train],dtype=object)
        out=[]
        for row in test:
            current=_regime_value(row); mask=train_reg==current; n=int(mask.sum())
            if current is None or n<spec.min_regime_count:
                out.append(global_p); continue
            regime_p=float(y[mask].mean())
            if spec.name=="shrunk-regime":
                lam=n/(n+max(spec.prior_strength,1e-9)); regime_p=lam*regime_p+(1-lam)*global_p
            out.append(regime_p)
        return np.clip(np.asarray(out,dtype=float),1e-6,1-1e-6)
    else: raise ValueError(f"unsupported baseline: {spec.name}")
    return np.full(len(test),np.clip(p,1e-6,1-1e-6),dtype=float)


def default_specs(include_regime:bool=False):
    specs=[BaselineSpec("expanding")]+[BaselineSpec("rolling",window_days=d) for d in (90,180,365)]+[BaselineSpec("ewma",half_life_days=d) for d in (30,60,90,180)]
    if include_regime: specs += [BaselineSpec("regime"),BaselineSpec("shrunk-regime")]
    return specs


def _key(spec:BaselineSpec)->str:
    if spec.window_days: return f"{spec.name}-{spec.window_days}d"
    if spec.half_life_days: return f"{spec.name}-{int(spec.half_life_days)}d"
    return spec.name


def evaluate_baselines(folds, specs=None, *, horizon_bars:int, bootstrap_reps:int=500) -> dict:
    specs=specs or default_specs(); store={_key(s):{"p":[],"y":[],"fold_brier":[]} for s in specs}
    for fold in folds:
        train,test=fold["train"],fold["test"]; y=_targets(test)
        for spec in specs:
            key=_key(spec); p=predict_baseline(train,test,spec); store[key]["p"].extend(p.tolist()); store[key]["y"].extend(y.tolist()); store[key]["fold_brier"].append(brier(y,p))
    if not any(v["y"] for v in store.values()): return {"available":False,"reason":"NO_VALID_FOLDS"}
    metrics={}; base_y=np.asarray(store["expanding"]["y"]); base_p=np.asarray(store["expanding"]["p"])
    for key,v in store.items():
        y=np.asarray(v["y"]); p=np.asarray(v["p"]); ci=moving_block_delta_brier_ci(y,p,base_p,horizon_bars,reps=bootstrap_reps) if len(y)==len(base_y) else None
        fold=np.asarray(v["fold_brier"],dtype=float); base_fold=np.asarray(store["expanding"]["fold_brier"],dtype=float)
        metrics[key]={"brier":brier(y,p),"brier_skill_vs_expanding":brier_skill_score(y,p,base_p),"log_loss":log_loss(y,p),"calibration_error":calibration_error(y,p),"fold_brier":v["fold_brier"],"fold_win_rate_vs_expanding":float(np.mean(fold<base_fold)) if len(fold)==len(base_fold) else None,"delta_brier_ci_vs_expanding":ci,"oos_n":len(y)}
    ranking=sorted(metrics,key=lambda k:(metrics[k]["brier"],0 if k=="expanding" else 1))
    winner=ranking[0]
    return {"available":True,"winner":winner,"runner_up":ranking[1] if len(ranking)>1 else None,"ranking":ranking,"metrics":metrics,"selection_rule":"Brier primary; inspect skill, CI and fold stability; uncertain ties prefer simpler baseline"}
