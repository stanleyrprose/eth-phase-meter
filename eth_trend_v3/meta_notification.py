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


_BUY_DECISIONS = {"BUY", "STRONG BUY", "ADD", "ACCUMULATE"}
_SELL_DECISIONS = {"SELL", "STRONG SELL", "REDUCE", "EXIT"}

_ACTION_META = {
    "ADD": ("🟢", "增加现有 ETH directional exposure（不自动下单）"),
    "HOLD": ("🟡", "保持当前 exposure，不因本次信号调整"),
    "REDUCE": ("🟠", "降低现有 ETH directional exposure；不等于开空"),
    "AVOID": ("⛔", "不新增方向性 exposure，等待冲突、数据或风险条件解除"),
}

_REASON_TEXT = {
    "TRADINGAGENTS_CONTRACT_INVALID": "TradingAgents contract 无效",
    "TRADINGAGENTS_DECISION_UNKNOWN": "TradingAgents decision 无法识别",
    "ASSET_MISMATCH": "资产标的不一致",
    "TRADINGAGENTS_STALE_OR_TIMESTAMP_INVALID": "TradingAgents 结果过期或时间戳无效",
    "PHASE_DATA_GATED": "Phase Meter 数据健康/覆盖率未通过",
    "PHASE_DATA_STALE_OR_TIMESTAMP_INVALID": "Phase Meter 数据过期或时间戳无效",
    "EXTREME_VOLATILITY_RISK": "波动风险过高",
    "1H_4H_STRONG_CONFLICT": "1H 与 4H 出现强方向冲突",
    "CROSS_SYSTEM_CONFLICT": "TradingAgents 与 Phase Meter 出现强方向冲突",
    "CONSTRUCTIVE_BUT_UNCONFIRMED": "偏正但确认不足",
    "BEARISH_BUT_UNCONFIRMED": "偏空但确认不足",
    "BUY_SIGNAL_LACKS_MULTI_TIMEFRAME_CONFIRMATION": "TradingAgents 看多，但多周期确认不足",
    "SELL_SIGNAL_LACKS_MULTI_TIMEFRAME_CONFIRMATION": "TradingAgents 看空，但多周期确认不足",
    "NO_CROSS_SYSTEM_EDGE": "跨系统尚无明确方向优势",
}


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score(value) -> str:
    number = _number(value)
    if number is None:
        return "UNKNOWN"
    return f"{number:+.0f}" if number.is_integer() else f"{number:+.1f}"


def _plain(value) -> str:
    number = _number(value)
    if number is None:
        return "UNKNOWN"
    return f"{number:.0f}" if number.is_integer() else f"{number:.1f}"


def _transition_text(current: str, previous: str | None, change_type: str) -> str:
    if change_type == "BASELINE":
        return f"BASELINE ({current})"
    if change_type == "UNCHANGED":
        return f"UNCHANGED ({current})"
    return f"{previous or 'UNKNOWN'} → {current}"


def _hold_confirmation_lines(
    ta_decision: str,
    one_hour: Mapping,
    four_hour: Mapping,
) -> list[str]:
    d1 = _number(one_hour.get("direction"))
    d4 = _number(four_hour.get("direction"))
    momentum = _number(four_hour.get("momentum"))
    order_flow = _number(four_hour.get("order_flow"))
    options = _number(four_hour.get("options_positioning"))

    missing: list[str] = []
    if ta_decision in _BUY_DECISIONS:
        if d4 is None or d4 < 25:
            missing.append(f"ADD 缺失：4H direction {_score(d4)} < +25")
        if d1 is None or d1 < 15:
            missing.append(f"ADD 缺失：1H direction {_score(d1)} < +15")
        if momentum is None or momentum < 20:
            missing.append(f"ADD 缺失：Momentum {_score(momentum)} < +20")
        if order_flow is None or order_flow <= 0:
            missing.append(f"ADD 缺失：Order Flow {_score(order_flow)} <= 0")
        if options is None or options < -25:
            missing.append(f"ADD 缺失：Options {_score(options)} < -25")
    elif ta_decision in _SELL_DECISIONS:
        if d4 is None or d4 > -20:
            missing.append(f"REDUCE 缺失：4H direction {_score(d4)} > -20")
        if d1 is None or d1 > -10:
            missing.append(f"REDUCE 缺失：1H direction {_score(d1)} > -10")
        if (momentum is None or momentum > 0) and (order_flow is None or order_flow > 0):
            missing.append("REDUCE 缺失：Momentum / Order Flow 尚未恶化到 <= 0")
    else:
        missing.append("TradingAgents 尚未给出 BUY/SELL 方向确认")

    return missing or ["尚未达到 ADD/REDUCE 的完整多系统确认条件"]


