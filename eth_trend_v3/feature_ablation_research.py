from __future__ import annotations

from collections import OrderedDict

from .probabilistic_research import evaluate_logistic


def _sequential(folds, groups, *, horizon_bars, baseline_spec, bootstrap_reps):
    selected = []
    out = []
    for group, features in groups.items():
        selected += [f for f in features if f not in selected]
        result = evaluate_logistic(folds, selected, horizon_bars=horizon_bars, baseline_spec=baseline_spec, bootstrap_reps=bootstrap_reps)
        out.append({"group": group, "features": list(selected), "result": result})
    return out


def run_group_ablation(folds, groups: dict[str, list[str]], *, horizon_bars: int, baseline_spec=None, bootstrap_reps: int = 300):
    ordered = OrderedDict(groups)
    sequential = _sequential(folds, ordered, horizon_bars=horizon_bars, baseline_spec=baseline_spec, bootstrap_reps=bootstrap_reps)
    full = [f for features in ordered.values() for f in features]
    full = list(dict.fromkeys(full))
    leave_one_out = []
    for group in ordered:
        reduced = [f for f in full if f not in ordered[group]]
        result = evaluate_logistic(folds, reduced, horizon_bars=horizon_bars, baseline_spec=baseline_spec, bootstrap_reps=bootstrap_reps)
        leave_one_out.append({"removed_group": group, "features": reduced, "result": result})

    reverse_groups = OrderedDict(reversed(list(ordered.items())))
    reverse = _sequential(folds, reverse_groups, horizon_bars=horizon_bars, baseline_spec=baseline_spec, bootstrap_reps=bootstrap_reps)
    forward_pass = {x["group"]: bool(x["result"].get("passes_incremental_gate")) for x in sequential}
    reverse_pass = {x["group"]: bool(x["result"].get("passes_incremental_gate")) for x in reverse}
    order_robust = {g: forward_pass.get(g) == reverse_pass.get(g) for g in ordered}

    survivors = [g for g in ordered if forward_pass.get(g) and reverse_pass.get(g)]
    return {
        "sequential": sequential,
        "reverse_sequential": reverse,
        "leave_one_group_out": leave_one_out,
        "order_robustness": order_robust,
        "survivor_groups": survivors,
        "interpretation_note": "SHAP/coefficient importance may explain models but does not establish incremental predictive value; survivors must be robust to at least forward/reverse ordering.",
    }
