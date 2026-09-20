from __future__ import annotations

from datetime import datetime, timezone

from scripts.scheduled_monitor_watchdog import evaluate_runs


NOW = datetime(2026, 9, 20, 4, 0, tzinfo=timezone.utc)


def run(
    run_id: int,
    created_at: str,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    event: str = "schedule",
):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "status": status,
        "conclusion": conclusion,
        "event": event,
        "head_sha": "abc123",
        "html_url": f"https://example.invalid/{run_id}",
    }


def test_fresh_success_does_not_recover():
    decision = evaluate_runs(
        {"workflow_runs": [run(1, "2026-09-20T00:20:00Z")]},
        now=NOW,
    )
    assert decision.recovery_required is False
    assert decision.reason == "LATEST_SUCCESS_FRESH"
    assert decision.latest_success_age_hours == 3.667


def test_stale_success_requests_recovery():
    decision = evaluate_runs(
        {"workflow_runs": [run(1, "2026-09-19T22:20:00Z")]},
        now=NOW,
    )
    assert decision.recovery_required is True
    assert decision.reason == "LATEST_SUCCESS_STALE"
    assert decision.latest_success_age_hours == 5.667


def test_active_run_blocks_duplicate_recovery_even_when_success_is_stale():
    payload = {
        "workflow_runs": [
            run(2, "2026-09-20T03:58:00Z", status="in_progress", conclusion=None, event="workflow_dispatch"),
            run(1, "2026-09-19T22:20:00Z"),
        ]
    }
    decision = evaluate_runs(payload, now=NOW)
    assert decision.recovery_required is False
    assert decision.reason == "ACTIVE_MONITOR_RUN_PRESENT"
    assert decision.active_run["id"] == 2


def test_recent_failure_recovers_when_last_success_is_stale():
    payload = {
        "workflow_runs": [
            run(3, "2026-09-20T03:30:00Z", conclusion="failure"),
            run(1, "2026-09-19T22:20:00Z"),
        ]
    }
    decision = evaluate_runs(payload, now=NOW)
    assert decision.recovery_required is True
    assert decision.reason == "LATEST_SUCCESS_STALE"
    assert decision.latest_run["id"] == 3


def test_no_success_requests_recovery():
    decision = evaluate_runs(
        {"workflow_runs": [run(3, "2026-09-20T03:30:00Z", conclusion="failure")]},
        now=NOW,
    )
    assert decision.recovery_required is True
    assert decision.reason == "NO_SUCCESSFUL_MONITOR_RUN"
