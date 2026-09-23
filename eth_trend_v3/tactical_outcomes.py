from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from .shadow_forecast import path_outcome
from .tactical_alerts import DIRECTION_THRESHOLD


EVENT_VERSION = "r2-tactical-v1"
HORIZON_HOURS = (1, 4, 12, 24)
MAX_EVENT_DELAY_MINUTES = 15.0
REQUESTED_COHORTS = (
    "WEAK_BEAR+WAIT",
    "WEAK_BEAR+PASS",
    "WEAK_BULL+PASS",
    "WAIT→PASS",
    "GATE_BLOCKED",
    "GATE_PASS",
    "CROSS_UP_+20",
    "CROSS_DOWN_+20",
    "CROSS_UP_-20",
    "CROSS_DOWN_-20",
    "DIRECTION_STRENGTHENING",
    "DIRECTION_WEAKENING",
    "DIRECTION_REVERSAL",
)


def _parse_time(value: Any) -> datetime:
    text = str(value).strip().replace(" UTC", "+00:00")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nominal_1h(value: Any) -> datetime:
    observed = _parse_time(value)
    shifted = observed - timedelta(minutes=15)
    return shifted.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=15)


def _payload_nominal(payload: dict) -> datetime:
    explicit = payload.get("schedule_nominal_time")
    if explicit:
        return _parse_time(explicit)
    observed = payload.get("observed_at") or payload.get("timestamp")
    if not observed:
        raise ValueError("tactical payload has no observation timestamp")
    return _nominal_1h(observed)


def _payload_observed(payload: dict) -> datetime:
    value = payload.get("observed_at") or payload.get("timestamp")
    if not value:
        raise ValueError("tactical payload has no observed_at/timestamp")
    return _parse_time(value)


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _state(payload: dict) -> str | None:
    value = payload.get("tactical_state")
    return str(value) if value else None


def _gate(payload: dict) -> str | None:
    value = payload.get("execution_gate")
    return str(value) if value else None


def _regime(payload: dict) -> str | None:
    value = payload.get("rule_regime")
    return str(value) if value else None


def tactical_cohorts(current: dict, previous: dict | None = None) -> list[str]:
    previous = previous or {}
    labels: set[str] = set()

    state = _state(current)
    gate = _gate(current)
    if state:
        labels.add(f"STATE_{state}")
    if gate:
        labels.add(f"GATE_{gate}")
    if state and gate:
        labels.add(f"{state}+{gate}")

    previous_gate = _gate(previous)
    if previous_gate and gate and previous_gate != gate:
        labels.add(f"{previous_gate}→{gate}")

    previous_direction = _as_int(previous.get("rule_direction"))
    current_direction = _as_int(current.get("rule_direction"))
    if previous_direction is not None and current_direction is not None:
        if previous_direction < DIRECTION_THRESHOLD <= current_direction:
            labels.add("CROSS_UP_+20")
        if previous_direction >= DIRECTION_THRESHOLD > current_direction:
            labels.add("CROSS_DOWN_+20")
        if previous_direction > -DIRECTION_THRESHOLD >= current_direction:
            labels.add("CROSS_DOWN_-20")
        if previous_direction <= -DIRECTION_THRESHOLD < current_direction:
            labels.add("CROSS_UP_-20")

    triggers = ((current.get("notification_decision") or {}).get("triggers") or [])
    for trigger in triggers:
        text = str(trigger)
        for kind in ("STRENGTHENING", "WEAKENING", "REVERSAL"):
            if text.startswith(f"DIRECTION_{kind}:"):
                labels.add(f"DIRECTION_{kind}")

    return sorted(labels)


