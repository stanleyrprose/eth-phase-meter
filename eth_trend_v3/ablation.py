from __future__ import annotations
from .forecast import expanding_walk_forward
ABLATIONS={"BasePrice":["trend"],"Technical+Risk":["trend","crowding","volatility_risk"],"+CapitalFlow":["trend","crowding","volatility_risk","capital_flow"],"+Structural":["trend","crowding","volatility_risk","capital_flow","structural_supply"],"+Valuation":["trend","crowding","volatility_risk","capital_flow","structural_supply","valuation"]}
def run_ablation(rows):
    out=[]; prev=None
    for name,features in ABLATIONS.items():
        r=expanding_walk_forward(rows,features); m=r.get("metrics") or {}; b=m.get("brier"); out.append({"model":name,"features":features,"available":r.get("available",False),"sample_size":r.get("sample_size",0),"brier":b,"log_loss":m.get("log_loss"),"brier_lift_vs_base":m.get("brier_lift"),"incremental_brier":prev-b if prev is not None and b is not None else None}); prev=b if b is not None else prev
    return out
