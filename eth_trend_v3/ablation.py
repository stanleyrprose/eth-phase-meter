from __future__ import annotations
from .forecast import expanding_walk_forward, MODEL_LADDER

def run_ablation(rows):
    out=[]; prev=None
    for name,features in MODEL_LADDER:
        r=expanding_walk_forward(rows,features); m=r.get("metrics") or {}; b=m.get("brier")
        out.append({"model":name,"features":features,"available":r.get("available",False),"sample_size":r.get("sample_size",0),"brier":b,"log_loss":m.get("log_loss"),"brier_lift_vs_base":m.get("brier_lift"),"passes_baseline_gate":m.get("passes_baseline_gate",False),"incremental_brier":prev-b if prev is not None and b is not None else None})
        if b is not None:prev=b
    return out
