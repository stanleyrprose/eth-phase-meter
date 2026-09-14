#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

try:
    from scripts.install_mac_meta_pipeline_launchd import (
        DEFAULT_LABEL as PRODUCTION_LABEL,
        _require_executable,
        _require_tcc_safe_runtime_path,
    )
except ModuleNotFoundError:  # Direct execution sets sys.path[0] to scripts/.
    from install_mac_meta_pipeline_launchd import (  # type: ignore[no-redef]
        DEFAULT_LABEL as PRODUCTION_LABEL,
        _require_executable,
        _require_tcc_safe_runtime_path,
    )


DEFAULT_RUNTIME_ROOT = Path.home() / ".openclaw/workspace/tools/eth-meta-runtime"
DEFAULT_BASE_PYTHON = "/opt/anaconda3/bin/python"
DEFAULT_SMOKE_LABEL = "com.stanley.eth-meta-runtime-smoke"
ETH_REPO_URL = "https://github.com/stanleyrprose/eth-phase-meter.git"
ETH_BRANCH = "main"
TRADINGAGENTS_REPO_URL = "https://github.com/stanleyrprose/TradingAgents.git"
TRADINGAGENTS_BRANCH = "feature/codex-oauth-reasoning-provider"
DEPENDENCY_MARKER = ".eth-meta-deps.sha256"
SMOKE_TIMEOUT_SECONDS = 20.0

RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    run_command: RunCommand = subprocess.run,
    error_code: str = "COMMAND_FAILED",
) -> subprocess.CompletedProcess[str]:
    completed = run_command(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        suffix = f": {detail[-1000:]}" if detail else ""
        raise RuntimeError(f"{error_code}{suffix}")
    return completed


def _git_output(
    repo: Path,
    *args: str,
    run_command: RunCommand = subprocess.run,
) -> str:
    return _run(
        ["git", "-C", str(repo), *args],
        run_command=run_command,
    ).stdout.strip()


def sync_repo(
    *,
    destination: Path,
    url: str,
    branch: str,
    run_command: RunCommand = subprocess.run,
) -> str:
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "git",
                "clone",
                "--branch",
                branch,
                "--single-branch",
                url,
                str(destination),
            ],
            run_command=run_command,
        )
    elif not (destination / ".git").exists():
        raise RuntimeError(f"COMMAND_FAILED: NOT_A_GIT_CLONE: {destination}")
    else:
        origin = _git_output(
            destination,
            "remote",
            "get-url",
            "origin",
            run_command=run_command,
        )
        if origin != url:
            raise RuntimeError(f"REMOTE_MISMATCH: expected={url} actual={origin}")
        current_branch = _git_output(
            destination,
            "branch",
            "--show-current",
            run_command=run_command,
        )
        if current_branch != branch:
            raise RuntimeError(
                f"BRANCH_MISMATCH: expected={branch} actual={current_branch or 'DETACHED'}"
            )
        tracked_status = _git_output(
            destination,
            "status",
            "--porcelain",
            "--untracked-files=no",
            run_command=run_command,
        )
        if tracked_status:
            raise RuntimeError(f"DIRTY_TRACKED: {destination}")
        _run(
            ["git", "-C", str(destination), "fetch", "origin", branch],
            run_command=run_command,
        )
        _run(
            [
                "git",
                "-C",
                str(destination),
                "merge",
                "--ff-only",
                f"origin/{branch}",
            ],
            run_command=run_command,
        )
    return _git_output(destination, "rev-parse", "HEAD", run_command=run_command)


def ensure_tradingagents_env(repo: Path, source: Path | None = None) -> Path:
    destination = repo / ".env"
    if not destination.exists():
        if source is None or not source.expanduser().is_file():
            raise RuntimeError("TRADINGAGENTS_ENV_MISSING")
        shutil.copy2(source.expanduser(), destination)
    destination.chmod(0o600)
    return destination


