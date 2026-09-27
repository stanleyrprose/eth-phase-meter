import json

from eth_trend_v3.meta_notification import (
    TelegramCredentials,
    format_meta_notification,
    process_meta_notification,
    resolve_telegram_credentials,
    send_telegram_message,
)


def _meta(recommendation="HOLD"):
    return {
        "generated_at": "2026-09-13T00:00:00+00:00",
        "recommendation": recommendation,
        "evidence_alignment": "MEDIUM",
        "reason_codes": ["CONSTRUCTIVE_BUT_UNCONFIRMED"],
        "sources": {
            "tradingagents": {"decision": "HOLD"},
            "phase_meter": {
                "1h": {"direction": 12.0, "regime": "Range"},
                "4h": {
                    "direction": 22.0,
                    "regime": "Transition",
                    "momentum": 18.0,
                    "order_flow": 4.0,
                    "options_positioning": -10.0,
                    "volatility_risk": 25.0,
                },
            },
        },
    }


def _configured_env():
    return {"TG_BOT_TOKEN": "test-token", "TG_CHAT_ID": "test-chat"}


def test_first_baseline_sends_action_snapshot(tmp_path):
    calls = []
    status, baseline = process_meta_notification(
        _meta(),
        {},
        secret_file=tmp_path / "missing.json",
        environ=_configured_env(),
        sender=lambda credentials, message: calls.append((credentials, message)),
    )
    assert status["status"] == "SENT"
    assert status["policy_action"] == "SEND_BASELINE"
    assert status["change_type"] == "BASELINE"
    assert status["attempted"] is True
    assert baseline == "HOLD"
    assert len(calls) == 1
    assert "🎯 ETH ACTION [4H]" in calls[0][1]
    assert "Action: 🟡 HOLD" in calls[0][1]
    assert "BASELINE (HOLD)" in calls[0][1]


def test_no_change_still_sends_current_action_snapshot(tmp_path):
    calls = []
    status, baseline = process_meta_notification(
        _meta(),
        {"last_notified_recommendation": "HOLD"},
        secret_file=tmp_path / "missing.json",
        environ=_configured_env(),
        sender=lambda credentials, message: calls.append((credentials, message)),
    )
    assert status["status"] == "SENT"
    assert status["policy_action"] == "SEND_UNCHANGED"
    assert status["change_type"] == "UNCHANGED"
    assert baseline == "HOLD"
    assert len(calls) == 1
    assert "UNCHANGED (HOLD)" in calls[0][1]
    assert "TradingAgents 尚未给出 BUY/SELL 方向确认" in calls[0][1]


def test_legacy_meta_baseline_same_value_sends_snapshot(tmp_path):
    calls = []
    status, baseline = process_meta_notification(
        _meta(),
        {"last_meta_recommendation": "HOLD"},
        secret_file=tmp_path / "missing.json",
        environ=_configured_env(),
        sender=lambda credentials, message: calls.append((credentials, message)),
    )
    assert status["status"] == "SENT"
    assert status["policy_action"] == "SEND_UNCHANGED"
    assert status["previous_recommendation"] == "HOLD"
    assert baseline == "HOLD"
    assert len(calls) == 1


def test_legacy_meta_baseline_changed_value_notifies(tmp_path):
    calls = []
    status, baseline = process_meta_notification(
        _meta("REDUCE"),
        {"last_meta_recommendation": "HOLD"},
        secret_file=tmp_path / "missing.json",
        environ=_configured_env(),
        sender=lambda credentials, message: calls.append((credentials, message)),
    )
    assert status["status"] == "SENT"
    assert status["policy_action"] == "SEND_CHANGE"
    assert status["previous_recommendation"] == "HOLD"
    assert baseline == "REDUCE"
    assert len(calls) == 1
    assert "HOLD → REDUCE" in calls[0][1]


def test_change_success_advances_last_notified_and_formats_action_first_evidence(tmp_path):
    calls = []
    meta = _meta("ADD")
    meta["sources"]["tradingagents"]["decision"] = "BUY"
    status, baseline = process_meta_notification(
        meta,
        {"last_notified_recommendation": "HOLD"},
        secret_file=tmp_path / "missing.json",
        environ=_configured_env(),
        sender=lambda credentials, message: calls.append((credentials, message)),
    )
    assert status["status"] == "SENT"
    assert status["policy_action"] == "SEND_CHANGE"
    assert status["credential_source"] == "environment"
    assert baseline == "ADD"
    assert len(calls) == 1
    message = calls[0][1]
    assert message.startswith("🎯 ETH ACTION [4H]\nAction: 🟢 ADD")
    assert "Exposure: 增加现有 ETH directional exposure（不自动下单）" in message
    assert "状态: HOLD → ADD" in message
    assert "证据一致性: MEDIUM" in message
    assert "TradingAgents: BUY" in message
    assert "1H: +12 | Range" in message
    assert "4H: +22 | Transition" in message
    assert "Reason codes: CONSTRUCTIVE_BUT_UNCONFIRMED" in message
    assert "2026-09-13T00:00:00+00:00" in message
    assert "不会自动下单" in message


