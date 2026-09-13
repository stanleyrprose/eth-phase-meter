import plistlib
import subprocess
import sys
from pathlib import Path


def test_launchagent_print_plist_has_explicit_runtime_paths(tmp_path):
    ta_repo = tmp_path / "TradingAgents"
    scripts = ta_repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run_tradingagents.py").write_text("print('ok')\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/install_mac_meta_pipeline_launchd.py",
            "--tradingagents-repo",
            str(ta_repo),
            "--python",
            sys.executable,
            "--gh",
            "/opt/homebrew/bin/gh",
            "--codex",
            "/opt/homebrew/bin/codex",
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
    assert payload["ProgramArguments"][-1] == "/opt/homebrew/bin/gh"
    assert "/opt/homebrew/bin" in payload["EnvironmentVariables"]["PATH"]
    assert payload["StandardOutPath"].endswith(".eth-meta-pipeline/launchd.stdout.log")
