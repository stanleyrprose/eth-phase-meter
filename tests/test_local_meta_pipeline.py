import datetime as dt
import json
import os
import subprocess
import sys
import time

import pytest

from scripts import run_local_meta_pipeline as pipeline


def _monitor():
    now = dt.datetime.now(dt.timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    base = {
        "timestamp": timestamp,
        "coverage": 98,
        "data_health": {"status": "NORMAL"},
        "model_health": {"status": "NORMAL"},
        "regime": {"regime": "Transition"},
        "volatility_risk": 25,
        "feature_clusters": {
            "momentum": {"score": 55},
            "order_flow": {"score": 59},
            "options_positioning": {"score": -21},
        },
    }
    return {
        "1h": {**base, "rule_direction": 1},
        "4h": {**base, "rule_direction": 22},
    }


def _decision():
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "contract_version": "tradingagents-decision-v1",
        "generated_at": now.isoformat(),
        "analysis_date": now.date().isoformat(),
        "canonical_symbol": "ETH-USD",
        "decision": "Hold",
        "decision_normalized": "HOLD",
        "report_path": "/tmp/report.md",
    }


def _run_pipeline(*args):
    env = os.environ.copy()
    env.pop("TG_BOT_TOKEN", None)
    env.pop("TG_CHAT_ID", None)
    return subprocess.run(
        [sys.executable, "scripts/run_local_meta_pipeline.py", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_local_pipeline_reuses_fresh_decision_when_phase_is_stable(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")
    state_dir.mkdir()
    (state_dir / "latest_monitor.json").write_text(json.dumps(_monitor()), encoding="utf-8")
    (state_dir / "tradingagents_decision.json").write_text(json.dumps(_decision()), encoding="utf-8")

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
    )
    assert completed.returncode == 0, completed.stderr
    trigger = json.loads((state_dir / "tradingagents_trigger.json").read_text(encoding="utf-8"))
    meta = json.loads((state_dir / "meta_decision.json").read_text(encoding="utf-8"))
    assert trigger["action"] == "REUSE"
    assert meta["recommendation"] == "HOLD"
    assert meta["pipeline"]["ta_trigger_action"] == "REUSE"
    assert meta["pipeline"]["notification"]["status"] == "BASELINE_INITIALIZED"
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["last_notified_recommendation"] == "HOLD"
    assert state["last_notification"]["attempted"] is False
    progress = [
        json.loads(line)
        for line in (state_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    stages = [entry["stage"] for entry in progress]
    assert stages == [
        "pipeline_started",
        "components_loaded",
        "monitor_load_started",
        "monitor_loaded",
        "trigger_evaluated",
        "meta_decision_completed",
        "notification_completed",
        "state_written",
        "pipeline_completed",
    ]
    assert progress[-1]["status"] == "OK"


def test_local_pipeline_defers_when_phase_is_untrustworthy(tmp_path):
    monitor = _monitor()
    monitor["4h"]["coverage"] = 40
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(monitor), encoding="utf-8")

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
    )
    assert completed.returncode == 0, completed.stderr
    trigger = json.loads((state_dir / "tradingagents_trigger.json").read_text(encoding="utf-8"))
    assert trigger["action"] == "DEFER"
    assert not (state_dir / "meta_decision.json").exists()
    progress = [
        json.loads(line)
        for line in (state_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["stage"] for entry in progress][-2:] == ["state_written", "pipeline_completed"]
    assert progress[-2]["status"] == "DEFER"


def test_progress_stdout_prints_only_stage_and_flushes(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: calls.append((args, kwargs)))

    pipeline.ProgressLogger(tmp_path / "progress.jsonl").emit(
        "safe_stage",
        arbitrary_detail="secret-value-must-not-reach-stdout",
    )

    assert calls == [(('Meta Pipeline progress: safe_stage',), {"flush": True})]


def test_no_new_monitor_run_progress_path_without_github_calls(monkeypatch, tmp_path, capfd):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps({"last_processed_run_id": 123}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pipeline,
        "_latest_monitor_run",
        lambda _gh, _repo, _workflow: {
            "databaseId": 123,
            "headSha": "test-sha",
            "createdAt": "2026-01-02T00:00:00Z",
        },
    )

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("artifact download must not run when the monitor run is already processed")

    monkeypatch.setattr(pipeline, "_download_monitor", unexpected_download)

    result = pipeline.main(
        [
            "--state-dir",
            str(state_dir),
            "--gh",
            "fake-gh",
            "--watchdog-seconds",
            "0",
        ]
    )

    assert result == 0
    assert "NO_NEW_MONITOR_RUN run_id=123" in capfd.readouterr().out
    progress = [
        json.loads(line)
        for line in (state_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["stage"] for entry in progress] == [
        "pipeline_started",
        "components_loaded",
        "gh_run_list_started",
        "gh_run_list_completed",
        "pipeline_completed",
    ]
    assert progress[-1]["status"] == "NO_NEW_MONITOR_RUN"


def test_github_artifact_download_completion_precedes_monitor_load(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "latest_monitor.json").write_text(json.dumps(_monitor()), encoding="utf-8")
    (state_dir / "tradingagents_decision.json").write_text(
        json.dumps(_decision()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pipeline,
        "_latest_monitor_run",
        lambda _gh, _repo, _workflow: {
            "databaseId": 456,
            "headSha": "test-sha",
            "createdAt": "2026-01-02T00:00:00Z",
        },
    )

    def fake_download(_gh, _repo, _run_id, destination):
        monitor_path = destination / "eth-monitor-test" / "latest_monitor.json"
        monitor_path.parent.mkdir()
        monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")
        return monitor_path

    monkeypatch.setattr(pipeline, "_download_monitor", fake_download)

    assert pipeline.main(
        [
            "--state-dir",
            str(state_dir),
            "--gh",
            "fake-gh",
            "--watchdog-seconds",
            "0",
        ]
    ) == 0

    progress = [
        json.loads(line)
        for line in (state_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    stages = [entry["stage"] for entry in progress]
    assert stages.index("gh_run_download_started") < stages.index("gh_run_download_completed")
    assert stages.index("gh_run_download_completed") < stages.index("monitor_loaded")


def test_delayed_traceback_default_is_one_minute():
    assert pipeline.TRACEBACK_DELAY_SECONDS == 60


@pytest.mark.parametrize("error", [OSError("stderr unavailable"), ValueError("unsupported file")])
def test_delayed_traceback_diagnostics_fails_open_when_arming_fails(monkeypatch, error):
    cancelled = False

    def fail_to_arm(_delay_seconds, *, repeat):
        assert repeat is True
        raise error

    def cancel():
        nonlocal cancelled
        cancelled = True

    monkeypatch.setattr(pipeline.faulthandler, "dump_traceback_later", fail_to_arm)
    monkeypatch.setattr(pipeline.faulthandler, "cancel_dump_traceback_later", cancel)

    body_ran = False
    with pipeline._delayed_traceback_diagnostics(1):
        body_ran = True

    assert body_ran is True
    assert cancelled is False


def test_local_pipeline_unconfigured_change_syncs_notification_baseline(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")
    state_dir.mkdir()
    (state_dir / "latest_monitor.json").write_text(json.dumps(_monitor()), encoding="utf-8")
    (state_dir / "tradingagents_decision.json").write_text(json.dumps(_decision()), encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"last_notified_recommendation": "ADD"}),
        encoding="utf-8",
    )

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
        "--telegram-secret-file",
        str(tmp_path / "missing-telegram.json"),
    )
    assert completed.returncode == 0, completed.stderr
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["last_notification"]["status"] == "SKIPPED_UNCONFIGURED"
    assert state["last_notified_recommendation"] == "HOLD"


def test_local_pipeline_migrates_same_meta_baseline_without_notification(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")
    state_dir.mkdir()
    (state_dir / "latest_monitor.json").write_text(json.dumps(_monitor()), encoding="utf-8")
    (state_dir / "tradingagents_decision.json").write_text(json.dumps(_decision()), encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"last_meta_recommendation": "HOLD"}),
        encoding="utf-8",
    )

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
        "--telegram-secret-file",
        str(tmp_path / "missing-telegram.json"),
    )
    assert completed.returncode == 0, completed.stderr
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["last_notification"]["status"] == "NO_CHANGE"
    assert state["last_notification"]["previous_recommendation"] == "HOLD"
    assert state["last_notified_recommendation"] == "HOLD"


def test_local_pipeline_migrates_changed_meta_baseline_through_policy(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")
    state_dir.mkdir()
    (state_dir / "latest_monitor.json").write_text(json.dumps(_monitor()), encoding="utf-8")
    (state_dir / "tradingagents_decision.json").write_text(json.dumps(_decision()), encoding="utf-8")
    (state_dir / "state.json").write_text(
        json.dumps({"last_meta_recommendation": "REDUCE"}),
        encoding="utf-8",
    )

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
        "--telegram-secret-file",
        str(tmp_path / "missing-telegram.json"),
    )
    assert completed.returncode == 0, completed.stderr
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["last_notification"]["status"] == "SKIPPED_UNCONFIGURED"
    assert state["last_notification"]["previous_recommendation"] == "REDUCE"
    assert state["last_notified_recommendation"] == "HOLD"


def test_local_pipeline_runs_tradingagents_when_contract_is_missing(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    ta_repo = tmp_path / "TradingAgents"
    scripts = ta_repo / "scripts"
    scripts.mkdir(parents=True)
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")

    fake_runner = scripts / "run_tradingagents.py"
    fake_runner.write_text(
        """
import argparse
import datetime as dt
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("symbol")
parser.add_argument("--date", required=True)
parser.add_argument("--decision-json", required=True)
args = parser.parse_args()
now = dt.datetime.now(dt.timezone.utc)
payload = {
    "contract_version": "tradingagents-decision-v1",
    "generated_at": now.isoformat(),
    "analysis_date": args.date,
    "canonical_symbol": "ETH-USD",
    "decision": "Hold",
    "decision_normalized": "HOLD",
    "report_path": "/tmp/fake-report.md",
}
Path(args.decision_json).parent.mkdir(parents=True, exist_ok=True)
Path(args.decision_json).write_text(json.dumps(payload), encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
        "--tradingagents-repo",
        str(ta_repo),
        "--tradingagents-python",
        sys.executable,
    )
    assert completed.returncode == 0, completed.stderr
    trigger = json.loads((state_dir / "tradingagents_trigger.json").read_text(encoding="utf-8"))
    decision = json.loads((state_dir / "tradingagents_decision.json").read_text(encoding="utf-8"))
    meta = json.loads((state_dir / "meta_decision.json").read_text(encoding="utf-8"))
    assert trigger["action"] == "RUN"
    assert "TA_MISSING_INVALID_OR_STALE" in trigger["reason_codes"]
    assert decision["contract_version"] == "tradingagents-decision-v1"
    assert meta["recommendation"] == "HOLD"
    assert meta["pipeline"]["ta_trigger_action"] == "RUN"


def test_subprocess_timeout_stops_the_process_group(tmp_path):
    marker = tmp_path / "child-stopped"
    parent_code = r"""
import pathlib
import subprocess
import sys
import time

marker = sys.argv[1]
child_code = r'''\
import pathlib
import signal
import sys
import time

marker = pathlib.Path(sys.argv[1])
def stop(_signum, _frame):
    marker.write_text("stopped", encoding="utf-8")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
pathlib.Path(str(marker) + ".ready").write_text("ready", encoding="utf-8")
time.sleep(60)
'''
subprocess.Popen([sys.executable, "-c", child_code, marker])
ready = pathlib.Path(marker + ".ready")
while not ready.exists():
    time.sleep(0.005)
time.sleep(60)
"""

    with pytest.raises(RuntimeError, match="^TEST_SUBPROCESS_TIMEOUT$"):
        pipeline._run(
            [sys.executable, "-c", parent_code, str(marker)],
            timeout=0.5,
            timeout_code="TEST_SUBPROCESS_TIMEOUT",
        )

    assert marker.read_text(encoding="utf-8") == "stopped"


def test_subprocess_callers_have_explicit_timeout_codes(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        raise RuntimeError(kwargs["timeout_code"])

    monkeypatch.setattr(pipeline, "_run", fake_run)

    with pytest.raises(RuntimeError, match="^GH_RUN_LIST_TIMEOUT$"):
        pipeline._latest_monitor_run("gh", "owner/repo", "workflow.yml")
    with pytest.raises(RuntimeError, match="^GH_RUN_DOWNLOAD_TIMEOUT$"):
        pipeline._download_monitor("gh", "owner/repo", 123, tmp_path)

    ta_repo = tmp_path / "TradingAgents"
    (ta_repo / "scripts").mkdir(parents=True)
    (ta_repo / "scripts" / "run_tradingagents.py").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="^TRADINGAGENTS_TIMEOUT$"):
        pipeline._run_tradingagents(ta_repo, sys.executable, "2026-01-02", tmp_path / "decision.json")

    assert [(kwargs["timeout"], kwargs["timeout_code"]) for _, kwargs in calls] == [
        (30, "GH_RUN_LIST_TIMEOUT"),
        (120, "GH_RUN_DOWNLOAD_TIMEOUT"),
        (3600, "TRADINGAGENTS_TIMEOUT"),
    ]


@pytest.mark.skipif(os.name != "posix", reason="the whole-pipeline watchdog is POSIX-only")
def test_pipeline_watchdog_fires_and_cancels_cleanly():
    started = time.monotonic()
    with pytest.raises(pipeline.PipelineWatchdogTimeout, match="^PIPELINE_WATCHDOG_TIMEOUT$"):
        with pipeline._pipeline_watchdog(0.05):
            time.sleep(1)
    assert time.monotonic() - started < 0.5

    with pipeline._pipeline_watchdog(0.05):
        pass
    time.sleep(0.08)

    with pipeline._pipeline_watchdog(0):
        pass
