import json

from eth_trend_v3.shadow_runtime import run_shadow_cycle


def test_shadow_cycle_fails_closed_without_durable_postgres(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    report = run_shadow_cycle(output_dir=str(tmp_path))

    assert report["status"] == "SKIPPED_PERSISTENCE_UNAVAILABLE"
    assert report["reason"] == "DURABLE_POSTGRES_REQUIRED"
    assert report["persistence_mode"] == "ARTIFACT_ONLY"
    assert report["created"] == []
    assert report["settled_now"] == 0
    assert all(
        item["status"] == "SKIPPED_PERSISTENCE_UNAVAILABLE"
        for item in report["horizons"].values()
    )

    saved = json.loads((tmp_path / "shadow_cycle_report.json").read_text(encoding="utf-8"))
    assert saved["status"] == "SKIPPED_PERSISTENCE_UNAVAILABLE"
    assert saved["created"] == []
