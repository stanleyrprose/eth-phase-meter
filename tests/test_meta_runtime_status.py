import json

from scripts.meta_runtime_status import build_status


def test_status_surface_exposes_only_operational_fields(tmp_path):
    state = {
        "last_processed_run_id": 123,
        "last_pipeline_status": "OK",
        "last_meta_research_dispatch_run_id": 123,
        "last_meta_research_dispatch": {"status": "DISPATCHED"},
        "last_notification": {
            "status": "SKIPPED_UNCONFIGURED",
            "policy_action": "SEND_UNCHANGED",
            "change_type": "UNCHANGED",
        },
        "updated_at": "2026-09-27T04:40:00+00:00",
    }
    meta = {
        "recommendation": "HOLD",
        "evidence_alignment": "MEDIUM",
        "generated_at": "2026-09-27T04:39:00+00:00",
        "sources": {"tradingagents": {"decision": "HOLD"}},
    }
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "meta_decision.json").write_text(json.dumps(meta), encoding="utf-8")

    status = build_status(tmp_path)

    assert status["last_processed_run_id"] == 123
    assert status["recommendation"] == "HOLD"
    assert status["notification_status"] == "SKIPPED_UNCONFIGURED"
    assert status["meta_research_dispatch_status"] == "DISPATCHED"
    assert status["meta_research_dispatch_run_id"] == 123
    assert "bot_token" not in status
    assert "chat_id" not in status
