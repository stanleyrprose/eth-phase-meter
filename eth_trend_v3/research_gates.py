from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

HORIZONS = ("3d", "7d", "30d")


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace(" UTC", "+00:00").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_4h_pit(
    records: list[dict[str, Any]],
    *,
    now: datetime,
    stale_after_hours: float = 5.0,
) -> dict[str, Any]:
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for record in records:
        metric = record.get("metric_value") or {}
        if metric.get("timeframe") != "4h":
            continue
        observed = _parse_utc(record.get("observed_at") or record.get("event_time"))
        if observed is not None:
            candidates.append((observed, record))

    if not candidates:
        return {
            "status": "NO_DATA",
            "attention_required": True,
            "stale_after_hours": stale_after_hours,
            "latest_observed_at": None,
            "latest_age_hours": None,
            "latest_coverage": None,
            "latest_data_status": None,
            "latest_schedule_nominal_time": None,
            "latest_workflow_run_id": None,
            "latest_github_event": None,
        }

    observed, record = max(candidates, key=lambda item: item[0])
    age_hours = max(0.0, (now - observed).total_seconds() / 3600.0)
    quality = record.get("quality_flags") or {}
    data_status = str(quality.get("data_status") or (record.get("data_health") or {}).get("status") or "UNKNOWN")
    stale = age_hours > stale_after_hours

    if stale:
        status = "STALE"
    elif data_status not in {"NORMAL", "UNKNOWN"}:
        status = "DEGRADED"
    else:
        status = "NORMAL"

    return {
        "status": status,
        "attention_required": status != "NORMAL",
        "stale_after_hours": stale_after_hours,
        "latest_observed_at": observed.isoformat(),
        "latest_age_hours": round(age_hours, 3),
        "latest_coverage": record.get("coverage"),
        "latest_data_status": data_status,
        "latest_schedule_nominal_time": record.get("schedule_nominal_time"),
        "latest_workflow_run_id": record.get("workflow_run_id"),
        "latest_github_event": record.get("github_event"),
    }


def _approval_summary(approval: Mapping[str, Any] | None) -> dict[str, Any]:
    if not approval:
        return {
            "approved": False,
            "status": "NO_PRODUCTION_APPROVAL",
            "model_id": None,
            "model_version": None,
            "artifact_hash": None,
            "gate_version": None,
        }
    return {
        "approved": approval.get("status") == "PRODUCTION",
        "status": str(approval.get("status") or "UNKNOWN"),
        "model_id": approval.get("model_id"),
        "model_version": approval.get("model_version"),
        "artifact_hash": approval.get("artifact_hash"),
        "gate_version": approval.get("gate_version"),
    }


def build_research_gate_snapshot(
    readiness: Mapping[str, Any],
    sizing: Mapping[str, Any],
    records: list[dict[str, Any]],
    production_approvals: Mapping[str, Mapping[str, Any] | None],
    *,
    now: datetime | None = None,
    pit_stale_after_hours: float = 5.0,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)

    forecast: dict[str, Any] = {}
    research_ready_horizons: list[str] = []
    production_approved_horizons: list[str] = []
    readiness_horizons = readiness.get("horizons") or {}

    for horizon in HORIZONS:
        research = readiness_horizons.get(horizon) or {}
        research_ready = bool(research.get("research_ready"))
        approval = _approval_summary(production_approvals.get(horizon))
        if research_ready:
            research_ready_horizons.append(horizon)
        if approval["approved"]:
            production_approved_horizons.append(horizon)
        forecast[horizon] = {
            "labeled_rows": int(research.get("labeled_row_n") or 0),
            "minimum_research_rows": int(research.get("minimum_walk_forward_rows") or 0),
            "research_ready": research_ready,
            "production_eligible": bool(research.get("production_eligible", False)),
            "production_approval": approval,
        }

    sizing_ready = bool(sizing.get("review_checkpoint_reached"))
    cohorts = sizing.get("cohorts") or []
    cohort_counts = {
        str(item.get("cohort")): int(item.get("n_intervals") or 0)
        for item in cohorts
        if item.get("cohort")
    }
    pit = _latest_4h_pit(records, now=now, stale_after_hours=pit_stale_after_hours)

    if pit["attention_required"]:
        next_action = "ENGINEERING_ATTENTION_REQUIRED"
    elif production_approved_horizons:
        next_action = "PRODUCTION_FORECAST_APPROVAL_PRESENT"
    elif sizing_ready:
        next_action = "HUMAN_SIZING_REVIEW_AVAILABLE"
    elif research_ready_horizons:
        next_action = "FORECAST_RESEARCH_READY"
    else:
        next_action = "OBSERVE_AND_ACCUMULATE"

    actionable = next_action != "OBSERVE_AND_ACCUMULATE"

    return {
        "contract_version": "research-gates-v1",
        "generated_at": now.isoformat(),
        "source": {
            "forecast_readiness_contract": "research-readiness",
            "sizing_contract": sizing.get("contract_version"),
            "pit_source": "durable PIT records",
        },
        "forecast": forecast,
        "sizing": {
            "status": sizing.get("status"),
            "clean_intervals": int(sizing.get("raw_valid_intervals") or 0),
            "review_checkpoint_target_intervals": int(
                sizing.get("review_checkpoint_target_intervals") or 0
            ),
            "human_review_ready": sizing_ready,
            "canonical_4h_records": int(sizing.get("canonical_4h_records") or 0),
            "cohort_intervals": cohort_counts,
            "automatic_sizing_promotion_allowed": bool(
                sizing.get("automatic_sizing_promotion_allowed", False)
            ),
        },
        "pit": pit,
        "milestones": {
            "forecast_research_ready_horizons": research_ready_horizons,
            "sizing_human_review_ready": sizing_ready,
            "production_approved_horizons": production_approved_horizons,
            "pit_attention_required": pit["attention_required"],
        },
        "decision": {
            "status": next_action,
            "actionable": actionable,
            "observation_freeze": not actionable,
        },
        "execution": {
            "paper_execution_allowed": False,
            "live_execution_allowed": False,
            "automatic_capital_allocation_allowed": False,
        },
        "governance_notes": [
            "Research readiness does not imply production eligibility or approval.",
            "The sizing checkpoint is a human-review trigger only.",
            "Production forecast approval does not authorize paper/live trading or capital allocation.",
        ],
    }
