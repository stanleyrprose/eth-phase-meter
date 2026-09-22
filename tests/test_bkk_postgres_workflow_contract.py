from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DB_WORKFLOWS = [
    "backtest.yml",
    "contract-smoke.yml",
    "emergency-control.yml",
    "hmm-bootstrap.yml",
    "model-validation.yml",
    "pit-backup.yml",
    "postgres-recovery-watch.yml",
    "prd-v23-acceptance.yml",
    "research-readiness.yml",
    "scheduled-monitor.yml",
    "shadow-forecast.yml",
    "tactical-1h.yml",
]


def test_all_durable_db_workflows_use_bkk_tunnel_and_not_neon_secret():
    for name in DB_WORKFLOWS:
        path = ROOT / ".github" / "workflows" / name
        text = path.read_text(encoding="utf-8")
        yaml.safe_load(text)
        assert "secrets.DATABASE_URL" not in text, name
        assert "./.github/actions/setup-bkk-postgres" in text, name
        assert "secrets.BINANCE_EGRESS_SSH_KEY" in text, name


def test_bkk_tunnel_contract_is_localhost_only_and_passwordless_over_ssh():
    text = (ROOT / ".github" / "actions" / "setup-bkk-postgres" / "action.yml").read_text(encoding="utf-8")
    yaml.safe_load(text)
    assert "-L 127.0.0.1:15432:127.0.0.1:5432" in text
    assert "postgresql://eth_phase_meter@127.0.0.1:15432/eth_phase_meter?sslmode=disable" in text
    assert "root@43.133.101.242" in text


def test_bkk_server_provisioning_never_exposes_postgres_publicly():
    text = (ROOT / "scripts" / "provision_bkk_postgres.sh").read_text(encoding="utf-8")
    assert "PG_MAJOR" in text
    assert "18" in text
    assert "listen_addresses = '127.0.0.1'" in text
    assert "127.0.0.1/32 trust" in text
    assert "0.0.0.0" not in text


def test_pit_backup_docker_can_reach_runner_local_tunnel():
    text = (ROOT / ".github" / "workflows" / "pit-backup.yml").read_text(encoding="utf-8")
    assert text.count("--network host") >= 2


def test_migration_workflow_uses_known_good_backup_and_pg18_restore():
    text = (ROOT / ".github" / "workflows" / "migrate-bkk-postgres.yml").read_text(encoding="utf-8")
    yaml.safe_load(text)
    assert "35581618650" in text
    assert "postgres:18" in text
    assert "--network host" in text
    assert 'required: "true"' in text
    assert "required_tables_missing" in text
