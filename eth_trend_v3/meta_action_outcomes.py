from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from .shadow_forecast import path_outcome
from .tactical_outcomes import _canonical_1h_prices, _parse_time, load_tactical_price_records


EVENT_VERSION = "meta-action-v1"
HORIZON_HOURS = (4, 12, 24, 72)
PATH_CADENCE_HOURS = 4
ACTIONS = ("ADD", "HOLD", "REDUCE", "AVOID")

_BUY_DECISIONS = {"BUY", "STRONG BUY", "ADD", "ACCUMULATE"}
_SELL_DECISIONS = {"SELL", "STRONG SELL", "REDUCE", "EXIT"}


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_ta(value: Any) -> str:
    return str(value or "").strip().upper().replace("_", " ")


def _nominal_4h(value: Any) -> datetime:
    observed = _parse_time(value)
    shifted = observed - timedelta(minutes=15)
    hour = shifted.hour - (shifted.hour % 4)
    return shifted.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(minutes=15)


def _side_from_meta(action: str) -> int:
    if action == "ADD":
        return 1
    if action == "REDUCE":
        return -1
    return 0


def _side_from_phase(direction: float | None) -> int:
    if direction is None:
        return 0
    if direction >= 20:
        return 1
    if direction <= -20:
        return -1
    return 0


def _side_from_ta(decision: str) -> int:
    if decision in _BUY_DECISIONS:
        return 1
    if decision in _SELL_DECISIONS:
        return -1
    return 0


def build_meta_action_event(
    meta: dict[str, Any],
    monitor: dict[str, Any],
    *,
    monitor_run_id: int | str,
    monitor_git_sha: str | None,
    notification: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    four_hour = monitor.get("4h") or {}
    one_hour = monitor.get("1h") or {}
    timestamp = four_hour.get("timestamp")
    if not timestamp:
        return None, {"status": "SKIPPED_MISSING_4H_TIMESTAMP"}

    entry_price = _as_float(four_hour.get("price"))
    if entry_price is None or entry_price <= 0:
        entry_price = _as_float(one_hour.get("price"))
    if entry_price is None or entry_price <= 0:
        return None, {"status": "SKIPPED_INVALID_PRICE"}

    nominal = _nominal_4h(timestamp)
    generated_at = _parse_time(meta.get("generated_at") or timestamp)
    action = str(meta.get("recommendation") or "UNKNOWN").upper()
    if action not in ACTIONS:
        return None, {"status": "SKIPPED_UNKNOWN_ACTION", "action": action}

    sources = meta.get("sources") or {}
    phase = sources.get("phase_meter") or {}
    phase_1h = phase.get("1h") or {}
    phase_4h = phase.get("4h") or {}
    ta = sources.get("tradingagents") or {}
    ta_decision = _normalize_ta(ta.get("decision"))
    d4 = _as_float(phase_4h.get("direction"))
    notification = notification or {}

    event_id = f"meta-action-v1-{nominal.strftime('%Y%m%dT%H%MZ')}"
    event_health = (
        "NORMAL"
        if bool(phase.get("fresh"))
        and bool(ta.get("fresh"))
        and _as_float(phase_4h.get("coverage")) is not None
        and float(phase_4h.get("coverage") or 0) >= 80
        else "DEGRADED"
    )

    event = {
        "event_id": event_id,
        "event_version": EVENT_VERSION,
        "research_only": True,
        "nominal_time": nominal.isoformat(),
        "decision_generated_at": generated_at.isoformat(),
        "decision_latency_minutes": round(
            max(0.0, (generated_at - nominal).total_seconds() / 60.0), 3
        ),
        "entry_price": entry_price,
        "action": action,
        "evidence_alignment": str(meta.get("evidence_alignment") or "UNKNOWN"),
        "reason_codes": [str(value) for value in (meta.get("reason_codes") or [])],
        "event_health": event_health,
        "meta_side": _side_from_meta(action),
        "phase_reference_side": _side_from_phase(d4),
        "tradingagents_reference_side": _side_from_ta(ta_decision),
        "phase_1h_direction": _as_float(phase_1h.get("direction")),
        "phase_4h_direction": d4,
        "phase_1h_regime": phase_1h.get("regime"),
        "phase_4h_regime": phase_4h.get("regime"),
        "phase_4h_momentum": _as_float(phase_4h.get("momentum")),
        "phase_4h_order_flow": _as_float(phase_4h.get("order_flow")),
        "phase_4h_options_positioning": _as_float(phase_4h.get("options_positioning")),
        "phase_4h_volatility_risk": _as_float(phase_4h.get("volatility_risk")),
        "tradingagents_decision": ta_decision,
        "monitor_run_id": monitor_run_id,
        "monitor_git_sha": monitor_git_sha,
        "notification": {
            "fallback_requested": str(notification.get("status") or "") != "SENT",
            "local_status": notification.get("status"),
            "policy_action": notification.get("policy_action"),
            "change_type": notification.get("change_type"),
            "previous_recommendation": notification.get("previous_recommendation"),
            "current_recommendation": notification.get("current_recommendation"),
        },
        "meta_snapshot": meta,
        "guardrails": {
            "auto_retuning": False,
            "auto_promotion": False,
            "automatic_sizing_change": False,
            "trading_execution": False,
        },
    }
    return event, {"status": "ELIGIBLE", "event_id": event_id}


def persist_meta_action_event(event: dict[str, Any], dsn: str | None = None) -> dict[str, Any]:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return {"status": "SKIPPED_PERSISTENCE_UNAVAILABLE", "event_id": event["event_id"]}

    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO eth_meta_action_events("
                "event_id,event_version,nominal_time,decision_generated_at,payload"
                ") VALUES(%s,%s,%s,%s,%s::jsonb) "
                "ON CONFLICT DO NOTHING RETURNING event_id",
                (
                    event["event_id"],
                    event["event_version"],
                    _parse_time(event["nominal_time"]),
                    _parse_time(event["decision_generated_at"]),
                    json.dumps(event, ensure_ascii=False, default=str),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "status": "RECORDED" if row else "ALREADY_EXISTS",
        "event_id": event["event_id"],
    }


def load_meta_action_events(dsn: str | None = None) -> list[dict[str, Any]]:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return []
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM eth_meta_action_events ORDER BY nominal_time")
            return [row[0] for row in cur.fetchall()]


def load_meta_action_outcomes(dsn: str | None = None) -> list[dict[str, Any]]:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return []
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM eth_meta_action_outcomes "
                "ORDER BY settled_at,event_id,horizon_hours"
            )
            return [row[0] for row in cur.fetchall()]


def load_meta_action_outcome_revisions(dsn: str | None = None) -> list[dict[str, Any]]:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return []
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id,horizon_hours,revision,correction_reason,"
                "source_git_sha,payload "
                "FROM eth_meta_action_outcome_revisions "
                "ORDER BY event_id,horizon_hours,revision"
            )
            return [
                {
                    "event_id": event_id,
                    "horizon_hours": int(horizon_hours),
                    "revision": int(revision),
                    "correction_reason": correction_reason,
                    "source_git_sha": source_git_sha,
                    "payload": payload,
                }
                for event_id, horizon_hours, revision, correction_reason, source_git_sha, payload
                in cur.fetchall()
            ]


