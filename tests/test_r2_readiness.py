from datetime import datetime, timezone

from eth_trend_v3.r2_readiness import assess_r2_readiness, render_r2_readiness_message


NOW = datetime(2026, 9, 23, 10, 30, tzinfo=timezone.utc)


def event(event_id, nominal, *, health="NORMAL", cohorts=None):
    return {
        "event_id": event_id,
        "event_version": "r2-tactical-v1",
        "nominal_time": nominal,
        "data_health": health,
        "cohorts": cohorts or [],
    }


def outcome(event_id, horizon, *, complete=True):
    return {
        "event_id": event_id,
        "horizon_hours": horizon,
        "path_complete": complete,
    }


def pit(nominal, price=2700.0):
    return {
        "observed_at": nominal.replace(":15:00", ":18:00"),
        "schedule_nominal_time": nominal,
        "metric_value": {"timeframe": "1h", "price": price},
        "workflow_run_id": "123",
    }


def test_readiness_counts_due_and_not_due_settlements():
    events = [
        event("e1", "2026-09-23T06:15:00+00:00", cohorts=["WEAK_BULL+PASS", "GATE_PASS"]),
        event("e2", "2026-09-23T07:15:00+00:00", cohorts=["GATE_PASS"]),
        event("e3", "2026-09-23T08:15:00+00:00", cohorts=["GATE_PASS"]),
        event("e4", "2026-09-23T09:15:00+00:00", cohorts=["GATE_PASS"]),
    ]
    outcomes = [
        outcome("e1", 1),
        outcome("e2", 1),
        outcome("e3", 1),
    ]
    pits = [
        pit("2026-09-23T06:15:00+00:00"),
        pit("2026-09-23T07:15:00+00:00"),
        pit("2026-09-23T08:15:00+00:00"),
        pit("2026-09-23T09:15:00+00:00"),
    ]

    report = assess_r2_readiness(events, outcomes, pits, now=NOW)

    assert report["operational_status"] == "HEALTHY"
    assert report["event_count"] == 4
    assert report["outcome_count"] == 3
    one = report["horizons"]["1"]
    assert one["due_count"] == 3
    assert one["settled_count"] == 3
    assert one["not_due_count"] == 1
    assert one["settlement_completeness_pct"] == 100.0
    assert report["horizons"]["4"]["due_count"] == 0
    assert report["cohorts"]["WEAK_BULL+PASS"] == 1


def test_missing_target_pit_degrades_without_claiming_blocked_integrity():
    events = [
        event("e1", "2026-09-23T06:15:00+00:00"),
        event("e2", "2026-09-23T07:15:00+00:00"),
    ]
    pits = [
        pit("2026-09-23T06:15:00+00:00"),
        pit("2026-09-23T08:15:00+00:00"),
    ]

    report = assess_r2_readiness(events, [], pits, now=NOW)

    assert report["operational_status"] == "DEGRADED"
    assert report["horizons"]["1"]["missing_target_pit"] == 1


def test_existing_target_without_outcome_blocks_as_settlement_lag():
    events = [event("e1", "2026-09-23T06:15:00+00:00")]
    pits = [
        pit("2026-09-23T06:15:00+00:00"),
        pit("2026-09-23T07:15:00+00:00"),
    ]

    report = assess_r2_readiness(events, [], pits, now=NOW)

    assert report["operational_status"] == "BLOCKED"
    assert report["integrity"]["settlement_lag_count"] == 1


def test_duplicate_event_bucket_blocks_integrity():
    events = [
        event("e1", "2026-09-23T06:15:00+00:00"),
        event("e2", "2026-09-23T06:15:00+00:00"),
    ]
    report = assess_r2_readiness(
        events,
        [],
        [pit("2026-09-23T06:15:00+00:00")],
        now=NOW,
    )

    assert report["operational_status"] == "BLOCKED"
    assert report["integrity"]["duplicate_event_bucket_count"] == 1


def test_degraded_events_are_counted_but_do_not_create_fake_sufficiency_gate():
    report = assess_r2_readiness(
        [event("e1", "2026-09-23T09:15:00+00:00", health="DEGRADED")],
        [],
        [pit("2026-09-23T09:15:00+00:00")],
        now=NOW,
    )

    assert report["degraded_event_count"] == 1
    assert report["research_status"] == "ACCUMULATING_EVIDENCE"
    assert report["evidence_sufficiency_gate"] == "NO_AUTO_SUFFICIENCY_GATE"


def test_message_is_compact_and_governance_explicit():
    report = assess_r2_readiness(
        [event("e1", "2026-09-23T09:15:00+00:00", cohorts=["GATE_PASS"])],
        [],
        [pit("2026-09-23T09:15:00+00:00")],
        now=NOW,
    )

    message = render_r2_readiness_message(report)

    assert "R2 Tactical Research Status" in message
    assert "ACCUMULATING_EVIDENCE" in message
    assert "GATE_PASS=1" in message
    assert "no auto-retuning" in message
