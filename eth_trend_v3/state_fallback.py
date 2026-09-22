from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .persistence import load_latest_record


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _monitor_entry(path: Path, timeframe: str) -> dict | None:
    payload = _read_json(path)
    if not payload:
        return None
    value = payload.get(timeframe)
    return value if isinstance(value, dict) else None


def load_fallback_record(record_type: str, *, state_root: str | Path = ".state") -> tuple[dict | None, str | None]:
    root = Path(state_root)

    if record_type == "monitor_state_1h":
        candidates = [
            (root / "tactical" / "latest_tactical_1h.json", None, "ARTIFACT_TACTICAL"),
            (root / "tactical" / "v3_snapshot_1h.json", None, "ARTIFACT_TACTICAL"),
            (root / "strategic" / "latest_monitor.json", "1h", "ARTIFACT_STRATEGIC"),
            (root / "strategic" / "v3_snapshot_1h.json", None, "ARTIFACT_STRATEGIC"),
        ]
    elif record_type == "monitor_state_4h":
        candidates = [
            (root / "strategic" / "latest_monitor.json", "4h", "ARTIFACT_STRATEGIC"),
            (root / "strategic" / "v3_snapshot_4h.json", None, "ARTIFACT_STRATEGIC"),
        ]
    else:
        return None, None

    for path, key, source in candidates:
        if not path.exists():
            continue
        value = _monitor_entry(path, key) if key else _read_json(path)
        if value:
            return value, source
    return None, None


def load_state_record(record_type: str, *, state_root: str | Path = ".state") -> tuple[dict | None, str]:
    durable = load_latest_record(record_type)
    if durable:
        return durable, "POSTGRES"
    fallback, source = load_fallback_record(record_type, state_root=state_root)
    return fallback, source or "UNAVAILABLE"


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "+00:00")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def state_age_hours(record: dict | None, *, now: datetime | None = None) -> float | None:
    if not record:
        return None
    stamp = _parse_utc(record.get("timestamp"))
    if stamp is None:
        return None
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return max(0.0, (current - stamp).total_seconds() / 3600.0)
