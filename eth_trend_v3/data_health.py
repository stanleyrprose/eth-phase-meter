from __future__ import annotations
from datetime import datetime, timezone

MAX_AGE = {
    "candles": 21600,
    "derivatives": 21600,
    "options": 43200,
    "sentiment": 129600,
    "macro": 129600,
    "valuation": 259200,
    "capital_flow": 259200,
    "structural": 259200,
}


def _present(value) -> bool:
    if value is None:
        return False
    if hasattr(value, "empty"):
        return not bool(value.empty)
    if isinstance(value, (dict, list, tuple, set, str)):
        return len(value) > 0
    return True


def assess(raw: dict, factor_coverage: float) -> dict:
    meta = raw.get("_meta") or {}
    stale = []
    errors = []
    status_by = {}
    now = datetime.now(timezone.utc)

    for src in MAX_AGE:
        m = meta.get(src) or {}
        observed = m.get("observed_at")
        age = None
        if observed:
            try:
                age = (now - datetime.fromisoformat(observed.replace("Z", "+00:00"))).total_seconds()
            except Exception:
                pass

        value = raw.get(src)
        present = _present(value)
        is_stale = bool(age is not None and age > MAX_AGE[src])
        err = value.get("_error") if isinstance(value, dict) else None

        if is_stale:
            stale.append(src)
        if err:
            errors.append(f"{src}:{err}")
        status_by[src] = {
            "present": present,
            "age_seconds": age,
            "stale": is_stale,
            "error": err,
        }

    status = (
        "DATA_INSUFFICIENT"
        if factor_coverage < 50
        else "DEGRADED"
        if factor_coverage < 70 or stale or errors
        else "NORMAL"
    )
    return {
        "status": status,
        "coverage": factor_coverage,
        "stale_sources": stale,
        "errors": errors,
        "sources": status_by,
    }
