import pytest

from eth_trend_v3.meta_action_outcomes import (
    EVENT_VERSION,
    build_due_meta_action_outcomes,
    build_meta_action_event,
    meta_action_outcome_report,
)


def monitor(price=2700.0, direction_4h=30.0):
    return {
        "1h": {"timestamp": "2026-09-27 04:16 UTC", "price": price, "rule_direction": 18},
        "4h": {"timestamp": "2026-09-27 04:16 UTC", "price": price, "rule_direction": direction_4h},
    }


def meta(action="ADD", ta="BUY", direction_4h=30.0):
    return {
        "contract_version": "eth-meta-decision-v1",
        "generated_at": "2026-09-27T04:39:00+00:00",
        "recommendation": action,
        "evidence_alignment": "HIGH" if action in {"ADD", "REDUCE"} else "MEDIUM",
        "reason_codes": ["TEST_REASON"],
        "sources": {
            "tradingagents": {"decision": ta, "fresh": True},
            "phase_meter": {
                "fresh": True,
                "1h": {"direction": 18.0, "coverage": 98, "regime": "Range"},
                "4h": {
                    "direction": direction_4h,
                    "coverage": 98,
                    "regime": "Trend",
                    "momentum": 25,
                    "order_flow": 10,
                    "options_positioning": -5,
                    "volatility_risk": 20,
                },
            },
        },
        "guardrails": {"order_execution_allowed": False},
    }


def pit(nominal, price):
    return {
        "observed_at": nominal.replace(":15:00", ":18:00"),
        "schedule_nominal_time": nominal,
        "metric_value": {"timeframe": "1h", "price": price},
        "workflow_run_id": "target-run",
    }


def test_event_freezes_action_and_reference_sides():
    event, status = build_meta_action_event(
        meta("ADD", "BUY", 30),
        monitor(direction_4h=30),
        monitor_run_id=123,
        monitor_git_sha="abc",
        notification={
            "status": "SKIPPED_UNCONFIGURED",
            "change_type": "UNCHANGED",
            "previous_recommendation": "ADD",
        },
    )

    assert status["status"] == "ELIGIBLE"
    assert event["event_version"] == EVENT_VERSION
    assert event["event_id"] == "meta-action-v1-20260927T0415Z"
    assert event["meta_side"] == 1
    assert event["phase_reference_side"] == 1
    assert event["tradingagents_reference_side"] == 1
    assert event["notification"]["fallback_requested"] is True
    assert event["guardrails"]["trading_execution"] is False


def test_hold_is_non_directional_but_preserves_reference_systems():
    event, _ = build_meta_action_event(
        meta("HOLD", "BUY", 25),
        monitor(direction_4h=25),
        monitor_run_id=123,
        monitor_git_sha="abc",
        notification={"status": "SENT"},
    )
    assert event["meta_side"] == 0
    assert event["phase_reference_side"] == 1
    assert event["tradingagents_reference_side"] == 1
    assert event["notification"]["fallback_requested"] is False


def test_due_outcomes_use_exact_future_1h_pit_for_4h_and_12h():
    event, _ = build_meta_action_event(
        meta("ADD", "BUY", 30),
        monitor(price=100.0, direction_4h=30),
        monitor_run_id=123,
        monitor_git_sha="abc",
    )
    records = []
    for offset in range(1, 13):
        hour = 4 + offset
        day = 27
        if hour >= 24:
            day += hour // 24
            hour %= 24
        nominal = f"2026-09-{day:02d}T{hour:02d}:15:00+00:00"
        records.append(pit(nominal, 100.0 + offset))

    outcomes = build_due_meta_action_outcomes([event], records)
    four = next(row for row in outcomes if row["horizon_hours"] == 4)
    twelve = next(row for row in outcomes if row["horizon_hours"] == 12)

    assert four["target_price"] == 104.0
    assert four["actual_return"] == pytest.approx(0.04)
    assert four["meta_aligned_return"] == pytest.approx(0.04)
    assert four["path_complete"] is True
    assert twelve["target_price"] == 112.0
    assert twelve["path_bars"] == 12
    assert all(row["horizon_hours"] in {4, 12} for row in outcomes)


def test_incomplete_path_keeps_exact_target_return_but_gates_mae_mfe():
    event, _ = build_meta_action_event(
        meta("ADD", "HOLD", 30),
        monitor(price=100.0, direction_4h=30),
        monitor_run_id=123,
        monitor_git_sha="abc",
    )
    records = [
        pit("2026-09-27T05:15:00+00:00", 101.0),
        # 06:15 is deliberately missing.
        pit("2026-09-27T07:15:00+00:00", 103.0),
        pit("2026-09-27T08:15:00+00:00", 104.0),
    ]
    outcomes = build_due_meta_action_outcomes([event], records)
    four = next(row for row in outcomes if row["horizon_hours"] == 4)

    assert four["actual_return"] == pytest.approx(0.04)
    assert four["target_price"] == 104.0
    assert four["path_complete"] is False
    assert four["path_bars"] == 3
    assert four["mae"] is None
    assert four["mfe"] is None
    assert four["missing_path_nominal_times"] == ["2026-09-27T06:15:00+00:00"]


def test_report_is_descriptive_and_does_not_select_a_winner():
    event, _ = build_meta_action_event(
        meta("REDUCE", "SELL", -30),
        monitor(price=100.0, direction_4h=-30),
        monitor_run_id=123,
        monitor_git_sha="abc",
    )
    outcome = {
        "event_id": event["event_id"],
        "horizon_hours": 4,
        "actual_return": -0.03,
        "absolute_return": 0.03,
        "meta_aligned_return": 0.03,
        "phase_reference_aligned_return": 0.03,
        "tradingagents_reference_aligned_return": 0.03,
        "mae": -0.04,
        "mfe": 0.01,
        "path_complete": True,
    }
    report = meta_action_outcome_report([event], [outcome])

    assert report["status"] == "ACCUMULATING_EVIDENCE"
    assert report["governance"]["auto_retuning"] is False
    assert report["governance"]["ranking_or_winner_selection"] is False
    assert report["horizons"]["4"]["actions"]["REDUCE"]["n"] == 1
    assert (
        report["horizons"]["4"]["reference_alignment"]["meta_directional"]["mean_aligned_return"]
        == 0.03
    )
