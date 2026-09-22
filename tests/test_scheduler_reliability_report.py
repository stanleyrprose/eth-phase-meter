from datetime import datetime, timezone

from scripts.scheduler_reliability_report import evaluate_coverage


UTC = timezone.utc


def run(created_at, *, status="completed", conclusion="success"):
    return {"created_at": created_at, "status": status, "conclusion": conclusion}


def test_coverage_counts_strategic_boundary_and_tactical_hours():
    strategic = {"workflow_runs": [
        run("2026-09-22T00:20:00Z"),
    ]}
    tactical = {"workflow_runs": [
        run("2026-09-22T01:20:00Z"),
        run("2026-09-22T02:20:00Z"),
        run("2026-09-22T03:20:00Z"),
    ]}

    report = evaluate_coverage(
        strategic_runs=strategic,
        tactical_runs=tactical,
        now=datetime(2026, 9, 22, 3, 30, tzinfo=UTC),
        window_hours=4,
    )

    assert report["expected_buckets"] == 4
    assert report["covered_buckets"] == 4
    assert report["coverage_pct"] == 100.0
    assert report["p95_dispatch_delay_minutes"] == 5.0
    assert report["healthy"] is True


def test_missing_bucket_fails_audit():
    report = evaluate_coverage(
        strategic_runs={"workflow_runs": [run("2026-09-22T00:20:00Z")]},
        tactical_runs={"workflow_runs": [run("2026-09-22T01:20:00Z")]},
        now=datetime(2026, 9, 22, 3, 30, tzinfo=UTC),
        window_hours=4,
    )
    assert report["missing_count"] == 2
    assert report["healthy"] is False
