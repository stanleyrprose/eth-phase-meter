#!/usr/bin/env bash
set -euo pipefail

LABEL="${ETH_SCHEDULER_LABEL:-com.stanley.eth-phase-scheduler}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
GH_BIN="${GH_BIN:-$(command -v gh)}"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/.eth-phase-scheduler"
RUNTIME_DIR="${LOG_DIR}/runtime"
DOMAIN="gui/$(id -u)"

if [[ -z "${PYTHON_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: python3 not found or not executable" >&2
  exit 1
fi
if [[ -z "${GH_BIN}" || ! -x "${GH_BIN}" ]]; then
  echo "ERROR: gh not found or not executable" >&2
  exit 1
fi

"${GH_BIN}" auth status >/dev/null

mkdir -p "$(dirname "${PLIST_PATH}")" "${LOG_DIR}" "${RUNTIME_DIR}"
install -m 0644 "${REPO_ROOT}/scripts/external_scheduler_dispatch.py" "${RUNTIME_DIR}/external_scheduler_dispatch.py"

"${PYTHON_BIN}" - "${PLIST_PATH}" "${LABEL}" "${RUNTIME_DIR}" "${PYTHON_BIN}" "${GH_BIN}" "${LOG_DIR}" <<'PY'
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

plist_path, label, runtime_dir, python_bin, gh_bin, log_dir = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": [
        python_bin,
        str(Path(runtime_dir) / "external_scheduler_dispatch.py"),
        "--repo",
        "stanleyrprose/eth-phase-meter",
        "--gh",
        gh_bin,
    ],
    "WorkingDirectory": runtime_dir,
    "EnvironmentVariables": {
        "HOME": str(Path.home()),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    },
    "StartInterval": 300,
    "RunAtLoad": True,
    "ProcessType": "Background",
    "StandardOutPath": str(Path(log_dir) / "scheduler.log"),
    "StandardErrorPath": str(Path(log_dir) / "scheduler.err.log"),
}
with open(plist_path, "wb") as handle:
    plistlib.dump(payload, handle, sort_keys=False)
PY

/usr/bin/plutil -lint "${PLIST_PATH}"
/bin/launchctl bootout "${DOMAIN}" "${PLIST_PATH}" 2>/dev/null || true
/bin/launchctl bootstrap "${DOMAIN}" "${PLIST_PATH}"
/bin/launchctl kickstart -k "${DOMAIN}/${LABEL}"
/bin/launchctl print "${DOMAIN}/${LABEL}" | sed -n '1,80p'

echo "Installed ${LABEL}"
echo "Runtime: ${RUNTIME_DIR}"
echo "Logs: ${LOG_DIR}"
