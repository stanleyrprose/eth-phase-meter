from datetime import datetime, timezone
from scripts.audit_meta_action_path_gaps import build_gap_audit

def pit(ts, price=100):
    return {
        "schedule_nominal_time": ts,
        "observed_at": ts,
        "metric_value": {"timeframe": "1h", "price": price},
        "workflow_run_id": 1,
    }

def test_distinguishes_settled_path_gap_missing_target_and_future():
    events=[{"event_id":"e1","nominal_time":"2026-09-30T00:00:00+00:00"}]
    outcomes=[{"event_id":"e1","horizon_hours":4}]
    pits=[pit("2026-09-30T01:00:00+00:00"), pit("2026-09-30T03:00:00+00:00"), pit("2026-09-30T04:00:00+00:00")]
    report=build_gap_audit(events,outcomes,pits,now=datetime(2026,9,30,13,tzinfo=timezone.utc))
    assert report["settled_path_missing_nominal_count"] == 1
    assert report["settled_path_missing_nominal_times"][0]["nominal_time"] == "2026-09-30T02:00:00+00:00"
    assert report["unsettled_missing_target_count"] == 1
    assert report["unsettled_missing_targets"][0]["horizon_hours"] == 12
    assert report["future_not_due_count"] == 2
