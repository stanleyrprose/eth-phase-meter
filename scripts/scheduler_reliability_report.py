from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from math import ceil
from pathlib import Path
import subprocess
from typing import Any, Mapping

from scripts.external_scheduler_dispatch import _parse_utc, bucket_start


def _successful_runs(payload: Mapping[str, Any], cadence_hours: int) -> dict[datetime, list[dict]]:
    buckets: dict[datetime, list[dict]] = {}
    for item in payload.get("workflow_runs", []):
        if str(item.get("status") or "").lower() != "completed":
            continue
        if str(item.get("conclusion") or "").lower() != "success":
            continue
        created = _parse_utc(item.get("created_at") or item.get("run_started_at"))
        if created is None:
            continue
        nominal = bucket_start(created, cadence_hours)
        buckets.setdefault(nominal, []).append(dict(item))
    return buckets


def _failed_runs(payload: Mapping[str, Any], cadence_hours: int) -> dict[datetime, list[dict]]:
    buckets: dict[datetime, list[dict]] = {}
    for item in payload.get("workflow_runs", []):
        if str(item.get("status") or "").lower() != "completed":
            continue
        conclusion = str(item.get("conclusion") or "").lower()
        if conclusion in {"", "success", "skipped", "neutral"}:
            continue
        created = _parse_utc(item.get("created_at") or item.get("run_started_at"))
        if created is None:
            continue
        nominal = bucket_start(created, cadence_hours)
        buckets.setdefault(nominal, []).append(dict(item))
    return buckets


def _expected_buckets(now: datetime, window_hours: int) -> list[datetime]:
    now = now.astimezone(timezone.utc)
    end = now.replace(minute=15, second=0, microsecond=0)
    if now.minute < 15:
        end -= timedelta(hours=1)
    return [end - timedelta(hours=offset) for offset in reversed(range(window_hours))]


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def evaluate_coverage(
    *,
    strategic_runs: Mapping[str, Any],
    tactical_runs: Mapping[str, Any],
    now: datetime,
    window_hours: int = 24,
    max_p95_delay_minutes: float = 15.0,
) -> dict:
    if window_hours <= 0:
        raise ValueError("window_hours must be positive")

    strategic_success = _successful_runs(strategic_runs, 4)
    tactical_success = _successful_runs(tactical_runs, 1)
    strategic_failures = _failed_runs(strategic_runs, 4)
    tactical_failures = _failed_runs(tactical_runs, 1)

    expected = _expected_buckets(now, window_hours)
    missing: list[str] = []
    duplicates: list[str] = []
    delays: list[float] = []
    covered = 0
    strategic_expected = 0
    tactical_expected = 0

    for nominal in expected:
        if nominal.hour % 4 == 0:
            strategic_expected += 1
            runs = strategic_success.get(nominal, [])
        else:
            tactical_expected += 1
            runs = tactical_success.get(nominal, [])

        if not runs:
            missing.append(nominal.isoformat())
            continue

        covered += 1
        if len(runs) > 1:
            duplicates.append(nominal.isoformat())
        first_created = min(
            _parse_utc(run.get("created_at") or run.get("run_started_at"))
            for run in runs
        )
        if first_created is not None:
            delays.append(max(0.0, (first_created - nominal).total_seconds() / 60.0))

    coverage_pct = round(100.0 * covered / len(expected), 2) if expected else 100.0
    p95_delay = _p95(delays)
    healthy = (
        not missing
        and not duplicates
        and (p95_delay is None or p95_delay <= max_p95_delay_minutes)
    )
    return {
        "kind": "SCHEDULER_RELIABILITY_AUDIT",
        "checked_at": now.astimezone(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "expected_buckets": len(expected),
        "strategic_expected": strategic_expected,
        "tactical_expected": tactical_expected,
        "covered_buckets": covered,
        "coverage_pct": coverage_pct,
        "missing_count": len(missing),
        "missing_buckets": missing,
        "duplicate_count": len(duplicates),
        "duplicate_buckets": duplicates,
        "p95_dispatch_delay_minutes": round(p95_delay, 2) if p95_delay is not None else None,
        "max_p95_delay_minutes": max_p95_delay_minutes,
        "strategic_failed_attempts": sum(len(v) for v in strategic_failures.values()),
        "tactical_failed_attempts": sum(len(v) for v in tactical_failures.values()),
        "healthy": healthy,
    }


def _gh_json(gh: str, repo: str, workflow: str) -> dict:
    completed = subprocess.run(
        [gh, "api", f"/repos/{repo}/actions/workflows/{workflow}/runs?branch=main&per_page=100"],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def _append_github_output(path: str | None, report: dict) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"healthy={'true' if report['healthy'] else 'false'}\n")
        handle.write(f"coverage_pct={report['coverage_pct']}\n")
        handle.write(f"missing_count={report['missing_count']}\n")
        value = report.get("p95_dispatch_delay_minutes")
        handle.write(f"p95_delay_minutes={'' if value is None else value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ETH 1H/4H sampling coverage from GitHub Actions runs.")
    parser.add_argument("--repo", default="stanleyrprose/eth-phase-meter")
    parser.add_argument("--gh", default="gh")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--max-p95-delay-minutes", type=float, default=15.0)
    parser.add_argument("--report", default="scheduler-reliability-report.json")
    parser.add_argument("--github-output")
    parser.add_argument("--now")
    args = parser.parse_args()

    now = _parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now must be valid ISO-8601")

    report = evaluate_coverage(
        strategic_runs=_gh_json(args.gh, args.repo, "scheduled-monitor.yml"),
        tactical_runs=_gh_json(args.gh, args.repo, "tactical-1h.yml"),
        now=now,
        window_hours=args.hours,
        max_p95_delay_minutes=args.max_p95_delay_minutes,
    )
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _append_github_output(args.github_output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
