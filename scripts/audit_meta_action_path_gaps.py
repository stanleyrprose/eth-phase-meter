#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from eth_trend_v3.meta_action_outcomes import HORIZON_HOURS, load_meta_action_events, load_meta_action_outcomes
from eth_trend_v3.tactical_outcomes import _canonical_1h_prices, _parse_time, load_tactical_price_records

def build_gap_audit(events, outcomes, pit_records, *, now=None):
    now = now or datetime.now(timezone.utc)
    prices = _canonical_1h_prices(pit_records)
    settled = {(str(o.get("event_id")), int(o.get("horizon_hours") or 0)): o for o in outcomes}
    gaps = {}
    unsettled_missing_targets = []
    future_not_due = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        nominal = _parse_time(event["nominal_time"])
        for horizon in HORIZON_HOURS:
            target = nominal + timedelta(hours=horizon)
            key = (event_id, horizon)
            if key in settled:
                missing = [nominal + timedelta(hours=i) for i in range(1, horizon + 1)
                           if nominal + timedelta(hours=i) not in prices]
                for ts in missing:
                    item = gaps.setdefault(ts.isoformat(), {"nominal_time": ts.isoformat(), "affected": []})
                    item["affected"].append({"event_id": event_id, "horizon_hours": horizon})
            elif target > now:
                future_not_due.append({"event_id": event_id, "horizon_hours": horizon, "target_nominal_time": target.isoformat()})
            elif target not in prices:
                unsettled_missing_targets.append({"event_id": event_id, "horizon_hours": horizon, "target_nominal_time": target.isoformat()})
    ordered = sorted(gaps.values(), key=lambda x: x["nominal_time"])
    return {
        "status": "GAPS_FOUND" if ordered or unsettled_missing_targets else "COMPLETE",
        "research_only": True,
        "settled_path_missing_nominal_count": len(ordered),
        "settled_path_missing_nominal_times": ordered,
        "unsettled_missing_target_count": len(unsettled_missing_targets),
        "unsettled_missing_targets": unsettled_missing_targets,
        "future_not_due_count": len(future_not_due),
        "future_not_due": future_not_due,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    p.add_argument("--report", default="eth_reports/governance/meta_action_path_gap_audit.json")
    a=p.parse_args()
    if not a.database_url: raise SystemExit("DATABASE_URL is required")
    report=build_gap_audit(load_meta_action_events(a.database_url), load_meta_action_outcomes(a.database_url), load_tactical_price_records(a.database_url))
    target=Path(a.report); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
