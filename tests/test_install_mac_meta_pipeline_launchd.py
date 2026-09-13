import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.install_mac_meta_pipeline_launchd import (
    DEFAULT_TRADINGAGENTS_REPO,
    _require_tcc_safe_runtime_path,
)


def test_default_tradingagents_repo_is_outside_tcc_protected_folders():
    assert DEFAULT_TRADINGAGENTS_REPO == (
        Path.home() / ".openclaw/workspace/tools/eth-meta-runtime/TradingAgents"
    )


@pytest.mark.parametrize("folder", ["Documents", "Desktop", "Downloads"])
@pytest.mark.parametrize("role", ["repo_root", "tradingagents_repo"])
def test_tcc_protected_runtime_path_rejects_descendants(tmp_path, folder, role):
    home = tmp_path / "home"
    candidate = home / folder / "projects" / "runtime"

    with pytest.raises(
        RuntimeError,
        match=rf"^TCC_PROTECTED_RUNTIME_PATH: {role}=.*{folder}/projects/runtime$",
    ):
        _require_tcc_safe_runtime_path(candidate, role=role, home=home)


@pytest.mark.parametrize(
    "candidate",
    [
        ".openclaw/workspace/tools/eth-meta-runtime",
        ".local/share/eth-meta-runtime",
        "Library/Application Support/eth-meta-runtime",
    ],
)
def test_tcc_runtime_path_accepts_safe_home_descendants(tmp_path, candidate):
    home = tmp_path / "home"
    path = home / candidate

    assert _require_tcc_safe_runtime_path(path, role="repo_root", home=home) == path.resolve()


def test_tcc_runtime_path_accepts_tmp():
    path = Path("/tmp/eth-meta-runtime")

    assert _require_tcc_safe_runtime_path(path, role="tradingagents_repo") == path.resolve()


def test_tcc_runtime_path_does_not_use_string_prefix_matching(tmp_path):
    home = tmp_path / "home"
    path = home / "Documents-safe" / "eth-meta-runtime"

    assert _require_tcc_safe_runtime_path(path, role="repo_root", home=home) == path.resolve()


def test_launchagent_print_plist_has_explicit_runtime_paths(tmp_path):
    runtime_repo = tmp_path / "eth-phase-meter"
    runtime_scripts = runtime_repo / "scripts"
    runtime_scripts.mkdir(parents=True)
    installer = runtime_scripts / "install_mac_meta_pipeline_launchd.py"
    shutil.copy2("scripts/install_mac_meta_pipeline_launchd.py", installer)
    (runtime_scripts / "run_local_meta_pipeline.py").write_text("print('ok')\n", encoding="utf-8")

    ta_repo = tmp_path / "TradingAgents"
    scripts = ta_repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run_tradingagents.py").write_text("print('ok')\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    codex = fake_bin / "codex"
    gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gh.chmod(0o755)
    codex.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(installer),
            "--tradingagents-repo",
            str(ta_repo),
            "--python",
            sys.executable,
            "--gh",
            str(gh),
            "--codex",
            str(codex),
            "--print-plist",
        ],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    payload = plistlib.loads(completed.stdout)
    assert payload["Label"] == "com.stanley.eth-meta-pipeline"
    assert payload["StartInterval"] == 900
    assert payload["RunAtLoad"] is False
    assert payload["ProgramArguments"][0] == str(Path(sys.executable))
    assert "run_local_meta_pipeline.py" in payload["ProgramArguments"][1]
    assert payload["ProgramArguments"][payload["ProgramArguments"].index("--gh") + 1] == str(gh)
    secret_index = payload["ProgramArguments"].index("--telegram-secret-file")
    assert payload["ProgramArguments"][secret_index + 1].endswith(".eth-meta-pipeline/telegram.json")
    assert "TG_BOT_TOKEN" not in payload["EnvironmentVariables"]
    assert "TG_CHAT_ID" not in payload["EnvironmentVariables"]
    assert set(payload["EnvironmentVariables"]) == {"HOME", "PATH", "PYTHONUNBUFFERED"}
    assert payload["EnvironmentVariables"]["PYTHONUNBUFFERED"] == "1"
    assert str(fake_bin) in payload["EnvironmentVariables"]["PATH"]
    assert payload["StandardOutPath"].endswith(".eth-meta-pipeline/launchd.stdout.log")
    assert b"TG_BOT_TOKEN" not in completed.stdout
    assert b"TG_CHAT_ID" not in completed.stdout
