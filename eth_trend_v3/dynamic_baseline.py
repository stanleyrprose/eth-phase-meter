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


def _targets(rows): return np.asarray([int(r["target_up"]) for r in rows],dtype=int)


def _times(rows): return [parse_utc(r.get("feature_time",r.get("timestamp"))) for r in rows]


def predict_baseline(train: Sequence[Mapping[str,Any]], test: Sequence[Mapping[str,Any]], spec: BaselineSpec) -> np.ndarray:
    if not train: raise ValueError("baseline requires training observations")
    y=_targets(train); times=_times(train); p=float(y.mean())
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
    else: raise ValueError(f"unsupported baseline: {spec.name}")
    return np.full(len(test),np.clip(p,1e-6,1-1e-6),dtype=float)


def default_specs():
    return [BaselineSpec("expanding")]+[BaselineSpec("rolling",window_days=d) for d in (90,180,365)]+[BaselineSpec("ewma",half_life_days=d) for d in (30,60,90,180)]


def evaluate_baselines(folds, specs=None, *, horizon_bars:int, bootstrap_reps:int=500) -> dict:
    specs=specs or default_specs(); store={s.name+(f"-{s.window_days}d" if s.window_days else f"-{int(s.half_life_days)}d" if s.half_life_days else ""):{"p":[],"y":[],"fold_brier":[]} for s in specs}
    for fold in folds:
        train,test=fold["train"],fold["test"]; y=_targets(test)
        for spec,key in zip(specs,store):
            p=predict_baseline(train,test,spec); store[key]["p"].extend(p.tolist()); store[key]["y"].extend(y.tolist()); store[key]["fold_brier"].append(brier(y,p))
    if not any(v["y"] for v in store.values()): return {"available":False,"reason":"NO_VALID_FOLDS"}
    metrics={}
    expanding_key=next(k for k in store if k=="expanding")
    base_y=np.asarray(store[expanding_key]["y"]); base_p=np.asarray(store[expanding_key]["p"])
    for key,v in store.items():
        y=np.asarray(v["y"]); p=np.asarray(v["p"])
        ci=moving_block_delta_brier_ci(y,p,base_p,horizon_bars,reps=bootstrap_reps) if len(y)==len(base_y) else None
        metrics[key]={"brier":brier(y,p),"brier_skill_vs_expanding":brier_skill_score(y,p,base_p),"log_loss":log_loss(y,p),"calibration_error":calibration_error(y,p),"fold_brier":v["fold_brier"],"delta_brier_ci_vs_expanding":ci,"oos_n":len(y)}
    ranking=sorted(metrics,key=lambda k:(metrics[k]["brier"],0 if k=="expanding" else 1))
    winner=ranking[0]
    return {"available":True,"winner":winner,"ranking":ranking,"metrics":metrics,"selection_rule":"lowest Brier; ties prefer simpler expanding; inspect CI/stability before promotion"}
