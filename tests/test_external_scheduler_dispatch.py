from datetime import datetime, timezone

from scripts.external_scheduler_dispatch import STRATEGIC_WORKFLOW, TACTICAL_WORKFLOW, bucket_start, decide


UTC = timezone.utc


def run(created_at: str, *, status="completed", conclusion="success"):
    return {"created_at": created_at, "status": status, "conclusion": conclusion}


def payload(*runs):
    return {"workflow_runs": list(runs)}


def test_bucket_start_preserves_nominal_minute():
    now = datetime(2026, 9, 21, 5, 20, tzinfo=UTC)
    assert bucket_start(now, 1).isoformat() == "2026-09-21T05:15:00+00:00"
    assert bucket_start(now, 4).isoformat() == "2026-09-21T04:15:00+00:00"


def test_non_boundary_hour_prioritizes_tactical_even_if_strategic_bucket_failed():
    decision = decide(
        now=datetime(2026, 9, 21, 21, 20, tzinfo=UTC),
        strategic_runs=payload(run("2026-09-21T20:20:00Z", conclusion="failure")),
        tactical_runs=payload(),
    )
    assert decision.action == "DISPATCH"
    assert decision.workflow == TACTICAL_WORKFLOW
    assert decision.reason == "TACTICAL_BUCKET_MISSING"


def test_boundary_hour_uses_fresh_strategic_run_for_1h_too():
    decision = decide(
        now=datetime(2026, 9, 21, 8, 20, tzinfo=UTC),
        strategic_runs=payload(run("2026-09-21T08:18:00Z")),
        tactical_runs=payload(),
    )
    assert decision.action == "SKIP"
    assert decision.reason == "STRATEGIC_RUN_COVERS_BOUNDARY_1H"


def test_missing_boundary_strategic_dispatches_strategic():
    decision = decide(
        now=datetime(2026, 9, 21, 8, 20, tzinfo=UTC),
        strategic_runs=payload(run("2026-09-21T04:20:00Z")),
        tactical_runs=payload(),
    )
    assert decision.action == "DISPATCH"
    assert decision.workflow == STRATEGIC_WORKFLOW


def test_non_boundary_hour_dispatches_missing_tactical_bucket():
    decision = decide(
        now=datetime(2026, 9, 21, 9, 20, tzinfo=UTC),
        strategic_runs=payload(run("2026-09-21T08:18:00Z")),
        tactical_runs=payload(run("2026-09-21T07:21:00Z")),
    )
    assert decision.action == "DISPATCH"
    assert decision.workflow == TACTICAL_WORKFLOW


def test_active_current_tactical_run_blocks_duplicate_dispatch():
    decision = decide(
        now=datetime(2026, 9, 21, 9, 22, tzinfo=UTC),
        strategic_runs=payload(),
        tactical_runs=payload(run("2026-09-21T09:20:00Z", status="in_progress", conclusion=None)),
    )
    assert decision.action == "SKIP"
    assert decision.reason == "CURRENT_BUCKET_ALREADY_COVERED"


def test_failed_current_tactical_attempt_blocks_retry_storm():
    decision = decide(
        now=datetime(2026, 9, 21, 9, 30, tzinfo=UTC),
        strategic_runs=payload(),
        tactical_runs=payload(run("2026-09-21T09:20:00Z", status="completed", conclusion="failure")),
    )
    assert decision.action == "SKIP"
    assert decision.reason == "TACTICAL_BUCKET_ALREADY_ATTEMPTED"


def test_failed_boundary_strategic_attempt_blocks_retry_storm():
    decision = decide(
        now=datetime(2026, 9, 21, 8, 30, tzinfo=UTC),
        strategic_runs=payload(run("2026-09-21T08:20:00Z", conclusion="failure")),
        tactical_runs=payload(),
    )
    assert decision.action == "SKIP"
    assert decision.reason == "STRATEGIC_BUCKET_ALREADY_ATTEMPTED"


def test_before_nominal_minute_does_not_dispatch_previous_bucket():
    decision = decide(
        now=datetime(2026, 9, 21, 9, 5, tzinfo=UTC),
        strategic_runs=payload(),
        tactical_runs=payload(),
    )
    assert decision.action == "SKIP"
    assert decision.reason == "BEFORE_NOMINAL_MINUTE"
