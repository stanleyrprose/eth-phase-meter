#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any
from eth_trend_v3.meta_action_outcomes import (
    HORIZON_HOURS, effective_meta_action_outcomes, load_meta_action_events,
    load_meta_action_outcomes, load_meta_action_outcome_revisions,
)

OVERRIDE_REASONS={"PHASE_BULLISH_TA_NEUTRAL":"ADD","PHASE_BEARISH_TA_NEUTRAL":"REDUCE"}

def _r(v): return round(float(v),8) if v is not None else None

def summary(rows):
    if not rows:
        return {"n":0,"mean_return":None,"median_return":None,"hit_rate":None,
                "mean_mae":None,"mean_mfe":None,"complete_path_n":0}
    vals=[float(o["actual_return"]) for _,o in rows]
    maes=[float(o["mae"]) for _,o in rows if o.get("path_complete") and o.get("mae") is not None]
    mfes=[float(o["mfe"]) for _,o in rows if o.get("path_complete") and o.get("mfe") is not None]
    return {"n":len(rows),"mean_return":_r(mean(vals)),"median_return":_r(median(vals)),
            "hit_rate":_r(sum(v>0 for v in vals)/len(vals)),
            "mean_mae":_r(mean(maes)) if maes else None,"mean_mfe":_r(mean(mfes)) if mfes else None,
            "complete_path_n":sum(bool(o.get("path_complete")) for _,o in rows)}

def aligned_summary(rows, side):
    vals=[float(o["actual_return"])*side for _,o in rows]
    return {"n":len(vals),"mean_aligned_return":_r(mean(vals)) if vals else None,
            "median_aligned_return":_r(median(vals)) if vals else None,
            "aligned_hit_rate":_r(sum(v>0 for v in vals)/len(vals)) if vals else None}

def evaluate(events,outcomes):
    by_event={str(e["event_id"]):e for e in events}
    joined=[(by_event[str(o["event_id"])],o) for o in outcomes if str(o.get("event_id")) in by_event]
    out={"status":"ACCUMULATING_EVIDENCE","research_only":True,
         "contract":"meta-action-outcome-evaluation-v1",
         "event_count":len(events),"effective_outcome_count":len(outcomes),
         "horizons":{},"counterfactual":{"old_rule":"TA-neutral Phase confirmation => HOLD",
         "new_rule":"TA-neutral Phase confirmation may => ADD/REDUCE",
         "note":"Same realized PIT outcome; deterministic policy replay, not a second market path."},
         "governance":{"auto_retuning":False,"auto_promotion":False,"threshold_change":False,
                       "sizing_change":False,"trading_execution":False,"minimum_override_n_for_review":30}}
    for h in HORIZON_HOURS:
        hr=[x for x in joined if int(x[1].get("horizon_hours") or 0)==h]
        overrides=[x for x in hr if any(r in OVERRIDE_REASONS for r in (x[0].get("reason_codes") or []))]
        bullish=[x for x in overrides if "PHASE_BULLISH_TA_NEUTRAL" in (x[0].get("reason_codes") or [])]
        bearish=[x for x in overrides if "PHASE_BEARISH_TA_NEUTRAL" in (x[0].get("reason_codes") or [])]
        holds=[x for x in hr if x[0].get("action")=="HOLD"]
        regimes=defaultdict(list)
        for row in overrides: regimes[str(row[0].get("phase_4h_regime") or "UNKNOWN")].append(row)
        strength={"25_to_39":[],"40_plus":[],"bear_20_to_39":[],"bear_40_plus":[]}
        for row in overrides:
            d=float(row[0].get("phase_4h_direction") or 0)
            if 25<=d<40: strength["25_to_39"].append(row)
            elif d>=40: strength["40_plus"].append(row)
            elif -40<d<=-20: strength["bear_20_to_39"].append(row)
            elif d<=-40: strength["bear_40_plus"].append(row)
        out["horizons"][str(h)]={
            "override_all":summary(overrides),"override_bullish":summary(bullish),
            "override_bearish":summary(bearish),"ordinary_hold":summary(holds),
            "override_policy_aligned":aligned_summary(bullish,1) | {"bearish":aligned_summary(bearish,-1)},
            "by_4h_regime":{k:summary(v) for k,v in sorted(regimes.items())},
            "by_4h_direction_strength":{k:summary(v) for k,v in strength.items()},
            "old_vs_new_counterfactual":{
                "override_n":len(overrides),
                "old_rule_directional_exposure":"HOLD/0",
                "new_rule_aligned_outcome":aligned_summary(bullish,1),
                "new_rule_bearish_aligned_outcome":aligned_summary(bearish,-1),
            }}
    override_events=[e for e in events if any(r in OVERRIDE_REASONS for r in (e.get("reason_codes") or []))]
    out["override_event_count"]=len(override_events)
    out["promotion_review_ready"]=len(override_events)>=30
    return out

def main():
    p=argparse.ArgumentParser(); p.add_argument("--database-url",default=os.getenv("DATABASE_URL"))
    p.add_argument("--report",default="eth_reports/governance/meta_action_evaluation_v1.json"); a=p.parse_args()
    if not a.database_url: raise SystemExit("DATABASE_URL is required")
    base=load_meta_action_outcomes(a.database_url)
    effective=effective_meta_action_outcomes(base,load_meta_action_outcome_revisions(a.database_url))
    report=evaluate(load_meta_action_events(a.database_url),effective)
    target=Path(a.report); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
