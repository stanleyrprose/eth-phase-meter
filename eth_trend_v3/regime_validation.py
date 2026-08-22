from __future__ import annotations
from .forecast import expanding_walk_forward


def validate_regime_increment(rows_without_regime:list[dict], rows_with_regime:list[dict])->dict:
    base=expanding_walk_forward(rows_without_regime,['trend','crowding','volatility_risk'])
    candidate=expanding_walk_forward(rows_with_regime,['trend','crowding','volatility_risk','regime_code'])
    bm=(base.get('metrics') or {}).get('brier'); cm=(candidate.get('metrics') or {}).get('brier')
    if bm is None or cm is None:
        return {'status':'GATED','reason':'INSUFFICIENT_VALIDATION_DATA','promotion':False}
    improvement=bm-cm
    return {'status':'PASS' if improvement>0 else 'KILL','base_brier':bm,'candidate_brier':cm,'incremental_brier':improvement,'promotion':bool(improvement>0)}