def test_hold_with_bullish_ta_shows_missing_confirmation():
    meta = _meta("HOLD")
    meta["sources"]["tradingagents"]["decision"] = "BUY"
    message = format_meta_notification(meta)
    assert "ADD 缺失：4H direction +22 < +25" in message
    assert "ADD 缺失：1H direction +12 < +15" in message
    assert "ADD 缺失：Momentum +18 < +20" in message


def test_change_failure_keeps_baseline_and_later_call_retries(tmp_path):
    attempts = []

    def fail(credentials, message):
        attempts.append(message)
        raise OSError("transient test failure")

    state = {"last_notified_recommendation": "HOLD"}
    failed, baseline = process_meta_notification(
        _meta("REDUCE"),
        state,
        secret_file=tmp_path / "missing.json",
        environ=_configured_env(),
        sender=fail,
    )
    assert failed["status"] == "SEND_FAILED"
    assert failed["error_code"] == "TELEGRAM_SEND_FAILED:OSError"
    assert baseline == "HOLD"

    succeeded, retried_baseline = process_meta_notification(
        _meta("REDUCE"),
        {"last_notified_recommendation": baseline},
        secret_file=tmp_path / "missing.json",
        environ=_configured_env(),
        sender=lambda credentials, message: attempts.append(message),
    )
    assert succeeded["status"] == "SENT"
    assert retried_baseline == "REDUCE"
    assert len(attempts) == 2


def test_unconfigured_change_skips_and_syncs_baseline(tmp_path):
    status, baseline = process_meta_notification(
        _meta("AVOID"),
        {"last_notified_recommendation": "HOLD"},
        secret_file=tmp_path / "missing.json",
        environ={},
        sender=lambda credentials, message: (_ for _ in ()).throw(AssertionError("must not send")),
    )
    assert status["status"] == "SKIPPED_UNCONFIGURED"
    assert status["policy_action"] == "SEND_CHANGE"
    assert status["attempted"] is False
    assert baseline == "AVOID"


def test_insecure_secret_file_is_retryable_configuration_error(tmp_path):
    secret = tmp_path / "telegram.json"
    secret.write_text(json.dumps({"bot_token": "file-token", "chat_id": "file-chat"}), encoding="utf-8")
    secret.chmod(0o644)
    status, baseline = process_meta_notification(
        _meta("ADD"),
        {"last_notified_recommendation": "HOLD"},
        secret_file=secret,
        environ={},
    )
    assert status["status"] == "CONFIGURATION_ERROR"
    assert status["error_code"] == "SECRET_FILE_PERMISSIONS_INSECURE"
    assert baseline == "HOLD"
    assert "file-token" not in repr(status)


def test_environment_credentials_take_precedence_over_insecure_file(tmp_path):
    secret = tmp_path / "telegram.json"
    secret.write_text(json.dumps({"bot_token": "file-token", "chat_id": "file-chat"}), encoding="utf-8")
    secret.chmod(0o644)
    resolution = resolve_telegram_credentials(secret, environ=_configured_env())
    assert resolution.status == "CONFIGURED"
    assert resolution.credentials is not None
    assert resolution.credentials.source == "environment"
    assert resolution.credentials.bot_token == "test-token"


def test_stdlib_sender_posts_expected_fields_without_logging_token():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok": true}'

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    credentials = TelegramCredentials("secret-token", "12345", "environment")
    send_telegram_message(credentials, "hello", opener=opener)
    assert captured["request"].method == "POST"
    assert captured["request"].data == b"chat_id=12345&text=hello&disable_web_page_preview=true"
    assert captured["timeout"] == 10.0


def test_stdlib_sender_sanitizes_transport_errors():
    credentials = TelegramCredentials("secret-token", "12345", "environment")

    def opener(request, timeout):
        raise OSError(request.full_url)

    try:
        send_telegram_message(credentials, "hello", opener=opener)
    except RuntimeError as exc:
        assert str(exc) == "TELEGRAM_SEND_FAILED:OSError"
        assert "secret-token" not in str(exc)
    else:
        raise AssertionError("expected sanitized Telegram transport error")


def test_formatter_handles_missing_optional_source_fields():
    message = format_meta_notification(
        {
            "_notification_previous_recommendation": "HOLD",
            "_notification_change_type": "CHANGED",
            "recommendation": "AVOID",
            "reason_codes": [],
        }
    )
    assert message.startswith("🎯 ETH ACTION [4H]\nAction: ⛔ AVOID")
    assert "状态: HOLD → AVOID" in message
    assert "• 阻断：UNKNOWN_BLOCK" in message
