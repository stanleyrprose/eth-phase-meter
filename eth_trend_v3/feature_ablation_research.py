from __future__ import annotations

from .probabilistic_research import evaluate_logistic


def run_group_ablation(folds, groups:dict[str,list[str]], *, horizon_bars:int, baseline_spec=None, bootstrap_reps:int=300):
    ordered=list(groups); selected=[]; sequential=[]
    for group in ordered:
        selected += [f for f in groups[group] if f not in selected]
        r=evaluate_logistic(folds,selected,horizon_bars=horizon_bars,baseline_spec=baseline_spec,bootstrap_reps=bootstrap_reps)
        sequential.append({"group":group,"features":list(selected),"result":r})
    full=list(selected); leave_one_out=[]
    for group in ordered:
        reduced=[f for f in full if f not in groups[group]]
        r=evaluate_logistic(folds,reduced,horizon_bars=horizon_bars,baseline_spec=baseline_spec,bootstrap_reps=bootstrap_reps)
        leave_one_out.append({"removed_group":group,"features":reduced,"result":r})
    survivors=[]
    for item in sequential:
        r=item["result"]
        if r.get("available") and r.get("passes_incremental_gate"): survivors.append(item["group"])
    return {"sequential":sequential,"leave_one_group_out":leave_one_out,"survivor_groups":survivors,"interpretation_note":"SHAP/coefficient importance may explain models but does not establish incremental predictive value."}
