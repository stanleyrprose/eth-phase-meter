from __future__ import annotations
from .forecast import fit_live_probability, expanding_walk_forward

MODEL_LADDER = [
    ("baseline-1-momentum", ["trend"]),
    ("baseline-2-tech-derivatives", ["trend", "cluster_derivatives_positioning", "cluster_order_flow"]),
    ("baseline-3-plus-structural", ["trend", "cluster_derivatives_positioning", "cluster_order_flow", "structural_supply"]),
    ("model-5-plus-eth-state", ["trend", "cluster_derivatives_positioning", "cluster_order_flow", "structural_supply", "valuation", "capital_flow"]),
]

def select_live_model(rows: list[dict], current: dict) -> dict:
    candidates=[]
    for name,features in MODEL_LADDER:
        p,wf,reason=fit_live_probability(rows,current,features)
        metrics=wf.get("metrics") or {}
        candidates.append({"name":name,"features":features,"probability":p,"walk_forward":wf,"reason":reason,"brier":metrics.get("brier"),"passes":bool(p is not None and metrics.get("passes_baseline_gate"))})
    eligible=[c for c in candidates if c["passes"]]
    # Prefer the simplest model unless a more complex model improves OOS Brier by >= 0.005.
    selected=None
    for c in eligible:
        if selected is None:
            selected=c
        elif c.get("brier") is not None and selected.get("brier") is not None and selected["brier"]-c["brier"]>=0.005:
            selected=c
    return {"selected":selected,"candidates":candidates}