def build_tactical_event(
    current: dict,
    *,
    previous: dict | None = None,
    confirmation_4h: dict | None = None,
    max_delay_minutes: float = MAX_EVENT_DELAY_MINUTES,
) -> tuple[dict | None, dict]:
    previous = previous or {}
    confirmation_4h = confirmation_4h or {}
    observed = _payload_observed(current)
    nominal = _payload_nominal(current)
    delay_minutes = max(0.0, (observed - nominal).total_seconds() / 60.0)

    if delay_minutes > max_delay_minutes:
        return None, {
            "status": "SKIPPED_OUT_OF_BAND",
            "nominal_time": nominal.isoformat(),
            "observed_at": observed.isoformat(),
            "dispatch_delay_minutes": round(delay_minutes, 3),
            "max_delay_minutes": max_delay_minutes,
        }

    entry_price = _as_float(current.get("price"))
    if entry_price is None or entry_price <= 0:
        return None, {"status": "SKIPPED_INVALID_PRICE"}

    stamp = nominal.strftime("%Y%m%dT%H%MZ")
    event_id = f"tac-r2-v1-{stamp}"
    data_health = str((current.get("data_health") or {}).get("status") or "UNKNOWN")
    previous_snapshot = {
        "timestamp": previous.get("timestamp"),
        "rule_direction": _as_int(previous.get("rule_direction")),
        "tactical_state": _state(previous),
        "execution_gate": _gate(previous),
        "rule_regime": _regime(previous),
    }
    event = {
        "event_id": event_id,
        "event_version": EVENT_VERSION,
        "research_only": True,
        "nominal_time": nominal.isoformat(),
        "observed_at": observed.isoformat(),
        "dispatch_delay_minutes": round(delay_minutes, 3),
        "entry_price": entry_price,
        "rule_direction": _as_int(current.get("rule_direction")),
        "tactical_state": _state(current),
        "execution_gate": _gate(current),
        "rule_regime": _regime(current),
        "coverage": _as_float(current.get("coverage")),
        "data_health": data_health,
        "confirmation_4h_direction": _as_int(confirmation_4h.get("rule_direction")),
        "confirmation_4h_age_hours": _as_float(current.get("confirmation_4h_age_hours")),
        "notification_triggers": list(
            ((current.get("notification_decision") or {}).get("triggers") or [])
        ),
        "cohorts": tactical_cohorts(current, previous),
        "previous": previous_snapshot,
        "pit_snapshot_id": current.get("pit_snapshot_id"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "workflow_name": os.getenv("GITHUB_WORKFLOW", "local"),
        "git_sha": os.getenv("GITHUB_SHA", "unknown"),
    }
    return event, {"status": "ELIGIBLE", "event_id": event_id}


def persist_tactical_event(event: dict, dsn: str | None = None) -> dict:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return {"status": "SKIPPED_PERSISTENCE_UNAVAILABLE", "event_id": event["event_id"]}

    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO eth_tactical_events("
                "event_id,event_version,nominal_time,observed_at,payload"
                ") VALUES(%s,%s,%s,%s,%s::jsonb) "
                "ON CONFLICT DO NOTHING RETURNING event_id",
                (
                    event["event_id"],
                    event["event_version"],
                    _parse_time(event["nominal_time"]),
                    _parse_time(event["observed_at"]),
                    json.dumps(event, ensure_ascii=False, default=str),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "status": "RECORDED" if row else "ALREADY_EXISTS",
        "event_id": event["event_id"],
    }


def load_tactical_events(dsn: str | None = None) -> list[dict]:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return []
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM eth_tactical_events ORDER BY nominal_time")
            return [row[0] for row in cur.fetchall()]


def load_tactical_outcomes(dsn: str | None = None) -> list[dict]:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return []
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM eth_tactical_outcomes "
                "ORDER BY settled_at,event_id,horizon_hours"
            )
            return [row[0] for row in cur.fetchall()]


def load_tactical_price_records(dsn: str | None = None) -> list[dict]:
    """Load only the compact 1H PIT projection needed for R2 settlement."""
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return []

    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT "
                "payload->>'observed_at', "
                "payload->>'schedule_nominal_time', "
                "payload#>>'{metric_value,price}', "
                "payload->>'workflow_run_id' "
                "FROM eth_monitor_records "
                "WHERE record_type='pit_snapshot' "
                "AND payload#>>'{metric_value,timeframe}'='1h' "
                "ORDER BY created_at"
            )
            rows = cur.fetchall()

    records: list[dict] = []
    for observed_at, nominal_time, price, workflow_run_id in rows:
        parsed_price = _as_float(price)
        if not observed_at or parsed_price is None or parsed_price <= 0:
            continue
        records.append(
            {
                "observed_at": str(observed_at),
                "schedule_nominal_time": str(nominal_time) if nominal_time else None,
                "metric_value": {"timeframe": "1h", "price": parsed_price},
                "workflow_run_id": workflow_run_id,
            }
        )
    return records


