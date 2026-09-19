from __future__ import annotations

import datetime as dt
from typing import Any

KRONOS_EVIDENCE_CONTRACT_VERSION = "kronos-evidence-v1"


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def validate_kronos_evidence(
    payload: dict[str, Any] | None,
    *,
    now: dt.datetime | None = None,
    max_age_hours: float = 24.0,
) -> dict[str, Any]:
    """Validate research-only Kronos evidence without promoting it into a forecast probability."""
    payload = payload or {}
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    current = current.astimezone(dt.timezone.utc)

    reasons: list[str] = []
    contract_ok = payload.get("contract_version") == KRONOS_EVIDENCE_CONTRACT_VERSION
    if not contract_ok:
        reasons.append("KRONOS_CONTRACT_INVALID")

    asset = str(payload.get("asset") or "").upper()
    asset_ok = asset in {"ETH-USD", "ETHUSD", "ETHUSDT"}
    if not asset_ok:
        reasons.append("KRONOS_ASSET_MISMATCH")

    mode = str(payload.get("mode") or "").upper()
    shadow_only = mode == "SHADOW"
    if not shadow_only:
        reasons.append("KRONOS_NOT_SHADOW")

    generated = _parse_timestamp(payload.get("generated_at"))
    fresh = False
    if generated is not None:
        age = (current - generated).total_seconds()
        fresh = -300 <= age <= max_age_hours * 3600
    if not fresh:
        reasons.append("KRONOS_STALE_OR_TIMESTAMP_INVALID")

    horizons = payload.get("horizons") or {}
    valid_horizons: dict[str, dict[str, Any]] = {}
    for timeframe in ("1h", "4h"):
        item = horizons.get(timeframe) or {}
        score = _number(item.get("direction_score"))
        terminal = _number(item.get("median_terminal_return_pct"))
        if score is None or terminal is None:
            continue
        valid_horizons[timeframe] = {
            "direction_score": max(-100.0, min(100.0, score)),
            "median_terminal_return_pct": terminal,
            "sample_count": int(item.get("sample_count") or 0),
            "terminal_return_std_pct": _number(item.get("terminal_return_std_pct")),
            "sample_directional_agreement_pct": _number(item.get("sample_directional_agreement_pct")),
            "pred_len": int(item.get("pred_len") or 0),
            "lookback": int(item.get("lookback") or 0),
        }

    usable = contract_ok and asset_ok and shadow_only and fresh and bool(valid_horizons)
    if not valid_horizons:
        reasons.append("KRONOS_NO_VALID_HORIZONS")

    score4 = (valid_horizons.get("4h") or {}).get("direction_score")
    score1 = (valid_horizons.get("1h") or {}).get("direction_score")
    preferred_score = score4 if score4 is not None else score1
    if preferred_score is None:
        bias = "UNAVAILABLE"
    elif preferred_score >= 10:
        bias = "BULLISH"
    elif preferred_score <= -10:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "usable": usable,
        "fresh": fresh,
        "shadow_only": shadow_only,
        "bias": bias,
        "preferred_direction_score": preferred_score,
        "horizons": valid_horizons,
        "reason_codes": reasons,
    }


def compare_kronos_to_phase(
    monitor: dict[str, Any],
    validated: dict[str, Any],
) -> str:
    """Return descriptive cross-model alignment. It never changes the production recommendation."""
    if not validated.get("usable"):
        return "UNAVAILABLE"
    phase4 = _number((monitor.get("4h") or {}).get("rule_direction"))
    kronos4 = _number(validated.get("preferred_direction_score"))
    if phase4 is None or kronos4 is None:
        return "UNAVAILABLE"
    if abs(phase4) < 10 or abs(kronos4) < 10:
        return "MIXED"
    return "SUPPORTS" if phase4 * kronos4 > 0 else "CONFLICTS"
