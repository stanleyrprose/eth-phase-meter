from __future__ import annotations

import argparse
import html
import json
import os
from urllib import request


def build_message(*, component: str, status: str, reason: str, impact: str) -> str:
    icon = "⚠️" if status.upper() != "RECOVERED" else "✅"
    return "\n".join([
        f"{icon} <b>ETH System Health</b>",
        f"Component: <b>{html.escape(component)}</b>",
        f"Status: <b>{html.escape(status.upper())}</b>",
        f"Reason: <b>{html.escape(reason)}</b>",
        f"Impact: {html.escape(impact)}",
    ])


def send_message(text: str) -> dict:
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        return {"status": "SKIPPED", "reason": "NOT_CONFIGURED"}

    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            return {"status": "SENT", "http_status": int(response.status)}
    except Exception as exc:
        return {"status": "FAILED", "error": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="Send an operational ETH system-health alert.")
    parser.add_argument("--component", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--impact", required=True)
    args = parser.parse_args()

    result = send_message(build_message(
        component=args.component,
        status=args.status,
        reason=args.reason,
        impact=args.impact,
    ))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
