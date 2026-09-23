from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import html
from typing import Any, Iterable

from .tactical_outcomes import (
    HORIZON_HOURS,
    REQUESTED_COHORTS,
    _canonical_1h_prices,
    _parse_time,
)


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


def _event_nominal(event: dict[str, Any]) -> datetime:
    return _parse_time(event["nominal_time"])


def _event_key(event: dict[str, Any]) -> tuple[str, str]:
    return str(event.get("event_version") or ""), _event_nominal(event).isoformat()


def _outcome_key(outcome: dict[str, Any]) -> tuple[str, int]:
    return str(outcome.get("event_id") or ""), int(outcome.get("horizon_hours") or 0)


def assess_r2_readiness(
    events: Iterable[dict[str, Any]],
    outcomes: Iterable[dict[str, Any]],
    pit_records: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events = list(events)
    outcomes = list(outcomes)
    prices = _canonical_1h_prices(pit_records)

    event_key_counts = Counter(_event_key(event) for event in events)
    outcome_key_counts = Counter(_outcome_key(outcome) for outcome in outcomes)
    duplicate_event_buckets = sorted(
        nominal for (_, nominal), count in event_key_counts.items() if count > 1
    )
    duplicate_outcome_keys = [
        {"event_id": event_id, "horizon_hours": horizon}
        for (event_id, horizon), count in sorted(outcome_key_counts.items())
        if count > 1
    ]

    event_by_id = {
        str(event["event_id"]): event for event in events if event.get("event_id")
    }
    normal_events = [
        event for event in events if str(event.get("data_health") or "UNKNOWN") == "NORMAL"
    ]
    degraded_events = [
        event for event in events if str(event.get("data_health") or "UNKNOWN") != "NORMAL"
    ]

    latest_event = max((_event_nominal(event) for event in events), default=None)
    first_event = min((_event_nominal(event) for event in events), default=None)
    latest_pit_nominal = max(prices.keys(), default=None)

    cohort_counts = Counter()
    for event in events:
        for cohort in event.get("cohorts") or []:
            cohort_counts[str(cohort)] += 1

    horizon_reports: dict[str, dict[str, Any]] = {}
    total_missing_targets = 0
    total_settlement_lag = 0
    total_incomplete_paths = 0

    outcome_by_key = {_outcome_key(outcome): outcome for outcome in outcomes}
    for horizon in HORIZON_HOURS:
        due_events: list[dict[str, Any]] = []
        missing_target = 0
        settlement_lag = 0
        settled = 0
        incomplete_paths = 0

        for event in events:
            event_id = str(event.get("event_id") or "")
            if not event_id or latest_pit_nominal is None:
                continue
            target = _event_nominal(event) + timedelta(hours=horizon)
            if target > latest_pit_nominal:
                continue
            due_events.append(event)
            target_exists = target in prices
            outcome = outcome_by_key.get((event_id, horizon))
            if not target_exists:
                missing_target += 1
            elif outcome is None:
                settlement_lag += 1
            else:
                settled += 1
                if not bool(outcome.get("path_complete")):
                    incomplete_paths += 1

        due = len(due_events)
        horizon_reports[str(horizon)] = {
            "horizon_hours": horizon,
            "event_count": len(events),
            "due_count": due,
            "settled_count": settled,
            "not_due_count": len(events) - due,
            "settlement_completeness_pct": (
                _round(100.0 * settled / due) if due else None
            ),
            "missing_target_pit": missing_target,
            "settlement_lag": settlement_lag,
            "incomplete_path_count": incomplete_paths,
        }
        total_missing_targets += missing_target
        total_settlement_lag += settlement_lag
        total_incomplete_paths += incomplete_paths

    integrity_issue_count = (
        len(duplicate_event_buckets)
        + len(duplicate_outcome_keys)
        + total_settlement_lag
    )
    if latest_pit_nominal is None:
        operational_status = "BLOCKED"
        operational_reason = "NO_1H_PIT"
    elif integrity_issue_count:
        operational_status = "BLOCKED"
        operational_reason = "INTEGRITY_OR_SETTLEMENT_LAG"
    elif total_missing_targets or total_incomplete_paths:
        operational_status = "DEGRADED"
        operational_reason = "PIT_GAPS_OR_INCOMPLETE_PATHS"
    else:
        operational_status = "HEALTHY"
        operational_reason = "OK"

    report = {
        "timestamp": now.isoformat(),
        "operational_status": operational_status,
        "operational_reason": operational_reason,
        "research_status": "ACCUMULATING_EVIDENCE",
        "research_only": True,
        "evidence_sufficiency_gate": "NO_AUTO_SUFFICIENCY_GATE",
        "event_count": len(events),
        "normal_event_count": len(normal_events),
        "degraded_event_count": len(degraded_events),
        "outcome_count": len(outcomes),
        "first_event_nominal_time": first_event.isoformat() if first_event else None,
        "latest_event_nominal_time": latest_event.isoformat() if latest_event else None,
        "latest_event_age_hours": (
            _round((now - latest_event).total_seconds() / 3600.0, 3)
            if latest_event else None
        ),
        "latest_1h_pit_nominal_time": (
            latest_pit_nominal.isoformat() if latest_pit_nominal else None
        ),
        "horizons": horizon_reports,
        "cohorts": {
            cohort: int(cohort_counts.get(cohort, 0))
            for cohort in REQUESTED_COHORTS
        },
        "all_cohorts": dict(sorted(cohort_counts.items())),
        "integrity": {
            "duplicate_event_bucket_count": len(duplicate_event_buckets),
            "duplicate_event_buckets": duplicate_event_buckets,
            "duplicate_outcome_key_count": len(duplicate_outcome_keys),
            "duplicate_outcome_keys": duplicate_outcome_keys,
            "settlement_lag_count": total_settlement_lag,
            "missing_target_pit_count": total_missing_targets,
            "incomplete_path_count": total_incomplete_paths,
        },
        "governance": {
            "auto_retuning": False,
            "auto_promotion": False,
            "trading_execution": False,
            "interpretation": (
                "Operational readiness and evidence accumulation only; "
                "no statistical sufficiency or predictive-value claim."
            ),
        },
    }
    return report


def render_r2_readiness_message(report: dict[str, Any]) -> str:
    status = str(report.get("operational_status") or "UNKNOWN")
    icon = "✅" if status == "HEALTHY" else "⚠️" if status == "DEGRADED" else "🛑"
    lines = [
        f"{icon} <b>R2 Tactical Research Status</b>",
        f"Operational: <b>{html.escape(status)}</b>",
        f"Research: <b>{html.escape(str(report.get('research_status') or 'UNKNOWN'))}</b>",
        "",
        f"Events: <b>{int(report.get('event_count') or 0)}</b> "
        f"(normal {int(report.get('normal_event_count') or 0)}, "
        f"degraded {int(report.get('degraded_event_count') or 0)})",
        f"Outcomes: <b>{int(report.get('outcome_count') or 0)}</b>",
    ]

    for horizon in HORIZON_HOURS:
        item = (report.get("horizons") or {}).get(str(horizon)) or {}
        due = int(item.get("due_count") or 0)
        settled = int(item.get("settled_count") or 0)
        completeness = item.get("settlement_completeness_pct")
        suffix = f" · {completeness:.0f}%" if completeness is not None else ""
        lines.append(f"+{horizon}H settled: <b>{settled}/{due}</b>{suffix}")

    integrity = report.get("integrity") or {}
    lines.extend([
        "",
        "Integrity:",
        f"duplicates {int(integrity.get('duplicate_event_bucket_count') or 0)} · "
        f"settlement lag {int(integrity.get('settlement_lag_count') or 0)} · "
        f"missing PIT {int(integrity.get('missing_target_pit_count') or 0)}",
    ])

    cohort_counts = report.get("cohorts") or {}
    nonzero = [
        f"{label}={int(count)}"
        for label, count in cohort_counts.items()
        if int(count or 0) > 0
    ]
    if nonzero:
        lines.extend(["", "Cohorts:", html.escape(" · ".join(nonzero[:8]))])

    age = report.get("latest_event_age_hours")
    if age is not None:
        lines.append(f"Latest event age: <b>{float(age):.2f}h</b>")

    lines.extend([
        "",
        "<i>Descriptive evidence only; no auto-retuning, promotion, or trading.</i>",
    ])
    return "\n".join(lines)
