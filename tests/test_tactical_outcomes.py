from datetime import datetime, timezone

from eth_trend_v3.tactical_outcomes import (
    EVENT_VERSION,
    build_due_outcomes,
    build_tactical_event,
    tactical_cohorts,
    tactical_outcome_report,
)


def payload(
    *,
    observed="2026-09-23T05:18:00+00:00",
    nominal="2026-09-23T05:15:00+00:00",
    direction=-32,
    state="WEAK_BEAR",
    gate="WAIT",
    price=2700.0,
    triggers=None,
):
    return {
        "observed_at": observed,
        "schedule_nominal_time": nominal,
        "timestamp": "2026-09-23 05:18 UTC",
        "timeframe": "1h",
        "price": price,
        "rule_direction": direction,
        "tactical_state": state,
        "execution_gate": gate,
        "rule_regime": "TREND_DOWN",
        "coverage": 98.0,
        "data_health": {"status": "NORMAL"},
        "notification_decision": {"triggers": triggers or []},
        "pit_snapshot_id": "pit_1h_test.json",
    }


def pit(nominal, price, observed=None):
    observed = observed or nominal.replace(":15:00", ":18:00")
    return {
        "observed_at": observed,
        "schedule_nominal_time": nominal,
        "metric_value": {"timeframe": "1h", "price": price},
        "workflow_run_id": "123",
    }


def test_requested_state_gate_and_direction_cohorts():
    current = payload(
        direction=25,
        state="WEAK_BULL",
        gate="PASS",
        triggers=["DIRECTION_STRENGTHENING: +5→+25 (+20)", "GATE: WAIT→PASS"],
    )
    previous = payload(direction=5, state="NEUTRAL", gate="WAIT")

    cohorts = tactical_cohorts(current, previous)

    assert "WEAK_BULL+PASS" in cohorts
    assert "GATE_PASS" in cohorts
    assert "WAIT→PASS" in cohorts
    assert "CROSS_UP_+20" in cohorts
    assert "DIRECTION_STRENGTHENING" in cohorts


def test_negative_threshold_crossing_and_reversal_cohorts():
    current = payload(
        direction=-25,
        state="WEAK_BEAR",
        gate="PASS",
        triggers=["DIRECTION_REVERSAL: +25→-25 (-50)"],
    )
    previous = payload(direction=25, state="WEAK_BULL", gate="PASS")

    cohorts = tactical_cohorts(current, previous)

    assert "WEAK_BEAR+PASS" in cohorts
    assert "CROSS_DOWN_-20" in cohorts
    assert "CROSS_DOWN_+20" in cohorts
    assert "DIRECTION_REVERSAL" in cohorts


def test_out_of_band_observation_is_not_frozen_as_research_event():
    current = payload(
        observed="2026-09-23T05:57:00+00:00",
        nominal="2026-09-23T05:15:00+00:00",
    )
    event, status = build_tactical_event(current)

    assert event is None
    assert status["status"] == "SKIPPED_OUT_OF_BAND"


def test_event_id_is_deterministic_per_nominal_bucket(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    first, _ = build_tactical_event(payload(observed="2026-09-23T05:18:00+00:00"))
    second, _ = build_tactical_event(payload(observed="2026-09-23T05:20:00+00:00"))

    assert first["event_id"] == second["event_id"]
    assert first["event_version"] == EVENT_VERSION


def test_due_outcomes_use_exact_future_nominal_buckets_without_future_leakage():
    event, _ = build_tactical_event(
        payload(direction=30, state="WEAK_BULL", gate="PASS", price=100.0)
    )
    records = [
        pit("2026-09-23T06:15:00+00:00", 101.0),
        pit("2026-09-23T07:15:00+00:00", 99.0),
        pit("2026-09-23T08:15:00+00:00", 102.0),
        pit("2026-09-23T09:15:00+00:00", 104.0),
    ]

    outcomes = build_due_outcomes([event], records)

    one = next(row for row in outcomes if row["horizon_hours"] == 1)
    four = next(row for row in outcomes if row["horizon_hours"] == 4)
    assert one["target_price"] == 101.0
    assert one["actual_return"] == 0.01
    assert four["target_price"] == 104.0
    assert four["actual_return"] == 0.04
    assert four["path_bars"] == 4
    assert four["path_complete"] is True
    assert all(row["horizon_hours"] in {1, 4} for row in outcomes)


def test_due_outcomes_are_idempotent_against_existing_key():
    event, _ = build_tactical_event(payload(price=100.0))
    records = [pit("2026-09-23T06:15:00+00:00", 101.0)]

    outcomes = build_due_outcomes(
        [event],
        records,
        existing_keys={(event["event_id"], 1)},
    )

    assert outcomes == []


def test_report_is_descriptive_and_exposes_requested_cohort():
    event, _ = build_tactical_event(
        payload(direction=-30, state="WEAK_BEAR", gate="WAIT", price=100.0)
    )
    outcome = {
        "event_id": event["event_id"],
        "horizon_hours": 1,
        "actual_return": -0.02,
        "signal_aligned_return": 0.02,
        "mae": -0.03,
        "mfe": 0.01,
        "path_complete": True,
    }

    report = tactical_outcome_report([event], [outcome])

    assert report["research_only"] is True
    assert report["governance"]["auto_retuning"] is False
    cohort = report["horizons"]["1"]["cohorts"]["WEAK_BEAR+WAIT"]
    assert cohort["n"] == 1
    assert cohort["mean_forward_return"] == -0.02
    assert cohort["mean_signal_aligned_return"] == 0.02
