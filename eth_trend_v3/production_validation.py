from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


HORIZON_HOURS = {"3d": 72, "7d": 168, "30d": 720}
EXPECTED_HORIZONS = tuple(HORIZON_HOURS)


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace(" UTC", "+00:00")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def shadow_overlap_diagnostics(records: Sequence[Mapping[str, Any]], *, horizon: str) -> dict:
    """Describe temporal span/overlap without converting diagnostics into statistical proof.

    The result is deliberately diagnostic only. `effective_shadow_confirmed` must still be
    established by the approved statistical review/gate rather than inferred from raw count.
    """
    if horizon not in HORIZON_HOURS:
        raise ValueError("unsupported horizon")

    normal = [
        dict(record)
        for record in records
        if record.get("settled")
        and record.get("data_health") == "NORMAL"
        and record.get("horizon") == horizon
    ]
    times = sorted(
        dt for dt in (_parse_utc(r.get("forecast_time")) for r in normal) if dt is not None
    )
    span_hours = None
    median_step_hours = None
    overlap_factor = None
    conservative_nonoverlap_opportunities = 0
    if len(times) >= 2:
        span_hours = (times[-1] - times[0]).total_seconds() / 3600.0
        steps = sorted((b - a).total_seconds() / 3600.0 for a, b in zip(times, times[1:]) if b > a)
        if steps:
            median_step_hours = steps[len(steps) // 2]
            if median_step_hours > 0:
                overlap_factor = max(1.0, HORIZON_HOURS[horizon] / median_step_hours)
        conservative_nonoverlap_opportunities = 1 + int(span_hours // HORIZON_HOURS[horizon])
    elif len(times) == 1:
        conservative_nonoverlap_opportunities = 1

    regimes = sorted({str(r.get("regime")) for r in normal if r.get("regime") not in (None, "")})
    return {
        "kind": "DIAGNOSTIC",
        "horizon": horizon,
        "settled_normal_n": len(normal),
        "timestamped_n": len(times),
        "temporal_span_hours": span_hours,
        "median_forecast_step_hours": median_step_hours,
        "overlap_factor_estimate": overlap_factor,
        "conservative_nonoverlap_opportunities": conservative_nonoverlap_opportunities,
        "regimes": regimes,
        "regime_count": len(regimes),
        "note": "Raw count/span/overlap diagnostics do not grant promotion; approved effective-sample evidence is still required.",
    }


def validate_production_summary(
    summary: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_hours: float = 8.0,
    notification_configured: bool | None = None,
) -> dict:
    """Validate the post-run production contract while allowing explicit fail-closed output."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []

    primary = summary.get("4h") if isinstance(summary, Mapping) else None
    if not isinstance(primary, Mapping):
        return {"ok": False, "errors": ["MISSING_4H_RECORD"], "warnings": []}

    ts = _parse_utc(primary.get("timestamp"))
    if ts is None:
        errors.append("INVALID_OR_MISSING_TIMESTAMP")
        age_hours = None
    else:
        age_hours = (now - ts).total_seconds() / 3600.0
        if age_hours < -0.25 or age_hours > max_age_hours:
            errors.append("STALE_OR_FUTURE_RECORD")

    health = primary.get("data_health") or {}
    health_status = health.get("status") if isinstance(health, Mapping) else None
    if not health_status:
        errors.append("MISSING_DATA_HEALTH")

    forecasts = primary.get("forecasts") or {}
    if not isinstance(forecasts, Mapping):
        errors.append("MISSING_FORECASTS")
        forecasts = {}

    horizon_reports = {}
    for horizon in EXPECTED_HORIZONS:
        forecast = forecasts.get(horizon)
        h_errors: list[str] = []
        if not isinstance(forecast, Mapping):
            h_errors.append("MISSING_FORECAST")
            horizon_reports[horizon] = {"ok": False, "errors": h_errors}
            errors.append(f"{horizon}:MISSING_FORECAST")
            continue

        probability = forecast.get("probability_up")
        status = forecast.get("status")
        reason = forecast.get("reason")
        baseline = forecast.get("baseline_probability")
        if baseline is None:
            metrics = forecast.get("metrics") or {}
            if isinstance(metrics, Mapping):
                baseline = metrics.get("base_rate")

        if probability is None:
            if status != "UNAVAILABLE":
                h_errors.append("NULL_PROBABILITY_NOT_UNAVAILABLE")
            if not reason:
                h_errors.append("UNAVAILABLE_WITHOUT_REASON")
        else:
            try:
                p = float(probability)
            except (TypeError, ValueError):
                h_errors.append("INVALID_PROBABILITY")
            else:
                if not 0.0 <= p <= 1.0:
                    h_errors.append("PROBABILITY_OUT_OF_RANGE")
            if status != "PRODUCTION":
                h_errors.append("PUBLISHED_PROBABILITY_NOT_PRODUCTION")
            if baseline is None:
                h_errors.append("MISSING_BASELINE")
            approval = forecast.get("production_approval")
            if not isinstance(approval, Mapping):
                h_errors.append("MISSING_PRODUCTION_APPROVAL")
            else:
                if forecast.get("model_version") != approval.get("model_version"):
                    h_errors.append("MODEL_VERSION_MISMATCH")
                if forecast.get("artifact_hash") != approval.get("artifact_hash"):
                    h_errors.append("MODEL_ARTIFACT_MISMATCH")
            if health_status != "NORMAL":
                h_errors.append("PUBLISHED_WITH_NON_NORMAL_DATA_HEALTH")

        if h_errors:
            errors.extend(f"{horizon}:{item}" for item in h_errors)
        horizon_reports[horizon] = {
            "ok": not h_errors,
            "errors": h_errors,
            "status": status,
            "reason": reason,
            "baseline_available": baseline is not None,
        }

    notification = primary.get("notification")
    execution_gate_notification = primary.get("execution_gate_notification")
    notification_reports = {
        "primary": notification if isinstance(notification, Mapping) else None,
        "execution_gate": execution_gate_notification if isinstance(execution_gate_notification, Mapping) else None,
    }
    if notification_configured is False:
        warnings.append("TELEGRAM_NOT_CONFIGURED")
    elif notification_configured is True:
        for name, item in notification_reports.items():
            if not isinstance(item, Mapping):
                errors.append(f"MISSING_{name.upper()}_NOTIFICATION_STATUS")
                continue
            if item.get("status") != "SENT":
                errors.append(f"{name.upper()}_NOTIFICATION_NOT_SENT")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "timestamp": primary.get("timestamp"),
        "age_hours": age_hours,
        "data_health": health_status,
        "notification_configured": notification_configured,
        "notifications": notification_reports,
        "horizons": horizon_reports,
    }
