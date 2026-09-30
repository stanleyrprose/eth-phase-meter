from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_meta_action_workflow_keeps_tg_fallback_independent_of_database_availability():
    text = (ROOT / ".github" / "workflows" / "meta-action-outcomes.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch" in text
    assert "event_b64" in text
    assert "TG_BOT_TOKEN" in text
    assert "TG_CHAT_ID" in text
    assert "continue-on-error: true" in text
    assert "Apply versioned migrations" in text
    assert "Persist Meta Action and settle outcomes" in text
    assert text.index("Check PostgreSQL availability") < text.index(
        "Persist Meta Action and settle outcomes"
    )


def test_meta_action_migration_is_additive():
    text = (ROOT / "migrations" / "006_meta_action_outcomes.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS eth_meta_action_events" in text
    assert "CREATE TABLE IF NOT EXISTS eth_meta_action_outcomes" in text
    assert "CHECK (horizon_hours IN (4, 12, 24, 72))" in text

def test_meta_action_outcome_revision_migration_is_append_only():
    text = (ROOT / "migrations" / "007_meta_action_outcome_revisions.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS eth_meta_action_outcome_revisions" in text
    assert "PRIMARY KEY(event_id, horizon_hours, revision)" in text
    assert "REFERENCES eth_meta_action_outcomes(event_id, horizon_hours)" in text
    assert "UPDATE eth_meta_action_outcomes" not in text
