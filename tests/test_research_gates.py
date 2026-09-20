from __future__ import annotations

from datetime import datetime, timedelta, timezone

from eth_trend_v3.research_gates import build_research_gate_snapshot


NOW = datetime(2026, 9, 20, 5, 0, tzinfo=timezone.utc)


def readiness(*, ready: tuple[str, ...] = ()) -> dict:
    return {
        "status": "READY_FOR_RESEARCH" if ready else "WAIT_FOR_MORE_PIT",
        "horizons": {
            horizon: {
                "labeled_row_n": {"3d": 111, "7d": 95, "30d": 0}[horizon],
                "minimum_walk_forward_rows": 144,
                "research_ready": horizon in ready,
                "production_eligible": False,
            }
            for horizon in ("3d", "7d", "30d")
        },
    }


def sizing(*, ready: bool = False) -> dict:
    return {
        "contract_version": "eth-sizing-research-v1",
        "status": (
            "READY_FOR_HUMAN_SIZING_REVIEW"
            if ready
            else "WAIT_FOR_MORE_PIT_SIZING_EVIDENCE"
        ),
        "raw_valid_intervals": 250 if ready else 74,
        "review_checkpoint_target_intervals": 250,
        "review_checkpoint_reached": ready,
        "canonical_4h_records": 123,
        "cohorts": [
            {"cohort": "all_pit_clean", "n_intervals": 68},
            {"cohort": "coverage_ge_threshold", "n_intervals": 30},
        ],
        "automatic_sizing_promotion_allowed": False,
    }


def pit(*, age_hours: float = 2.0, data_status: str = "NORMAL") -> dict:
    observed = NOW - timedelta(hours=age_hours)
    return {
        "observed_at": observed.isoformat(),
        "schedule_nominal_time": observed.replace(minute=15).isoformat(),
        "metric_value": {"timeframe": "4h", "price": 3000, "final_direction": 10},
        "coverage": 98.0,
        "quality_flags": {"data_status": data_status},
        "workflow_run_id": "123",
        "github_event": "schedule",
    }


def test_default_snapshot_stays_in_observation_freeze():
    report = build_research_gate_snapshot(
        readiness(),
        sizing(),
        [pit()],
        {"3d": None, "7d": None, "30d": None},
        now=NOW,
    )
    assert report["decision"]["status"] == "OBSERVE_AND_ACCUMULATE"
    assert report["decision"]["actionable"] is False
    assert report["decision"]["observation_freeze"] is True
    assert report["execution"]["paper_execution_allowed"] is False
    assert report["execution"]["live_execution_allowed"] is False


def test_forecast_readiness_becomes_actionable_without_production_claim():
    report = build_research_gate_snapshot(
        readiness(ready=("3d",)),
        sizing(),
        [pit()],
        {"3d": None, "7d": None, "30d": None},
        now=NOW,
    )
    assert report["decision"]["status"] == "FORECAST_RESEARCH_READY"
    assert report["milestones"]["forecast_research_ready_horizons"] == ["3d"]
    assert report["forecast"]["3d"]["production_approval"]["approved"] is False


def test_sizing_checkpoint_is_human_review_only():
    report = build_research_gate_snapshot(
        readiness(),
        sizing(ready=True),
        [pit()],
        {"3d": None, "7d": None, "30d": None},
        now=NOW,
    )
    assert report["decision"]["status"] == "HUMAN_SIZING_REVIEW_AVAILABLE"
    assert report["sizing"]["human_review_ready"] is True
    assert report["sizing"]["automatic_sizing_promotion_allowed"] is False
    assert report["execution"]["automatic_capital_allocation_allowed"] is False


def test_effective_production_approval_is_visible_but_does_not_enable_trading():
    approval = {
        "status": "PRODUCTION",
        "model_id": "forecast-3d",
        "model_version": "v1",
        "artifact_hash": "abc",
        "gate_version": "v1",
    }
    report = build_research_gate_snapshot(
        readiness(ready=("3d",)),
        sizing(),
        [pit()],
        {"3d": approval, "7d": None, "30d": None},
        now=NOW,
    )
    assert report["decision"]["status"] == "PRODUCTION_FORECAST_APPROVAL_PRESENT"
    assert report["milestones"]["production_approved_horizons"] == ["3d"]
    assert report["execution"]["paper_execution_allowed"] is False
    assert report["execution"]["live_execution_allowed"] is False


def test_stale_pit_has_priority_and_requests_engineering_attention():
    report = build_research_gate_snapshot(
        readiness(ready=("3d",)),
        sizing(ready=True),
        [pit(age_hours=6.0)],
        {"3d": None, "7d": None, "30d": None},
        now=NOW,
        pit_stale_after_hours=5.0,
    )
    assert report["pit"]["status"] == "STALE"
    assert report["pit"]["attention_required"] is True
    assert report["decision"]["status"] == "ENGINEERING_ATTENTION_REQUIRED"
