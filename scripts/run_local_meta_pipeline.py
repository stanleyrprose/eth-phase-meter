#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_components():
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from eth_trend_v3.meta_decision import evaluate_meta_decision
    from eth_trend_v3.meta_notification import process_meta_notification
    from eth_trend_v3.ta_trigger import evaluate_tradingagents_trigger

    return evaluate_meta_decision, evaluate_tradingagents_trigger, process_meta_notification


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _latest_monitor_run(gh: str, repo: str, workflow: str) -> dict:
    completed = _run(
        [
            gh,
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            workflow,
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId,headSha,createdAt",
        ]
    )
    if completed.returncode != 0:
        raise RuntimeError(f"GH_RUN_LIST_FAILED: {completed.stderr.strip()}")
    rows = json.loads(completed.stdout or "[]")
    if not rows:
        raise RuntimeError("NO_SUCCESSFUL_MONITOR_RUN")
    return rows[0]


def _download_monitor(gh: str, repo: str, run_id: int, destination: Path) -> Path:
    completed = _run(
        [
            gh,
            "run",
            "download",
            str(run_id),
            "--repo",
            repo,
            "--pattern",
            "eth-monitor-*",
            "--dir",
            str(destination),
        ]
    )
    if completed.returncode != 0:
        raise RuntimeError(f"GH_RUN_DOWNLOAD_FAILED: {completed.stderr.strip()}")
    matches = list(destination.rglob("latest_monitor.json"))
    if len(matches) != 1:
        raise RuntimeError(f"MONITOR_ARTIFACT_AMBIGUOUS: count={len(matches)}")
    return matches[0]


def _monitor_date(monitor: dict) -> str:
    value = str(((monitor.get("4h") or {}).get("timestamp")) or "")
    if value.endswith(" UTC"):
        try:
            return dt.datetime.strptime(value, "%Y-%m-%d %H:%M UTC").date().isoformat()
        except ValueError:
            pass
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def _tradingagents_python(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    venv_python = repo / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _run_tradingagents(repo: Path, python: str, analysis_date: str, decision_path: Path) -> None:
    runner = repo / "scripts" / "run_tradingagents.py"
    if not runner.exists():
        raise RuntimeError(f"TRADINGAGENTS_RUNNER_MISSING: {runner}")
    completed = _run(
        [
            python,
            str(runner),
            "ETH-USD",
            "--date",
            analysis_date,
            "--decision-json",
            str(decision_path),
        ],
        cwd=repo,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise RuntimeError(f"TRADINGAGENTS_RUN_FAILED: {tail.strip()}")
    if not decision_path.exists():
        raise RuntimeError("TRADINGAGENTS_DECISION_NOT_WRITTEN")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Event-triggered local bridge from the latest GitHub ETH monitor artifact to TradingAgents."
    )
    parser.add_argument("--repo", default="stanleyrprose/eth-phase-meter")
    parser.add_argument("--workflow", default="scheduled-monitor.yml")
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / ".eth-meta-pipeline"),
        help="durable local state; contains the latest source contracts and meta decision",
    )
    parser.add_argument(
        "--tradingagents-repo",
        default=str(Path.home() / "Documents/mcpx-projects/TradingAgents-codex-oauth"),
    )
    parser.add_argument("--tradingagents-python")
    parser.add_argument("--gh", help="path to GitHub CLI; auto-detected when omitted")
    parser.add_argument(
        "--monitor-file",
        help="use a local latest_monitor.json instead of downloading the latest successful GitHub artifact",
    )
    parser.add_argument("--force-ta", action="store_true", help="force a TradingAgents refresh after phase gates pass")
    parser.add_argument(
        "--telegram-secret-file",
        default=str(Path.home() / ".eth-meta-pipeline" / "telegram.json"),
        help="local Telegram credential JSON; TG_BOT_TOKEN/TG_CHAT_ID take precedence",
    )
    args = parser.parse_args()

    evaluate_meta_decision, evaluate_trigger, process_notification = _load_components()
    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "state.json"
    previous_monitor_path = state_dir / "latest_monitor.json"
    decision_path = state_dir / "tradingagents_decision.json"
    trigger_path = state_dir / "tradingagents_trigger.json"
    meta_path = state_dir / "meta_decision.json"
    state = _read_json(state_path)

    run_id: int | str
    run_sha: str | None = None
    if args.monitor_file:
        monitor_path = Path(args.monitor_file).expanduser().resolve()
        monitor = _read_json(monitor_path)
        run_id = f"local:{(monitor.get('4h') or {}).get('timestamp') or monitor_path.stat().st_mtime_ns}"
    else:
        gh = args.gh or shutil.which("gh")
        if not gh:
            raise RuntimeError("GH_CLI_NOT_FOUND")
        latest = _latest_monitor_run(gh, args.repo, args.workflow)
        run_id = int(latest["databaseId"])
        run_sha = latest.get("headSha")
        if state.get("last_processed_run_id") == run_id:
            print(f"NO_NEW_MONITOR_RUN run_id={run_id}")
            return 0
        with tempfile.TemporaryDirectory(prefix="eth-meta-") as tmp:
            monitor_path = _download_monitor(gh, args.repo, run_id, Path(tmp))
            monitor = _read_json(monitor_path)

    previous_monitor = _read_json(previous_monitor_path)
    existing_decision = _read_json(decision_path)
    trigger = evaluate_trigger(
        monitor,
        previous_monitor=previous_monitor or None,
        tradingagents=existing_decision or None,
    )
    if args.force_ta and trigger["action"] != "DEFER":
        trigger["action"] = "RUN"
        trigger["reason_codes"] = ["FORCED_REFRESH"] + trigger["reason_codes"]
    trigger["monitor_run_id"] = run_id
    trigger["monitor_git_sha"] = run_sha
    _write_json(trigger_path, trigger)

    if trigger["action"] == "DEFER":
        _write_json(previous_monitor_path, monitor)
        state.update(
            {
                "last_processed_run_id": run_id,
                "last_monitor_git_sha": run_sha,
                "last_pipeline_status": "DEFER",
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        )
        _write_json(state_path, state)
        print(f"Meta Pipeline: DEFER | reasons={','.join(trigger['reason_codes'])}")
        return 0

    if trigger["action"] == "RUN":
        ta_repo = Path(args.tradingagents_repo).expanduser().resolve()
        ta_python = _tradingagents_python(ta_repo, args.tradingagents_python)
        _run_tradingagents(ta_repo, ta_python, _monitor_date(monitor), decision_path)

    decision = _read_json(decision_path)
    meta = evaluate_meta_decision(monitor, decision)
    meta["pipeline"] = {
        "monitor_run_id": run_id,
        "monitor_git_sha": run_sha,
        "ta_trigger_action": trigger["action"],
        "ta_trigger_reasons": trigger["reason_codes"],
    }
    notification, last_notified = process_notification(
        meta,
        state,
        secret_file=Path(args.telegram_secret_file).expanduser().resolve(),
    )
    meta["pipeline"]["notification"] = notification
    _write_json(meta_path, meta)
    _write_json(previous_monitor_path, monitor)
    state.update(
        {
            "last_processed_run_id": run_id,
            "last_monitor_git_sha": run_sha,
            "last_pipeline_status": "OK",
            "last_meta_recommendation": meta["recommendation"],
            "last_notified_recommendation": last_notified,
            "last_notification": notification,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )
    _write_json(state_path, state)

    print(
        f"Meta Pipeline: {meta['recommendation']} | alignment={meta['evidence_alignment']} | "
        f"ta={trigger['action']} | reasons={','.join(meta['reason_codes'])}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Meta Pipeline ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
