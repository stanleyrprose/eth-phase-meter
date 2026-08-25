from __future__ import annotations

from itertools import permutations

from .probabilistic_research import evaluate_logistic


def _sequential(folds, ordered_groups, groups, *, horizon_bars, baseline_spec, bootstrap_reps):
    selected=[]; out=[]
    for group in ordered_groups:
        selected += [f for f in groups[group] if f not in selected]
        r=evaluate_logistic(folds,selected,horizon_bars=horizon_bars,baseline_spec=baseline_spec,bootstrap_reps=bootstrap_reps)
        out.append({"group":group,"features":list(selected),"result":r})
    return out


def run_group_ablation(folds, groups:dict[str,list[str]], *, horizon_bars:int, baseline_spec=None, bootstrap_reps:int=300, max_order_checks:int=6):
    ordered=list(groups); sequential=_sequential(folds,ordered,groups,horizon_bars=horizon_bars,baseline_spec=baseline_spec,bootstrap_reps=bootstrap_reps)
    full=[]
    for group in ordered: full += [f for f in groups[group] if f not in full]
    leave_one_out=[]
    for group in ordered:
        reduced=[f for f in full if f not in groups[group]]
        r=evaluate_logistic(folds,reduced,horizon_bars=horizon_bars,baseline_spec=baseline_spec,bootstrap_reps=bootstrap_reps)
        leave_one_out.append({"removed_group":group,"features":reduced,"result":r})
    survivors=[x["group"] for x in sequential if x["result"].get("available") and x["result"].get("passes_incremental_gate")]
    order_checks=[]
    candidate_orders=[tuple(ordered),tuple(reversed(ordered))]
    if len(ordered)<=4:
        candidate_orders=list(permutations(ordered))[:max_order_checks]
    seen=set()
    for order in candidate_orders:
        if order in seen: continue
        seen.add(order); seq=_sequential(folds,list(order),groups,horizon_bars=horizon_bars,baseline_spec=baseline_spec,bootstrap_reps=bootstrap_reps)
        order_checks.append({"order":list(order),"passing_groups":[x["group"] for x in seq if x["result"].get("passes_incremental_gate")]})
    stability={g:sum(g in x["passing_groups"] for x in order_checks)/len(order_checks) for g in ordered} if order_checks else {}
    return {"sequential":sequential,"leave_one_group_out":leave_one_out,"survivor_groups":survivors,"order_robustness":{"checks":order_checks,"pass_rate_by_group":stability},"interpretation_note":"SHAP/coefficient importance may explain models but does not establish incremental predictive value."}
