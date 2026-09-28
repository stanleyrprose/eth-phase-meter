from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
STRATEGIC_WORKFLOW = "scheduled-monitor.yml"
TACTICAL_WORKFLOW = "tactical-1h.yml"
NOMINAL_MINUTE = 15
DEFAULT_LEDGER = Path.home() / ".eth-phase-scheduler" / "dispatch-ledger.json"


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


def _bucket_runs(payload: Mapping[str, Any], start: datetime) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for run in payload.get("workflow_runs", []):
        created = _parse_utc(run.get("created_at") or run.get("run_started_at"))
        if created is not None and created >= start:
            out.append(run)
    return out


def _run_is_covered(run: Mapping[str, Any]) -> bool:
    status = str(run.get("status") or "").lower()
    conclusion = str(run.get("conclusion") or "").lower()
    if status in ACTIVE_STATUSES:
        return True
    return status == "completed" and conclusion == "success"


def bucket_has_run(payload: Mapping[str, Any], start: datetime) -> bool:
    return any(_run_is_covered(run) for run in _bucket_runs(payload, start))


def bucket_has_attempt(payload: Mapping[str, Any], start: datetime) -> bool:
    return bool(_bucket_runs(payload, start))


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

    if now.hour % 4 == 0:
        strategic_start = bucket_start(now, 4)
        if bucket_has_run(strategic_runs, strategic_start):
            return DispatchDecision("SKIP", None, strategic_start.isoformat(), "STRATEGIC_RUN_COVERS_BOUNDARY_1H")
        if bucket_has_attempt(strategic_runs, strategic_start):
            return DispatchDecision("SKIP", None, strategic_start.isoformat(), "STRATEGIC_BUCKET_ALREADY_ATTEMPTED")
        return DispatchDecision(
            "DISPATCH",
            STRATEGIC_WORKFLOW,
            strategic_start.isoformat(),
            "STRATEGIC_BUCKET_MISSING",
        )

    tactical_start = bucket_start(now, 1)
    if bucket_has_run(tactical_runs, tactical_start):
        return DispatchDecision("SKIP", None, tactical_start.isoformat(), "CURRENT_BUCKET_ALREADY_COVERED")
    if bucket_has_attempt(tactical_runs, tactical_start):
        return DispatchDecision("SKIP", None, tactical_start.isoformat(), "TACTICAL_BUCKET_ALREADY_ATTEMPTED")
    return DispatchDecision(
        "DISPATCH",
        TACTICAL_WORKFLOW,
        tactical_start.isoformat(),
        "TACTICAL_BUCKET_MISSING",
    )


def _gh_json(gh: str, repo: str, workflow: str) -> dict[str, Any]:
    completed = subprocess.run(
        [gh, "api", f"/repos/{repo}/actions/workflows/{workflow}/runs?branch=main&per_page=40"],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def _dispatch(gh: str, repo: str, workflow: str) -> None:
    subprocess.run([gh, "workflow", "run", workflow, "--repo", repo, "--ref", "main"], check=True, text=True)


def _lease_key(workflow: str, nominal_start: str) -> str:
    return f"{workflow}|{nominal_start}"


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"dispatches": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("dispatches"), dict):
        return {"dispatches": {}}
    return payload


def _has_dispatch_lease(path: Path, workflow: str, nominal_start: str) -> bool:
    return _lease_key(workflow, nominal_start) in _load_ledger(path)["dispatches"]


def _record_dispatch_lease(path: Path, workflow: str, nominal_start: str, dispatched_at: datetime) -> None:
    payload = _load_ledger(path)
    payload["dispatches"][_lease_key(workflow, nominal_start)] = {
        "workflow": workflow,
        "nominal_start": nominal_start,
        "dispatched_at": dispatched_at.astimezone(timezone.utc).isoformat(),
    }
    # Keep the ledger bounded while retaining enough history for audit/debugging.
    cutoff = dispatched_at.astimezone(timezone.utc) - timedelta(days=7)
    payload["dispatches"] = {
        key: value for key, value in payload["dispatches"].items()
        if (_parse_utc(value.get("dispatched_at")) or cutoff) >= cutoff
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reliable external scheduler for ETH 4H Strategic / 1H Tactical workflows.")
    parser.add_argument("--repo", default="stanleyrprose/eth-phase-meter")
    parser.add_argument("--gh", default="/opt/homebrew/bin/gh")
    parser.add_argument("--now", help="ISO-8601 time for testing; defaults to current UTC time")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="Durable local dispatch lease ledger")
    args = parser.parse_args()

    now = _parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now must be a valid timestamp")

    strategic_runs = _gh_json(args.gh, args.repo, STRATEGIC_WORKFLOW)
    tactical_runs = _gh_json(args.gh, args.repo, TACTICAL_WORKFLOW)
    decision = decide(now=now, strategic_runs=strategic_runs, tactical_runs=tactical_runs)
    ledger_path = Path(args.ledger).expanduser()

    if decision.action == "DISPATCH" and decision.workflow and decision.nominal_start:
        if _has_dispatch_lease(ledger_path, decision.workflow, decision.nominal_start):
            decision = DispatchDecision("SKIP", None, decision.nominal_start, "LOCAL_DISPATCH_LEASE_PRESENT")
        elif not args.dry_run:
            _dispatch(args.gh, args.repo, decision.workflow)
            _record_dispatch_lease(ledger_path, decision.workflow, decision.nominal_start, now)

    print(json.dumps({
        "checked_at": now.astimezone(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        **decision.to_dict(),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
