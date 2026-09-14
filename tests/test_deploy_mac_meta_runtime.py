import plistlib
import stat
import subprocess
from pathlib import Path

import pytest

import scripts.deploy_mac_meta_runtime as deploy


def result(command, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


@pytest.mark.parametrize("folder", ["Documents", "Desktop", "Downloads"])
def test_protected_runtime_rejected(tmp_path, folder):
    home = tmp_path / "home"

    with pytest.raises(RuntimeError, match="^TCC_PROTECTED_RUNTIME_PATH"):
        deploy._require_tcc_safe_runtime_path(
            home / folder / "runtime", role="runtime_root", home=home
        )


def test_new_clone_uses_pinned_single_branch_command(tmp_path):
    destination = tmp_path / "runtime" / "eth-phase-meter"
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[-2:] == ["rev-parse", "HEAD"]:
            return result(command, stdout="abc123\n")
        return result(command)

    sha = deploy.sync_repo(
        destination=destination,
        url=deploy.ETH_REPO_URL,
        branch=deploy.ETH_BRANCH,
        run_command=fake_run,
    )

    assert commands[0] == [
        "git",
        "clone",
        "--branch",
        "main",
        "--single-branch",
        deploy.ETH_REPO_URL,
        str(destination),
    ]
    assert sha == "abc123"


def _existing_repo_fake(destination, *, origin=None, branch="main", status=""):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        args = command[3:]
        if args == ["remote", "get-url", "origin"]:
            return result(command, stdout=f"{origin or deploy.ETH_REPO_URL}\n")
        if args == ["branch", "--show-current"]:
            return result(command, stdout=f"{branch}\n")
        if args == ["status", "--porcelain", "--untracked-files=no"]:
            return result(command, stdout=status)
        if args == ["rev-parse", "HEAD"]:
            return result(command, stdout="def456\n")
        return result(command)

    (destination / ".git").mkdir(parents=True)
    return commands, fake_run


def test_existing_clone_fetches_then_fast_forwards(tmp_path):
    destination = tmp_path / "eth-phase-meter"
    commands, fake_run = _existing_repo_fake(destination)

    deploy.sync_repo(
        destination=destination,
        url=deploy.ETH_REPO_URL,
        branch="main",
        run_command=fake_run,
    )

    assert ["git", "-C", str(destination), "fetch", "origin", "main"] in commands
    assert [
        "git",
        "-C",
        str(destination),
        "merge",
        "--ff-only",
        "origin/main",
    ] in commands
    assert not any("reset" in command or "clean" in command or "stash" in command for command in commands)


def test_dirty_tracked_clone_fails_closed_before_fetch(tmp_path):
    destination = tmp_path / "eth-phase-meter"
    commands, fake_run = _existing_repo_fake(destination, status=" M tracked.py\n")

    with pytest.raises(RuntimeError, match="^DIRTY_TRACKED"):
        deploy.sync_repo(
            destination=destination,
            url=deploy.ETH_REPO_URL,
            branch="main",
            run_command=fake_run,
        )

    assert not any("fetch" in command for command in commands)


def test_remote_mismatch_fails_closed(tmp_path):
    destination = tmp_path / "eth-phase-meter"
    _, fake_run = _existing_repo_fake(destination, origin="https://example.invalid/repo.git")

    with pytest.raises(RuntimeError, match="^REMOTE_MISMATCH"):
        deploy.sync_repo(
            destination=destination,
            url=deploy.ETH_REPO_URL,
            branch="main",
            run_command=fake_run,
        )


def test_branch_mismatch_fails_closed(tmp_path):
    destination = tmp_path / "eth-phase-meter"
    _, fake_run = _existing_repo_fake(destination, branch="feature/wrong")

    with pytest.raises(RuntimeError, match="^BRANCH_MISMATCH"):
        deploy.sync_repo(
            destination=destination,
            url=deploy.ETH_REPO_URL,
            branch="main",
            run_command=fake_run,
        )


def test_command_failure_has_stable_code(tmp_path):
    def fake_run(command, **kwargs):
        return result(command, stderr="offline", returncode=1)

    with pytest.raises(RuntimeError, match="^COMMAND_FAILED"):
        deploy.sync_repo(
            destination=tmp_path / "new-clone",
            url=deploy.ETH_REPO_URL,
            branch="main",
            run_command=fake_run,
        )


def test_env_source_is_copied_and_restricted(tmp_path):
    repo = tmp_path / "TradingAgents"
    repo.mkdir()
    source = tmp_path / "bootstrap.env"
    source.write_text("SECRET=not-logged\n", encoding="utf-8")
    source.chmod(0o644)

    destination = deploy.ensure_tradingagents_env(repo, source)

    assert destination.read_text(encoding="utf-8") == "SECRET=not-logged\n"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_existing_env_is_restricted_without_reading(tmp_path, monkeypatch):
    repo = tmp_path / "TradingAgents"
    repo.mkdir()
    destination = repo / ".env"
    destination.write_text("SECRET=value\n", encoding="utf-8")
    destination.chmod(0o644)

    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("env read"))
    deploy.ensure_tradingagents_env(repo)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_missing_env_fails(tmp_path):
    repo = tmp_path / "TradingAgents"
    repo.mkdir()

    with pytest.raises(RuntimeError, match="^TRADINGAGENTS_ENV_MISSING$"):
        deploy.ensure_tradingagents_env(repo)