def notification_action(current: str, last_notified: str | None, *, has_baseline: bool) -> str:
    """Send one action snapshot for every newly processed 4H monitor artifact."""
    if not has_baseline:
        return "SEND_BASELINE"
    if current == last_notified:
        return "SEND_UNCHANGED"
    return "SEND_CHANGE"


def format_meta_notification(meta: Mapping) -> str:
    sources = meta.get("sources") or {}
    tradingagents = sources.get("tradingagents") or {}
    phase = sources.get("phase_meter") or {}
    kronos = sources.get("kronos") or {}
    one_hour = phase.get("1h") or {}
    four_hour = phase.get("4h") or {}

    recommendation = str(meta.get("recommendation") or "UNKNOWN").upper()
    previous = meta.get("_notification_previous_recommendation")
    change_type = str(meta.get("_notification_change_type") or "CHANGED")
    alignment = str(meta.get("evidence_alignment") or "UNKNOWN")
    reasons = [str(value) for value in (meta.get("reason_codes") or [])]
    ta_decision = str(tradingagents.get("decision") or "UNKNOWN").upper()

    icon, exposure = _ACTION_META.get(
        recommendation,
        ("⚪", "仅作研究观察；当前 action 无法识别"),
    )

    lines = [
        "🎯 ETH ACTION [4H]",
        f"Action: {icon} {recommendation}",
        f"Exposure: {exposure}",
        f"证据一致性: {alignment}",
        f"状态: {_transition_text(recommendation, str(previous) if previous is not None else None, change_type)}",
        "",
        "🔎 Key Evidence",
        f"TradingAgents: {ta_decision}",
        f"4H: {_score(four_hour.get('direction'))} | {four_hour.get('regime') or 'UNKNOWN'}",
        f"1H: {_score(one_hour.get('direction'))} | {one_hour.get('regime') or 'UNKNOWN'}",
        (
            f"Momentum: {_score(four_hour.get('momentum'))} | "
            f"Order Flow: {_score(four_hour.get('order_flow'))}"
        ),
        (
            f"Options: {_score(four_hour.get('options_positioning'))} | "
            f"Vol Risk: {_plain(four_hour.get('volatility_risk'))}"
        ),
    ]

    lines.extend(["", "🧩 Decision"])
    if recommendation == "HOLD":
        lines.extend(f"• {item}" for item in _hold_confirmation_lines(ta_decision, one_hour, four_hour))
    elif recommendation == "ADD":
        lines.append("• TradingAgents + 4H + 1H + momentum + order flow + options 已满足 ADD 确认")
    elif recommendation == "REDUCE":
        lines.append("• TradingAgents + 4H + 1H + momentum/order flow 已满足 REDUCE 确认")
    elif recommendation == "AVOID":
        blocking = reasons or ["UNKNOWN_BLOCK"]
        lines.extend(f"• 阻断：{_REASON_TEXT.get(code, code)}" for code in blocking)

    if reasons:
        lines.append(f"Reason codes: {', '.join(reasons)}")

    kronos_bias = kronos.get("bias")
    kronos_alignment = kronos.get("shadow_alignment")
    if kronos_bias or kronos_alignment:
        lines.extend(
            [
                "",
                (
                    "Kronos Shadow: "
                    f"{kronos_bias or 'UNAVAILABLE'} / "
                    f"{kronos_alignment or 'UNAVAILABLE'}"
                ),
            ]
        )

    lines.extend(
        [
            "",
            f"生成时间: {meta.get('generated_at') or 'UNKNOWN'}",
            "仅作研究型决策支持；不会自动下单，也不会改变 production forecast/model state。",
        ]
    )
    return "\n".join(lines)


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
    """Send the current Action-first snapshot once per newly processed monitor run."""
    current = str(meta.get("recommendation") or "UNKNOWN")

    previous_value = state.get("last_notified_recommendation")
    if previous_value is None:
        previous_value = state.get("last_meta_recommendation")
    has_baseline = previous_value is not None
    previous = str(previous_value) if previous_value is not None else None

    policy_action = notification_action(current, previous, has_baseline=has_baseline)
    change_type = (
        "BASELINE"
        if not has_baseline
        else "UNCHANGED"
        if current == previous
        else "CHANGED"
    )
    status = {
        "status": policy_action,
        "policy_action": policy_action,
        "change_type": change_type,
        "attempted": False,
        "previous_recommendation": previous,
        "current_recommendation": current,
    }

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
    message_meta["_notification_change_type"] = change_type
    try:
        sender(resolution.credentials, format_meta_notification(message_meta))
    except Exception as exc:
        status["status"] = "SEND_FAILED"
        status["error_code"] = f"TELEGRAM_SEND_FAILED:{type(exc).__name__}"
        return status, previous
    status["status"] = "SENT"
    return status, current