def dependency_fingerprint(repo: Path) -> str:
    manifests = [repo / "pyproject.toml"]
    if (repo / "requirements.txt").is_file():
        manifests.append(repo / "requirements.txt")
    if not manifests[0].is_file():
        raise RuntimeError("COMMAND_FAILED: DEPENDENCY_MANIFEST_MISSING")
    digest = hashlib.sha256()
    for manifest in manifests:
        digest.update(manifest.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(manifest.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def sync_dependencies(
    repo: Path,
    *,
    base_python: str,
    refresh: bool = False,
    run_command: RunCommand = subprocess.run,
) -> str:
    venv = repo / ".venv"
    marker = venv / DEPENDENCY_MARKER
    fingerprint = dependency_fingerprint(repo)
    venv_python = venv / "bin" / "python"
    pip = venv / "bin" / "pip"
    venv_repaired = not (venv_python.is_file() and pip.is_file())
    if venv_repaired:
        _run([base_python, "-m", "venv", str(venv)], run_command=run_command)
    previous = marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    if not (venv_repaired or refresh or previous != fingerprint):
        return "SKIPPED"
    _run([str(pip), "install", "-e", "."], cwd=repo, run_command=run_command)
    marker.write_text(f"{fingerprint}\n", encoding="utf-8")
    return "SYNCED"


def verify_pre_install(
    *,
    eth_repo: Path,
    tradingagents_repo: Path,
    gh: str,
    codex: str,
    run_command: RunCommand = subprocess.run,
) -> None:
    ta_python = tradingagents_repo / ".venv" / "bin" / "python"
    ta_runner = tradingagents_repo / "scripts" / "run_tradingagents.py"
    help_result = _run(
        [str(ta_python), str(ta_runner), "--help"],
        cwd=tradingagents_repo,
        run_command=run_command,
    )
    if "--decision-json" not in f"{help_result.stdout}\n{help_result.stderr}":
        raise RuntimeError("TRADINGAGENTS_DECISION_JSON_UNSUPPORTED")

    detect_result = _run(
        [str(ta_python), str(ta_runner), "ETH-USD", "--detect-only"],
        cwd=tradingagents_repo,
        run_command=run_command,
    )
    if "can_run: True" not in f"{detect_result.stdout}\n{detect_result.stderr}":
        raise RuntimeError("TRADINGAGENTS_DETECT_FAILED")

    _run([codex, "login", "status"], run_command=run_command)
    gh_result = _run(
        [
            gh,
            "run",
            "list",
            "--repo",
            "stanleyrprose/eth-phase-meter",
            "--workflow",
            "scheduled-monitor.yml",
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId",
        ],
        cwd=eth_repo,
        run_command=run_command,
    )
    try:
        successful_runs = json.loads(gh_result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("GH_SUCCESSFUL_RUN_INVALID_JSON") from exc
    if not successful_runs:
        raise RuntimeError("GH_SUCCESSFUL_RUN_MISSING")


def install_launchagent(
    *,
    eth_repo: Path,
    tradingagents_repo: Path,
    base_python: str,
    gh: str,
    codex: str,
    run_command: RunCommand = subprocess.run,
) -> None:
    installer = eth_repo / "scripts" / "install_mac_meta_pipeline_launchd.py"
    _run(
        [
            base_python,
            str(installer),
            "--tradingagents-repo",
            str(tradingagents_repo),
            "--python",
            base_python,
            "--gh",
            gh,
            "--codex",
            codex,
        ],
        cwd=eth_repo,
        run_command=run_command,
    )


def build_smoke_plist(
    *,
    eth_repo: Path,
    base_python: str,
    exit_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    label: str = DEFAULT_SMOKE_LABEL,
) -> dict:
    runner = eth_repo / "scripts" / "run_local_meta_pipeline.py"
    shell = '"$@"; status=$?; printf "%s\\n" "$status" > "$ETH_META_SMOKE_EXIT"; exit "$status"'
    return {
        "Label": label,
        "ProgramArguments": [
            "/bin/sh",
            "-c",
            shell,
            label,
            base_python,
            str(runner),
            "--help",
        ],
        "WorkingDirectory": str(eth_repo),
        "RunAtLoad": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "PATH": ":".join(
                dict.fromkeys(
                    [
                        str(Path(base_python).parent),
                        "/opt/homebrew/bin",
                        "/usr/local/bin",
                        "/usr/bin",
                        "/bin",
                    ]
                )
            ),
            "PYTHONUNBUFFERED": "1",
            "ETH_META_SMOKE_EXIT": str(exit_path),
        },
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
    }


def run_launchd_smoke(
    *,
    eth_repo: Path,
    base_python: str,
    timeout: float = SMOKE_TIMEOUT_SECONDS,
    label: str = DEFAULT_SMOKE_LABEL,
    home: Path | None = None,
    run_command: RunCommand = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    user_home = (home or Path.home()).expanduser()
    state_dir = user_home / ".eth-meta-pipeline"
    launchagents_dir = user_home / "Library" / "LaunchAgents"
    state_dir.mkdir(parents=True, exist_ok=True)
    launchagents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launchagents_dir / f"{label}.plist"
    exit_path = state_dir / "runtime-smoke.exit"
    stdout_path = state_dir / "runtime-smoke.stdout.log"
    stderr_path = state_dir / "runtime-smoke.stderr.log"
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    for path in (plist_path, exit_path, stdout_path, stderr_path):
        if path.exists():
            path.unlink()
    run_command(
        ["launchctl", "bootout", service],
        text=True,
        capture_output=True,
        check=False,
    )
    plist = build_smoke_plist(
        eth_repo=eth_repo,
        base_python=base_python,
        exit_path=exit_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        label=label,
    )
    plist_path.write_bytes(plistlib.dumps(plist, sort_keys=False))
    try:
        _run(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            run_command=run_command,
            error_code="SMOKE_LAUNCHCTL_FAILED",
        )
        deadline = monotonic() + timeout
        while not exit_path.exists() and monotonic() < deadline:
            sleep(0.1)
        if not exit_path.exists():
            raise RuntimeError("SMOKE_TIMEOUT")
        try:
            exit_code = int(exit_path.read_text(encoding="utf-8").strip())
        except ValueError as exc:
            raise RuntimeError("SMOKE_EXIT_INVALID") from exc
        output = "\n".join(
            path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            for path in (stdout_path, stderr_path)
        )
        if exit_code != 0:
            raise RuntimeError(f"SMOKE_FAILED: exit={exit_code}")
        if "usage" not in output.lower() and "help" not in output.lower():
            raise RuntimeError("SMOKE_HELP_OUTPUT_MISSING")
    finally:
        run_command(
            ["launchctl", "bootout", service],
            text=True,
            capture_output=True,
            check=False,
        )
        if plist_path.exists():
            plist_path.unlink()


def maybe_kickstart_production(
    enabled: bool,
    *,
    run_command: RunCommand = subprocess.run,
) -> None:
    if not enabled:
        return
    _run(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{PRODUCTION_LABEL}"],
        run_command=run_command,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap or fast-forward the TCC-safe local ETH Meta runtime."
    )
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--python", default=DEFAULT_BASE_PYTHON, help="base Python executable")
    parser.add_argument("--gh", help="GitHub CLI executable")
    parser.add_argument("--codex", help="Codex CLI executable")
    parser.add_argument("--tradingagents-env-source")
    parser.add_argument("--refresh-deps", action="store_true")
    parser.add_argument("--kickstart-production", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    runtime_root = _require_tcc_safe_runtime_path(
        Path(args.runtime_root), role="runtime_root"
    )
    eth_repo = _require_tcc_safe_runtime_path(
        runtime_root / "eth-phase-meter", role="eth_repo"
    )
    tradingagents_repo = _require_tcc_safe_runtime_path(
        runtime_root / "TradingAgents", role="tradingagents_repo"
    )
    base_python = _require_executable(args.python, "python")
    gh = _require_executable(args.gh, "gh")
    codex = _require_executable(args.codex, "codex")

    eth_sha = sync_repo(
        destination=eth_repo,
        url=ETH_REPO_URL,
        branch=ETH_BRANCH,
    )
    ta_sha = sync_repo(
        destination=tradingagents_repo,
        url=TRADINGAGENTS_REPO_URL,
        branch=TRADINGAGENTS_BRANCH,
    )
    env_source = Path(args.tradingagents_env_source) if args.tradingagents_env_source else None
    ensure_tradingagents_env(tradingagents_repo, env_source)
    dependency_action = sync_dependencies(
        tradingagents_repo,
        base_python=base_python,
        refresh=args.refresh_deps,
    )
    verify_pre_install(
        eth_repo=eth_repo,
        tradingagents_repo=tradingagents_repo,
        gh=gh,
        codex=codex,
    )
    install_launchagent(
        eth_repo=eth_repo,
        tradingagents_repo=tradingagents_repo,
        base_python=base_python,
        gh=gh,
        codex=codex,
    )
    run_launchd_smoke(eth_repo=eth_repo, base_python=base_python)
    maybe_kickstart_production(args.kickstart_production)
    print(
        "DEPLOYMENT "
        f"eth={eth_sha} ta={ta_sha} deps={dependency_action} "
        "launchd=INSTALLED smoke=PASS "
        f"production_kickstart={'YES' if args.kickstart_production else 'NO'}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Meta runtime deploy ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