def effective_meta_action_outcomes(
    base_outcomes: Iterable[dict[str, Any]],
    revisions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    effective = {
        (str(row.get("event_id")), int(row.get("horizon_hours") or 0)): dict(row)
        for row in base_outcomes
    }
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for revision in revisions:
        key = (str(revision.get("event_id")), int(revision.get("horizon_hours") or 0))
        if key not in effective:
            continue
        current = latest.get(key)
        if current is None or int(revision.get("revision") or 0) > int(current.get("revision") or 0):
            latest[key] = revision
    for key, revision in latest.items():
        payload = dict(revision.get("payload") or {})
        if str(payload.get("event_id")) != key[0] or int(payload.get("horizon_hours") or 0) != key[1]:
            continue
        payload["outcome_revision"] = int(revision["revision"])
        payload["correction_reason"] = str(revision["correction_reason"])
        payload["correction_source_git_sha"] = str(revision["source_git_sha"])
        effective[key] = payload
    return list(effective.values())


def _aligned(actual_return: float, side: int) -> float | None:
    return actual_return * side if side else None


def build_due_meta_action_outcomes(
    events: Iterable[dict[str, Any]],
    pit_records: Iterable[dict[str, Any]],
    *,
    existing_keys: set[tuple[str, int]] | None = None,
) -> list[dict[str, Any]]:
    existing_keys = existing_keys or set()
    prices = _canonical_1h_prices(pit_records)
    due: list[dict[str, Any]] = []

    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        nominal = _parse_time(event["nominal_time"])
        entry_price = _as_float(event.get("entry_price"))
        if entry_price is None or entry_price <= 0:
            continue

        for horizon in HORIZON_HOURS:
            key = (event_id, horizon)
            if key in existing_keys:
                continue
            target = nominal + timedelta(hours=horizon)
            target_row = prices.get(target)
            if not target_row:
                continue

            expected_path_times = [
                nominal + timedelta(hours=offset)
                for offset in range(PATH_CADENCE_HOURS, horizon + 1, PATH_CADENCE_HOURS)
            ]
            missing_path_times = [
                timestamp for timestamp in expected_path_times if timestamp not in prices
            ]
            path_rows = [
                prices[timestamp] for timestamp in expected_path_times if timestamp in prices
            ]
            if not path_rows:
                continue
            path_complete = not missing_path_times
            metrics = path_outcome(
                float(entry_price),
                [float(row["price"]) for row in path_rows],
            )
            actual_return = (float(target_row["price"]) / float(entry_price)) - 1.0
            if not path_complete:
                metrics["mae"] = None
                metrics["mfe"] = None
            metrics["actual_return"] = actual_return
            due.append(
                {
                    "event_id": event_id,
                    "event_version": event.get("event_version"),
                    "research_only": True,
                    "horizon_hours": horizon,
                    "event_nominal_time": nominal.isoformat(),
                    "target_nominal_time": target.isoformat(),
                    "settled_at": target_row["observed_at"],
                    "entry_price": entry_price,
                    "target_price": target_row["price"],
                    **metrics,
                    "absolute_return": abs(actual_return),
                    "meta_aligned_return": _aligned(actual_return, int(event.get("meta_side") or 0)),
                    "phase_reference_aligned_return": _aligned(
                        actual_return, int(event.get("phase_reference_side") or 0)
                    ),
                    "tradingagents_reference_aligned_return": _aligned(
                        actual_return, int(event.get("tradingagents_reference_side") or 0)
                    ),
                    "path_bars": len(path_rows),
                    "expected_path_bars": horizon // PATH_CADENCE_HOURS,
                    "path_cadence_hours": PATH_CADENCE_HOURS,
                    "path_complete": path_complete,
                    "missing_path_nominal_times": [
                        timestamp.isoformat() for timestamp in missing_path_times
                    ],
                    "target_workflow_run_id": target_row.get("workflow_run_id"),
                }
            )
    return due


def persist_meta_action_outcomes(
    outcomes: Iterable[dict[str, Any]],
    dsn: str | None = None,
) -> int:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return 0
    import psycopg

    inserted = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for outcome in outcomes:
                cur.execute(
                    "INSERT INTO eth_meta_action_outcomes("
                    "event_id,horizon_hours,settled_at,payload"
                    ") VALUES(%s,%s,%s,%s::jsonb) "
                    "ON CONFLICT DO NOTHING RETURNING event_id",
                    (
                        outcome["event_id"],
                        int(outcome["horizon_hours"]),
                        _parse_time(outcome["settled_at"]),
                        json.dumps(outcome, ensure_ascii=False, default=str),
                    ),
                )
                if cur.fetchone():
                    inserted += 1
        conn.commit()
    return inserted


def _round(value: float | None) -> float | None:
    return round(float(value), 8) if value is not None else None


def _return_summary(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mean_forward_return": None,
            "median_forward_return": None,
            "positive_return_rate": None,
            "mean_absolute_return": None,
            "mean_mae": None,
            "mean_mfe": None,
            "complete_path_n": 0,
        }
    returns = [float(outcome["actual_return"]) for _, outcome in rows]
    return {
        "n": len(rows),
        "mean_forward_return": _round(mean(returns)),
        "median_forward_return": _round(median(returns)),
        "positive_return_rate": _round(sum(value > 0 for value in returns) / len(returns)),
        "mean_absolute_return": _round(mean(abs(value) for value in returns)),
        "mean_mae": _round(
            mean(float(outcome["mae"]) for _, outcome in rows if outcome.get("path_complete"))
        )
        if any(outcome.get("path_complete") for _, outcome in rows)
        else None,
        "mean_mfe": _round(
            mean(float(outcome["mfe"]) for _, outcome in rows if outcome.get("path_complete"))
        )
        if any(outcome.get("path_complete") for _, outcome in rows)
        else None,
        "complete_path_n": sum(bool(outcome.get("path_complete")) for _, outcome in rows),
    }


def _aligned_summary(
    rows: list[tuple[dict[str, Any], dict[str, Any]]],
    field: str,
) -> dict[str, Any]:
    values = [
        float(outcome[field])
        for _, outcome in rows
        if outcome.get(field) is not None
    ]
    return {
        "n": len(values),
        "mean_aligned_return": _round(mean(values)) if values else None,
        "median_aligned_return": _round(median(values)) if values else None,
        "aligned_hit_rate": (
            _round(sum(value > 0 for value in values) / len(values)) if values else None
        ),
    }


def meta_action_outcome_report(
    events: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    events_by_id = {
        str(event["event_id"]): event for event in events if event.get("event_id")
    }
    report: dict[str, Any] = {
        "status": "ACCUMULATING_EVIDENCE",
        "research_only": True,
        "event_version": EVENT_VERSION,
        "event_count": len(events),
        "outcome_count": len(outcomes),
        "normal_event_count": sum(event.get("event_health") == "NORMAL" for event in events),
        "degraded_event_count": sum(event.get("event_health") != "NORMAL" for event in events),
        "horizons": {},
        "governance": {
            "auto_retuning": False,
            "auto_promotion": False,
            "automatic_sizing_change": False,
            "trading_execution": False,
            "ranking_or_winner_selection": False,
            "note": (
                "Prospective descriptive forward-outcome evidence only. "
                "Reference-system alignment is not a calibrated probability or production gate."
            ),
        },
        "reference_definitions": {
            "meta_directional": "ADD=+1, REDUCE=-1; HOLD/AVOID are non-directional.",
            "phase_reference": "4H direction >= +20 is +1; <= -20 is -1; otherwise 0.",
            "tradingagents_reference": "BUY-family=+1, SELL-family=-1; HOLD-family=0.",
        },
    }

    for horizon in HORIZON_HOURS:
        joined = [
            (events_by_id[str(outcome["event_id"])], outcome)
            for outcome in outcomes
            if int(outcome.get("horizon_hours") or 0) == horizon
            and str(outcome.get("event_id")) in events_by_id
        ]
        actions = {
            action: _return_summary(
                [(event, outcome) for event, outcome in joined if event.get("action") == action]
            )
            for action in ACTIONS
        }
        report["horizons"][str(horizon)] = {
            "settled_n": len(joined),
            "overall": _return_summary(joined),
            "actions": actions,
            "reference_alignment": {
                "meta_directional": _aligned_summary(joined, "meta_aligned_return"),
                "phase_reference": _aligned_summary(joined, "phase_reference_aligned_return"),
                "tradingagents_reference": _aligned_summary(
                    joined, "tradingagents_reference_aligned_return"
                ),
            },
        }
    return report


def run_meta_action_outcome_cycle(
    event: dict[str, Any],
    *,
    output_dir: str = "eth_reports/meta-action-outcomes",
    dsn: str | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        report = {
            "status": "SKIPPED_PERSISTENCE_UNAVAILABLE",
            "research_only": True,
            "event_record": {"status": "SKIPPED_PERSISTENCE_UNAVAILABLE"},
            "settled_now": 0,
        }
        (root / "meta_action_outcomes_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report

    event_record = persist_meta_action_event(event, dsn)
    events = load_meta_action_events(dsn)
    existing = load_meta_action_outcomes(dsn)
    existing_keys = {
        (str(outcome.get("event_id")), int(outcome.get("horizon_hours") or 0))
        for outcome in existing
    }
    pit_records = load_tactical_price_records(dsn)
    due = build_due_meta_action_outcomes(events, pit_records, existing_keys=existing_keys)
    settled_now = persist_meta_action_outcomes(due, dsn)
    all_outcomes = load_meta_action_outcomes(dsn)
    report = meta_action_outcome_report(events, all_outcomes)
    report["event_record"] = event_record
    report["settled_now"] = settled_now
    report["due_candidates"] = len(due)
    (root / "meta_action_outcomes_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return report


def safe_run_meta_action_outcome_cycle(
    event: dict[str, Any],
    *,
    output_dir: str = "eth_reports/meta-action-outcomes",
    dsn: str | None = None,
) -> dict[str, Any]:
    try:
        return run_meta_action_outcome_cycle(event, output_dir=output_dir, dsn=dsn)
    except Exception as exc:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        report = {
            "status": "ERROR",
            "research_only": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        (root / "meta_action_outcomes_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report
