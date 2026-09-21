from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import subprocess
from typing import Any, Mapping


ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
STRATEGIC_WORKFLOW = "scheduled-monitor.yml"
TACTICAL_WORKFLOW = "tactical-1h.yml"
NOMINAL_MINUTE = 15


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def bucket_start(now: datetime, cadence_hours: int, minute: int = NOMINAL_MINUTE) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    shifted = now - timedelta(minutes=minute)
    bucket_hour = (shifted.hour // cadence_hours) * cadence_hours
    return shifted.replace(hour=bucket_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=minute)


def _run_is_valid_for_bucket(run: Mapping[str, Any], start: datetime) -> bool:
    created = _parse_utc(run.get("created_at") or run.get("run_started_at"))
    if created is None or created < start:
        return False
    status = str(run.get("status") or "").lower()
    conclusion = str(run.get("conclusion") or "").lower()
    if status in ACTIVE_STATUSES:
        return True
    return status == "completed" and conclusion == "success"


def bucket_has_run(payload: Mapping[str, Any], start: datetime) -> bool:
    return any(_run_is_valid_for_bucket(run, start) for run in payload.get("workflow_runs", []))


@dataclass(frozen=True)
class DispatchDecision:
    action: str
    workflow: str | None
    nominal_start: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "workflow": self.workflow,
            "nominal_start": self.nominal_start,
            "reason": self.reason,
        }


def decide(*, now: datetime, strategic_runs: Mapping[str, Any], tactical_runs: Mapping[str, Any]) -> DispatchDecision:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)

    if now.minute < NOMINAL_MINUTE:
        return DispatchDecision("SKIP", None, None, "BEFORE_NOMINAL_MINUTE")

    strategic_start = bucket_start(now, 4)
    if not bucket_has_run(strategic_runs, strategic_start):
        return DispatchDecision("DISPATCH", STRATEGIC_WORKFLOW, strategic_start.isoformat(), "STRATEGIC_BUCKET_MISSING")

    if now.hour % 4 == 0:
        return DispatchDecision("SKIP", None, strategic_start.isoformat(), "STRATEGIC_RUN_COVERS_BOUNDARY_1H")

    tactical_start = bucket_start(now, 1)
    if not bucket_has_run(tactical_runs, tactical_start):
        return DispatchDecision("DISPATCH", TACTICAL_WORKFLOW, tactical_start.isoformat(), "TACTICAL_BUCKET_MISSING")

    return DispatchDecision("SKIP", None, tactical_start.isoformat(), "CURRENT_BUCKET_ALREADY_COVERED")


def _gh_json(gh: str, repo: str, workflow: str) -> dict[str, Any]:
    completed = subprocess.run(
        [gh, "api", f"/repos/{repo}/actions/workflows/{workflow}/runs?branch=main&per_page=20"],
        check=True, text=True, capture_output=True,
    )
    return json.loads(completed.stdout)


def _dispatch(gh: str, repo: str, workflow: str) -> None:
    subprocess.run([gh, "workflow", "run", workflow, "--repo", repo, "--ref", "main"], check=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reliable external scheduler for ETH 4H Strategic / 1H Tactical workflows.")
    parser.add_argument("--repo", default="stanleyrprose/eth-phase-meter")
    parser.add_argument("--gh", default="/opt/homebrew/bin/gh")
    parser.add_argument("--now", help="ISO-8601 time for testing; defaults to current UTC time")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = _parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now must be a valid timestamp")

    strategic_runs = _gh_json(args.gh, args.repo, STRATEGIC_WORKFLOW)
    tactical_runs = _gh_json(args.gh, args.repo, TACTICAL_WORKFLOW)
    decision = decide(now=now, strategic_runs=strategic_runs, tactical_runs=tactical_runs)

    if decision.action == "DISPATCH" and decision.workflow and not args.dry_run:
        _dispatch(args.gh, args.repo, decision.workflow)

    print(json.dumps({
        "checked_at": now.astimezone(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        **decision.to_dict(),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