def _canonical_1h_prices(pit_records: Iterable[dict]) -> dict[datetime, dict]:
    buckets: dict[datetime, dict] = {}
    for record in pit_records:
        metric = record.get("metric_value") or {}
        if metric.get("timeframe") != "1h":
            continue
        price = _as_float(metric.get("price"))
        observed_value = record.get("observed_at") or record.get("event_time")
        if price is None or price <= 0 or not observed_value:
            continue
        observed = _parse_time(observed_value)
        nominal_value = record.get("schedule_nominal_time")
        nominal = _parse_time(nominal_value) if nominal_value else _nominal_1h(observed)
        existing = buckets.get(nominal)
        if existing is None or observed < existing["observed_at_dt"]:
            buckets[nominal] = {
                "price": price,
                "observed_at": observed.isoformat(),
                "observed_at_dt": observed,
                "workflow_run_id": record.get("workflow_run_id"),
            }
    return buckets


def build_due_outcomes(
    events: Iterable[dict],
    pit_records: Iterable[dict],
    *,
    existing_keys: set[tuple[str, int]] | None = None,
) -> list[dict]:
    existing_keys = existing_keys or set()
    prices = _canonical_1h_prices(pit_records)
    due: list[dict] = []

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

            path_rows = [
                prices[nominal + timedelta(hours=offset)]
                for offset in range(1, horizon + 1)
                if nominal + timedelta(hours=offset) in prices
            ]
            if not path_rows:
                continue
            metrics = path_outcome(
                float(entry_price),
                [float(row["price"]) for row in path_rows],
            )
            direction = _as_int(event.get("rule_direction")) or 0
            sign = 1 if direction > 0 else -1 if direction < 0 else 0
            aligned = metrics["actual_return"] * sign if sign else None

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
                    "signal_aligned_return": aligned,
                    "path_bars": len(path_rows),
                    "expected_path_bars": horizon,
                    "path_complete": len(path_rows) == horizon,
                    "target_workflow_run_id": target_row.get("workflow_run_id"),
                }
            )
    return due