def _dependency_repo(tmp_path):
    repo = tmp_path / "TradingAgents"
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='ta'\n", encoding="utf-8")
    (repo / ".venv" / "bin" / "python").touch()
    (repo / ".venv" / "bin" / "pip").touch()
    return repo


def test_unchanged_dependency_fingerprint_skips_install(tmp_path):
    repo = _dependency_repo(tmp_path)
    marker = repo / ".venv" / deploy.DEPENDENCY_MARKER
    marker.write_text(deploy.dependency_fingerprint(repo) + "\n", encoding="utf-8")
    commands = []

    action = deploy.sync_dependencies(
        repo,
        base_python="/base/python",
        run_command=lambda command, **kwargs: commands.append(command) or result(command),
    )

    assert action == "SKIPPED"
    assert commands == []


def test_changed_dependency_fingerprint_syncs_install(tmp_path):
    repo = _dependency_repo(tmp_path)
    marker = repo / ".venv" / deploy.DEPENDENCY_MARKER
    marker.write_text("old\n", encoding="utf-8")
    commands = []

    action = deploy.sync_dependencies(
        repo,
        base_python="/base/python",
        run_command=lambda command, **kwargs: commands.append(command) or result(command),
    )

    assert action == "SYNCED"
    assert commands == [[str(repo / ".venv/bin/pip"), "install", "-e", "."]]
    assert marker.read_text(encoding="utf-8").strip() == deploy.dependency_fingerprint(repo)


@pytest.mark.parametrize("missing_executable", ["python", "pip"])
def test_incomplete_venv_is_repaired_in_place_and_dependencies_sync(
    tmp_path, missing_executable
):
    repo = _dependency_repo(tmp_path)
    venv = repo / ".venv"
    (venv / "preserved").write_text("keep\n", encoding="utf-8")
    (venv / "bin" / missing_executable).unlink()
    marker = venv / deploy.DEPENDENCY_MARKER
    marker.write_text(deploy.dependency_fingerprint(repo) + "\n", encoding="utf-8")
    commands = []

    action = deploy.sync_dependencies(
        repo,
        base_python="/base/python",
        run_command=lambda command, **kwargs: commands.append(command) or result(command),
    )

    assert action == "SYNCED"
    assert commands == [
        ["/base/python", "-m", "venv", str(venv)],
        [str(venv / "bin" / "pip"), "install", "-e", "."],
    ]
    assert (venv / "preserved").read_text(encoding="utf-8") == "keep\n"


def test_smoke_plist_only_runs_help_from_safe_working_directory(tmp_path):
    home = tmp_path / "home"
    eth_repo = home / ".openclaw" / "runtime" / "eth-phase-meter"
    plist = deploy.build_smoke_plist(
        eth_repo=eth_repo,
        base_python="/opt/anaconda3/bin/python",
        exit_path=home / "smoke.exit",
        stdout_path=home / "smoke.out",
        stderr_path=home / "smoke.err",
    )
    encoded = plistlib.dumps(plist)

    assert plist["WorkingDirectory"] == str(eth_repo)
    assert plist["ProgramArguments"][-1] == "--help"
    assert "run_local_meta_pipeline.py" in plist["ProgramArguments"][-2]
    assert b"--force-ta" not in encoded
    assert b"TradingAgents" not in encoded


def test_default_does_not_kickstart_production():
    commands = []
    deploy.maybe_kickstart_production(
        False,
        run_command=lambda command, **kwargs: commands.append(command) or result(command),
    )
    assert commands == []


def test_explicit_flag_kickstarts_production():
    commands = []
    deploy.maybe_kickstart_production(
        True,
        run_command=lambda command, **kwargs: commands.append(command) or result(command),
    )
    assert commands == [
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{deploy.os.getuid()}/com.stanley.eth-meta-pipeline",
        ]
    ]
