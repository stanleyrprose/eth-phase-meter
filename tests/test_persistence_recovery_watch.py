from datetime import datetime, timezone
import json

from scripts.database_preflight import DatabaseHealth
from scripts.persistence_recovery_watch import _read_previous, evaluate_recovery


NOW = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)


def health(available: bool, reason: str) -> DatabaseHealth:
    return DatabaseHealth(
        configured=True,
        available=available,
        reason=reason,
        error_type=None if available else "OperationalError",
    )


def test_first_run_establishes_baseline_without_recovery_alert():
    decision = evaluate_recovery(
        current=health(False, "QUOTA_EXCEEDED"),
        previous_available=None,
        now=NOW,
    )
    assert decision.transition == "BASELINE"
    assert decision.recovered is False


def test_unavailable_to_unavailable_is_unchanged():
    decision = evaluate_recovery(
        current=health(False, "QUOTA_EXCEEDED"),
        previous_available=False,
        previous_reason="QUOTA_EXCEEDED",
        now=NOW,
    )
    assert decision.transition == "UNCHANGED"
    assert decision.recovered is False


def test_unavailable_to_available_is_recovered_once():
    decision = evaluate_recovery(
        current=health(True, "OK"),
        previous_available=False,
        previous_reason="QUOTA_EXCEEDED",
        now=NOW,
    )
    assert decision.transition == "RECOVERED"
    assert decision.recovered is True
    assert decision.previous_reason == "QUOTA_EXCEEDED"


def test_available_to_available_does_not_repeat_recovery():
    decision = evaluate_recovery(
        current=health(True, "OK"),
        previous_available=True,
        previous_reason="OK",
        now=NOW,
    )
    assert decision.transition == "UNCHANGED"
    assert decision.recovered is False


def test_available_to_unavailable_records_degraded_without_recovery_alert():
    decision = evaluate_recovery(
        current=health(False, "CONNECTION_TIMEOUT"),
        previous_available=True,
        previous_reason="OK",
        now=NOW,
    )
    assert decision.transition == "DEGRADED"
    assert decision.recovered is False


def test_previous_state_reader_uses_artifact_health(tmp_path):
    path = tmp_path / "postgres-recovery-state.json"
    path.write_text(
        json.dumps({
            "health": {
                "configured": True,
                "available": False,
                "reason": "QUOTA_EXCEEDED",
            }
        }),
        encoding="utf-8",
    )
    available, reason = _read_previous(path)
    assert available is False
    assert reason == "QUOTA_EXCEEDED"
