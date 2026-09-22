from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}


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


def _run_time(run: Mapping[str, Any]) -> datetime | None:
    return _parse_utc(run.get("created_at") or run.get("run_started_at"))


def _summary(run: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "id": run.get("id"),
        "event": run.get("event"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "head_sha": run.get("head_sha"),
        "html_url": run.get("html_url"),
    }


@dataclass(frozen=True)
class WatchdogDecision:
    checked_at: str
    expected_cadence_hours: float
    stale_after_hours: float
    recovery_required: bool
    reason: str
    latest_success_age_hours: float | None
    latest_success: dict[str, Any] | None
    latest_run: dict[str, Any] | None
    active_run: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_runs(
    payload: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    expected_cadence_hours: float = 4.0,
    stale_after_hours: float = 5.0,
) -> WatchdogDecision:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if expected_cadence_hours <= 0:
        raise ValueError("expected_cadence_hours must be positive")
    if stale_after_hours <= 0:
        raise ValueError("stale_after_hours must be positive")

    raw_runs = payload.get("workflow_runs", []) if isinstance(payload, Mapping) else payload
    runs = [dict(item) for item in raw_runs]

    timed = [(run, _run_time(run)) for run in runs]
    timed = [(run, ts) for run, ts in timed if ts is not None]
    timed.sort(key=lambda pair: pair[1], reverse=True)

    latest_run = timed[0][0] if timed else None
    active = [
        (run, ts)
        for run, ts in timed
        if str(run.get("status") or "").lower() in ACTIVE_STATUSES
    ]
    active_run = active[0][0] if active else None

    successes = [
        (run, ts)
        for run, ts in timed
        if str(run.get("status") or "").lower() == "completed"
        and str(run.get("conclusion") or "").lower() == "success"
    ]
    latest_success = successes[0] if successes else None

    age_hours = None
    if latest_success:
        age_seconds = (now - latest_success[1]).total_seconds()
        age_hours = max(0.0, age_seconds / 3600.0)

    if active_run:
        recover = False
        reason = "ACTIVE_MONITOR_RUN_PRESENT"
    elif latest_success is None:
        recover = True
        reason = "NO_SUCCESSFUL_MONITOR_RUN"
    elif age_hours is not None and age_hours > stale_after_hours:
        recover = True
        reason = "LATEST_SUCCESS_STALE"
    else:
        recover = False
        reason = "LATEST_SUCCESS_FRESH"

    return WatchdogDecision(
        checked_at=now.isoformat(),
        expected_cadence_hours=expected_cadence_hours,
        stale_after_hours=stale_after_hours,
        recovery_required=recover,
        reason=reason,
        latest_success_age_hours=round(age_hours, 3) if age_hours is not None else None,
        latest_success=_summary(latest_success[0]) if latest_success else None,
        latest_run=_summary(latest_run),
        active_run=_summary(active_run),
    )


def _append_github_output(path: str | None, decision: WatchdogDecision) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"recover={'true' if decision.recovery_required else 'false'}\n")
        handle.write(f"reason={decision.reason}\n")
        if decision.latest_success_age_hours is not None:
            handle.write(f"latest_success_age_hours={decision.latest_success_age_hours}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect a stale/missed ETH Scheduled Monitor run.")
    parser.add_argument("--runs", required=True, help="GitHub workflow-runs JSON payload")
    parser.add_argument("--report", required=True, help="Output watchdog report JSON")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT"))
    parser.add_argument("--now", help="ISO-8601 UTC-capable timestamp; defaults to current time")
    parser.add_argument("--expected-cadence-hours", type=float, default=4.0)
    parser.add_argument("--stale-after-hours", type=float, default=5.0)
    args = parser.parse_args()

    now = _parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now must be a valid timestamp")

    payload = json.loads(Path(args.runs).read_text(encoding="utf-8"))
    decision = evaluate_runs(
        payload,
        now=now,
        expected_cadence_hours=args.expected_cadence_hours,
        stale_after_hours=args.stale_after_hours,
    )
    report = decision.to_dict()
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _append_github_output(args.github_output, decision)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
