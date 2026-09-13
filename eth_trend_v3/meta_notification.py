from __future__ import annotations

import json
import os
import stat
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping


@dataclass(frozen=True)
class TelegramCredentials:
    bot_token: str = field(repr=False)
    chat_id: str = field(repr=False)
    source: str


@dataclass(frozen=True)
class CredentialResolution:
    status: str
    credentials: TelegramCredentials | None = None
    error_code: str | None = None


def notification_action(current: str, last_notified: str | None, *, has_baseline: bool) -> str:
    """Return the change-only policy action without performing I/O."""
    if not has_baseline:
        return "BASELINE"
    if current == last_notified:
        return "NO_CHANGE"
    return "SEND"


def format_meta_notification(meta: Mapping) -> str:
    sources = meta.get("sources") or {}
    tradingagents = sources.get("tradingagents") or {}
    phase = sources.get("phase_meter") or {}
    one_hour = phase.get("1h") or {}
    four_hour = phase.get("4h") or {}
    previous = meta.get("_notification_previous_recommendation") or "UNKNOWN"
    reasons = ", ".join(str(value) for value in (meta.get("reason_codes") or [])) or "NONE"
    return "\n".join(
        [
            f"ETH Meta 变化：{previous} → {meta.get('recommendation') or 'UNKNOWN'}",
            f"证据一致性：{meta.get('evidence_alignment') or 'UNKNOWN'}",
            f"原因：{reasons}",
            f"TradingAgents：{tradingagents.get('decision') or 'UNKNOWN'}",
            (
                "Phase："
                f"1h {one_hour.get('direction', 'UNKNOWN')} / {one_hour.get('regime') or 'UNKNOWN'}；"
                f"4h {four_hour.get('direction', 'UNKNOWN')} / {four_hour.get('regime') or 'UNKNOWN'}"
            ),
            f"生成时间：{meta.get('generated_at') or 'UNKNOWN'}",
        ]
    )


def resolve_telegram_credentials(
    secret_file: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> CredentialResolution:
    env = os.environ if environ is None else environ
    env_token = str(env.get("TG_BOT_TOKEN") or "").strip()
    env_chat_id = str(env.get("TG_CHAT_ID") or "").strip()
    if env_token or env_chat_id:
        if not env_token or not env_chat_id:
            return CredentialResolution("INVALID", error_code="ENV_CREDENTIALS_INCOMPLETE")
        return CredentialResolution(
            "CONFIGURED",
            TelegramCredentials(env_token, env_chat_id, "environment"),
        )

    if not secret_file.exists():
        return CredentialResolution("UNCONFIGURED")
    try:
        mode = stat.S_IMODE(secret_file.stat().st_mode)
    except OSError:
        return CredentialResolution("INVALID", error_code="SECRET_FILE_STAT_FAILED")
    if mode & 0o077:
        return CredentialResolution("INVALID", error_code="SECRET_FILE_PERMISSIONS_INSECURE")
    try:
        payload = json.loads(secret_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return CredentialResolution("INVALID", error_code="SECRET_FILE_INVALID")
    if not isinstance(payload, dict):
        return CredentialResolution("INVALID", error_code="SECRET_FILE_INVALID")
    token = str(payload.get("bot_token") or "").strip()
    chat_id = str(payload.get("chat_id") or "").strip()
    if not token or not chat_id:
        return CredentialResolution("INVALID", error_code="SECRET_FILE_CREDENTIALS_INCOMPLETE")
    return CredentialResolution(
        "CONFIGURED",
        TelegramCredentials(token, chat_id, "secret_file"),
    )


def send_telegram_message(
    credentials: TelegramCredentials,
    message: str,
    *,
    timeout_seconds: float = 10.0,
    opener: Callable = urllib.request.urlopen,
) -> None:
    body = urllib.parse.urlencode(
        {"chat_id": credentials.chat_id, "text": message, "disable_web_page_preview": "true"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{credentials.bot_token}/sendMessage",
        data=body,
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"TELEGRAM_SEND_FAILED:{type(exc).__name__}") from None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("TELEGRAM_SEND_FAILED:API_REJECTED")


def process_meta_notification(
    meta: Mapping,
    state: Mapping,
    *,
    secret_file: Path,
    environ: Mapping[str, str] | None = None,
    sender: Callable[[TelegramCredentials, str], None] = send_telegram_message,
) -> tuple[dict, str | None]:
    """Evaluate and perform notification, returning status and the new durable baseline."""
    current = str(meta.get("recommendation") or "UNKNOWN")
    if "last_notified_recommendation" in state:
        previous_value = state.get("last_notified_recommendation")
        has_baseline = True
    elif "last_meta_recommendation" in state:
        previous_value = state.get("last_meta_recommendation")
        has_baseline = True
    else:
        previous_value = None
        has_baseline = False
    previous = str(previous_value) if previous_value is not None else None
    action = notification_action(current, previous, has_baseline=has_baseline)
    status = {
        "status": action,
        "attempted": False,
        "previous_recommendation": previous,
        "current_recommendation": current,
    }
    if action == "BASELINE":
        status["status"] = "BASELINE_INITIALIZED"
        return status, current
    if action == "NO_CHANGE":
        return status, previous

    resolution = resolve_telegram_credentials(secret_file, environ=environ)
    if resolution.status == "UNCONFIGURED":
        status["status"] = "SKIPPED_UNCONFIGURED"
        return status, current
    if resolution.status != "CONFIGURED" or resolution.credentials is None:
        status["status"] = "CONFIGURATION_ERROR"
        status["error_code"] = resolution.error_code
        return status, previous

    status["attempted"] = True
    status["credential_source"] = resolution.credentials.source
    message_meta = dict(meta)
    message_meta["_notification_previous_recommendation"] = previous
    try:
        sender(resolution.credentials, format_meta_notification(message_meta))
    except Exception as exc:
        status["status"] = "SEND_FAILED"
        status["error_code"] = f"TELEGRAM_SEND_FAILED:{type(exc).__name__}"
        return status, previous
    status["status"] = "SENT"
    return status, current
