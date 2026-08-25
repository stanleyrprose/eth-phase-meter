from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from eth_trend_v3.persistence import load_latest_record
from eth_trend_v3.production_validation import validate_production_summary


def _load_summary() -> tuple[dict, str]:
    latest = load_latest_record("monitor_state_4h")
    if latest:
        # Normalize the durable single 4h record into the same shape as latest_monitor.json.
        return {"4h": latest}, "POSTGRES"

    path = Path("eth_reports/latest_monitor.json")
    if not path.exists():
        raise RuntimeError("latest monitor artifact is missing")
    return json.loads(path.read_text(encoding="utf-8")), "ARTIFACT"


def main() -> None:
    summary, source = _load_summary()
    notification_configured = bool(os.getenv("TG_BOT_TOKEN") and os.getenv("TG_CHAT_ID"))
    primary = summary.get("4h") if isinstance(summary, dict) else None
    notification_status = primary.get("notification") if isinstance(primary, dict) else None
    report = validate_production_summary(
        summary,
        now=datetime.now(timezone.utc),
        notification_configured=notification_configured,
        notification_status=notification_status,
    )
    report["source"] = source
    target = Path("eth_reports/forecast-research/production_validation.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if not report.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