def persist_tactical_outcomes(outcomes: Iterable[dict], dsn: str | None = None) -> int:
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        return 0
    import psycopg

    inserted = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for outcome in outcomes:
                cur.execute(
                    "INSERT INTO eth_tactical_outcomes("
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


def _summary(rows: list[tuple[dict, dict]]) -> dict:
    if not rows:
        return {
            "n": 0,
            "mean_forward_return": None,
            "median_forward_return": None,
            "positive_return_rate": None,
            "mean_signal_aligned_return": None,
            "signal_hit_rate": None,
            "mean_mae": None,
            "mean_mfe": None,
            "complete_path_n": 0,
        }

    returns = [float(outcome["actual_return"]) for _, outcome in rows]
    aligned = [
        float(outcome["signal_aligned_return"])
        for _, outcome in rows
        if outcome.get("signal_aligned_return") is not None
    ]
    return {
        "n": len(rows),
        "mean_forward_return": _round(mean(returns)),
        "median_forward_return": _round(median(returns)),
        "positive_return_rate": _round(sum(value > 0 for value in returns) / len(returns)),
        "mean_signal_aligned_return": _round(mean(aligned)) if aligned else None,
        "signal_hit_rate": (
            _round(sum(value > 0 for value in aligned) / len(aligned)) if aligned else None
        ),
        "mean_mae": _round(mean(float(outcome["mae"]) for _, outcome in rows)),
        "mean_mfe": _round(mean(float(outcome["mfe"]) for _, outcome in rows)),
        "complete_path_n": sum(bool(outcome.get("path_complete")) for _, outcome in rows),
    }


def tactical_outcome_report(events: list[dict], outcomes: list[dict]) -> dict:
    events_by_id = {str(event["event_id"]): event for event in events if event.get("event_id")}
    normal_event_ids = {
        event_id
        for event_id, event in events_by_id.items()
        if str(event.get("data_health") or "UNKNOWN") == "NORMAL"
    }
    report = {
        "status": "DESCRIPTIVE_ONLY",
        "research_only": True,
        "event_version": EVENT_VERSION,
        "horizons": {},
        "event_count": len(events),
        "outcome_count": len(outcomes),
        "normal_event_count": len(normal_event_ids),
        "degraded_event_count": len(events) - len(normal_event_ids),
        "requested_cohorts": list(REQUESTED_COHORTS),
        "governance": {
            "auto_retuning": False,
            "auto_promotion": False,
            "trading_execution": False,
            "note": "Descriptive forward-outcome evidence only; no causal or predictive claim.",
        },
    }

    for horizon in HORIZON_HOURS:
        joined = [
            (events_by_id[str(outcome["event_id"])], outcome)
            for outcome in outcomes
            if int(outcome.get("horizon_hours") or 0) == horizon
            and str(outcome.get("event_id")) in normal_event_ids
        ]
        cohort_rows: dict[str, list[tuple[dict, dict]]] = {
            label: [] for label in REQUESTED_COHORTS
        }
        for event, outcome in joined:
            for label in event.get("cohorts") or []:
                cohort_rows.setdefault(str(label), []).append((event, outcome))

        report["horizons"][str(horizon)] = {
            "settled_n": len(joined),
            "overall": _summary(joined),
            "cohorts": {
                label: _summary(rows)
                for label, rows in sorted(cohort_rows.items())
            },
        }
    return report


def run_tactical_outcome_cycle(
    current: dict,
    *,
    previous: dict | None = None,
    confirmation_4h: dict | None = None,
    output_dir: str = "eth_reports/tactical-outcomes",
) -> dict:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        report = {
            "status": "SKIPPED_PERSISTENCE_UNAVAILABLE",
            "research_only": True,
            "event_record": {"status": "SKIPPED_PERSISTENCE_UNAVAILABLE"},
            "settled_now": 0,
        }
        (root / "tactical_outcomes_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report

    event, eligibility = build_tactical_event(
        current,
        previous=previous,
        confirmation_4h=confirmation_4h,
    )
    event_record = eligibility
    if event is not None:
        event_record = persist_tactical_event(event, dsn)

    events = load_tactical_events(dsn)
    existing_outcomes = load_tactical_outcomes(dsn)
    existing_keys = {
        (str(outcome.get("event_id")), int(outcome.get("horizon_hours") or 0))
        for outcome in existing_outcomes
    }
    pit_records = load_tactical_price_records(dsn)
    due = build_due_outcomes(events, pit_records, existing_keys=existing_keys)
    settled_now = persist_tactical_outcomes(due, dsn)
    all_outcomes = load_tactical_outcomes(dsn)
    report = tactical_outcome_report(events, all_outcomes)
    report["event_record"] = event_record
    report["settled_now"] = settled_now
    report["due_candidates"] = len(due)
    (root / "tactical_outcomes_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return report


def safe_run_tactical_outcome_cycle(
    current: dict,
    *,
    previous: dict | None = None,
    confirmation_4h: dict | None = None,
    output_dir: str = "eth_reports/tactical-outcomes",
) -> dict:
    try:
        return run_tactical_outcome_cycle(
            current,
            previous=previous,
            confirmation_4h=confirmation_4h,
            output_dir=output_dir,
        )
    except Exception as exc:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        report = {
            "status": "ERROR",
            "research_only": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        (root / "tactical_outcomes_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report
