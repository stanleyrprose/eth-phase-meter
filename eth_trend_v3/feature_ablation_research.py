from __future__ import annotations

from itertools import permutations

from .probabilistic_research import evaluate_logistic


def _score(result: dict) -> float | None:
    if not result.get("available"):
        return None
    return (result.get("metrics") or {}).get("brier_skill")


def run_group_ablation(
    folds,
    groups: dict[str, list[str]],
    *,
    horizon_bars: int,
    baseline_spec=None,
    bootstrap_reps: int = 300,
    robustness_permutations: int = 8,
):
    ordered = list(groups)
    selected = []
    sequential = []
    for group in ordered:
        selected += [f for f in groups[group] if f not in selected]
        result = evaluate_logistic(
            folds,
            selected,
            horizon_bars=horizon_bars,
            baseline_spec=baseline_spec,
            bootstrap_reps=bootstrap_reps,
        )
        sequential.append({"group": group, "features": list(selected), "result": result})

    full = list(selected)
    full_result = evaluate_logistic(
        folds,
        full,
        horizon_bars=horizon_bars,
        baseline_spec=baseline_spec,
        bootstrap_reps=bootstrap_reps,
    )
    leave_one_out = []
    for group in ordered:
        reduced = [f for f in full if f not in groups[group]]
        result = evaluate_logistic(
            folds,
            reduced,
            horizon_bars=horizon_bars,
            baseline_spec=baseline_spec,
            bootstrap_reps=bootstrap_reps,
        )
        leave_one_out.append({"removed_group": group, "features": reduced, "result": result})

    order_results = []
    candidate_orders = [tuple(ordered)]
    if len(ordered) > 1:
        candidate_orders.append(tuple(reversed(ordered)))
    for order in permutations(ordered):
        if order not in candidate_orders:
            candidate_orders.append(order)
        if len(candidate_orders) >= max(1, robustness_permutations):
            break

    for order in candidate_orders:
        acc = []
        steps = []
        for group in order:
            acc += [f for f in groups[group] if f not in acc]
            result = evaluate_logistic(
                folds,
                acc,
                horizon_bars=horizon_bars,
                baseline_spec=baseline_spec,
                bootstrap_reps=max(50, bootstrap_reps // 2),
            )
            steps.append({"group": group, "brier_skill": _score(result)})
        order_results.append({"order": list(order), "steps": steps})

    full_skill = _score(full_result)
    survivors = []
    rejected = []
    for item in leave_one_out:
        reduced_skill = _score(item["result"])
        group = item["removed_group"]
        if full_skill is not None and reduced_skill is not None and full_skill > reduced_skill:
            survivors.append(group)
        else:
            rejected.append(group)

    return {
        "sequential": sequential,
        "full_model": full_result,
        "leave_one_group_out": leave_one_out,
        "order_robustness": order_results,
        "survivor_groups": survivors,
        "rejected_groups": rejected,
        "interpretation_note": (
            "SHAP/coefficient importance may explain a fitted model but does not establish incremental predictive value; "
            "survival is based on OOS ablation evidence."
        ),
    }
