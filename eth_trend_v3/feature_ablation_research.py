from __future__ import annotations

from .probabilistic_research import evaluate_logistic


def _sequential(folds, groups, order, *, horizon_bars, baseline_spec, bootstrap_reps):
    selected = []
    out = []
    for group in order:
        selected += [f for f in groups[group] if f not in selected]
        result = evaluate_logistic(
            folds,
            selected,
            horizon_bars=horizon_bars,
            baseline_spec=baseline_spec,
            bootstrap_reps=bootstrap_reps,
        )
        out.append({"group": group, "features": list(selected), "result": result})
    return out


def run_group_ablation(folds, groups: dict[str, list[str]], *, horizon_bars: int, baseline_spec=None, bootstrap_reps: int = 300):
    ordered = list(groups)
    sequential = _sequential(folds, groups, ordered, horizon_bars=horizon_bars, baseline_spec=baseline_spec, bootstrap_reps=bootstrap_reps)
    reverse = _sequential(folds, groups, list(reversed(ordered)), horizon_bars=horizon_bars, baseline_spec=baseline_spec, bootstrap_reps=bootstrap_reps)
    full = [f for group in ordered for f in groups[group] if f]
    full = list(dict.fromkeys(full))
    leave_one_out = []
    for group in ordered:
        reduced = [f for f in full if f not in groups[group]]
        result = evaluate_logistic(folds, reduced, horizon_bars=horizon_bars, baseline_spec=baseline_spec, bootstrap_reps=bootstrap_reps)
        leave_one_out.append({"removed_group": group, "features": reduced, "result": result})
    forward_pass = {x["group"]: bool(x["result"].get("passes_incremental_gate")) for x in sequential}
    reverse_pass = {x["group"]: bool(x["result"].get("passes_incremental_gate")) for x in reverse}
    robust_groups = [g for g in ordered if forward_pass.get(g) and reverse_pass.get(g)]
    return {
        "sequential": sequential,
        "reverse_order": reverse,
        "leave_one_group_out": leave_one_out,
        "survivor_groups": robust_groups,
        "order_robustness": {"forward_pass": forward_pass, "reverse_pass": reverse_pass, "robust_groups": robust_groups},
        "interpretation_note": "SHAP/coefficient importance may explain models but does not establish incremental predictive value.",
    }
