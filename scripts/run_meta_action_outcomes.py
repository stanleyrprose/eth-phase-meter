#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from eth_trend_v3.meta_action_outcomes import safe_run_meta_action_outcome_cycle
from eth_trend_v3.meta_notification import (
    TelegramCredentials,
    format_meta_notification,
    send_telegram_message,
)


def _decode_event(value: str) -> dict:
    raw = base64.b64decode(value.encode("ascii"), validate=True)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("event_id"):
        raise ValueError("META_ACTION_EVENT_INVALID")
    return payload


def _github_fallback_notification(event: dict) -> dict:
    notification = event.get("notification") or {}
    if not bool(notification.get("fallback_requested")):
        return {"status": "NOT_REQUESTED", "attempted": False}

    token = str(os.getenv("TG_BOT_TOKEN") or "").strip()
    chat_id = str(os.getenv("TG_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return {"status": "SKIPPED_UNCONFIGURED", "attempted": False}

    meta = dict(event.get("meta_snapshot") or {})
    meta["_notification_previous_recommendation"] = notification.get(
        "previous_recommendation"
    )
    meta["_notification_change_type"] = notification.get("change_type") or "UNCHANGED"
    credentials = TelegramCredentials(token, chat_id, "github_actions")
    try:
        send_telegram_message(credentials, format_meta_notification(meta))
    except Exception as exc:
        return {
            "status": "SEND_FAILED",
            "attempted": True,
            "error_code": f"TELEGRAM_SEND_FAILED:{type(exc).__name__}",
        }
    return {"status": "SENT_GITHUB_FALLBACK", "attempted": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Persist one Meta Action event, settle due outcomes, and optionally deliver TG fallback."
    )
    parser.add_argument("--event-b64", required=True)
    parser.add_argument("--output-dir", default="eth_reports/meta-action-outcomes")
    args = parser.parse_args(argv)

    event = _decode_event(args.event_b64)
    notification = _github_fallback_notification(event)
    report = safe_run_meta_action_outcome_cycle(event, output_dir=args.output_dir)
    report["github_fallback_notification"] = notification

    output = Path(args.output_dir) / "meta_action_outcomes_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(
        "Meta Action Research: "
        f"event={event['event_id']} status={report.get('status')} "
        f"tg={notification.get('status')} settled_now={report.get('settled_now', 0)}"
    )
    return 1 if report.get("status") == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
