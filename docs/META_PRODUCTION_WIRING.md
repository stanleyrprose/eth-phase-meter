# ETH Meta Decision Production Wiring v1

## Decision

Use an event-triggered local bridge on the Mac mini rather than running the full TradingAgents graph every four hours.

The authoritative Phase Meter run remains GitHub Actions. The Mac mini consumes the latest successful `ETH Scheduled Monitor` artifact and runs TradingAgents only when the Phase Meter state materially changes or the prior TradingAgents judgment is stale.

This preserves the existing trust boundaries:

- GitHub Actions remains the authoritative Phase Meter execution plane.
- TradingAgents keeps its local ChatGPT/Codex OAuth runtime on the Mac mini.
- No OAuth credential is copied into GitHub Actions.
- The bridge never places an order and never changes Phase Meter production model state.

## Flow

```text
GitHub Actions: ETH Scheduled Monitor (every 4h)
        |
        | artifact: eth_reports/latest_monitor.json
        v
Mac mini: run_local_meta_pipeline.py
        |
        +--> trigger policy --> DEFER / REUSE / RUN
        |                         |       |
        |                         |       +--> TradingAgents ETH-USD
        |                         |             -> tradingagents_decision.json
        |                         |
        |                         +--> reuse fresh decision.json
        |
        v
eth_trend_v3.meta_decision
        |
        v
~/.eth-meta-pipeline/meta_decision.json
```

## Trigger policy

`RUN` is emitted when at least one material condition is true:

- TradingAgents contract is missing, invalid, or older than 24 hours.
- No previous local Phase Meter baseline exists.
- 4h regime changes.
- 4h direction crosses +20 or -20.
- 4h direction moves by at least 15 points.
- 1h direction crosses +15 or -15.
- 4h momentum flips sign and the new magnitude is at least 20.
- 4h order flow flips sign and the new magnitude is at least 25.
- options positioning crosses the `-25` blocking threshold used by Meta Decision ADD confirmation.
- volatility risk crosses 60 or changes by at least 20 points.

`REUSE` is emitted when the Phase Meter state has no material change and the existing TradingAgents contract is still fresh.

`DEFER` is emitted when either 1h or 4h Phase Meter evidence is stale, has coverage below 80%, Data Health is not `NORMAL`, or Model Health is `MODEL_UNRELIABLE`. Bad Phase Meter evidence must not trigger an expensive multi-agent run.

## Local state

Default directory: `~/.eth-meta-pipeline/`

Files:

- `state.json`: last processed GitHub run id and pipeline status.
- `latest_monitor.json`: previous Phase Meter baseline for state-change comparison.
- `tradingagents_trigger.json`: latest `eth-tradingagents-trigger-v1` contract.
- `tradingagents_decision.json`: latest `tradingagents-decision-v1` contract.
- `meta_decision.json`: latest `eth-meta-decision-v1` result.
- `telegram.json`: optional local Telegram credentials (owner-readable only).
- `progress.jsonl`: append-only, flushed JSONL stage progress for the current and previous invocations.
- `launchd.stdout.log` / `launchd.stderr.log`: local scheduler logs.

A failed TradingAgents execution does not mark the GitHub monitor run as processed, so a later scheduler invocation can retry the same source artifact.

## Change-only Telegram notification

The first Meta recommendation establishes a baseline without sending. Later runs send only when the recommendation differs from the last successfully notified recommendation. Telegram delivery is fail-open: a transient failure leaves the notification baseline unchanged for a later retry while the market-decision pipeline remains successful. If credentials are absent, the run records `SKIPPED_UNCONFIGURED` and advances the baseline so enabling Telegram later does not replay old changes.

Environment variables `TG_BOT_TOKEN` and `TG_CHAT_ID` take precedence. For launchd, use the default local secret file and restrict it to the owner:

```bash
mkdir -p ~/.eth-meta-pipeline
cat > ~/.eth-meta-pipeline/telegram.json <<'JSON'
{
  "bot_token": "<TELEGRAM_BOT_TOKEN>",
  "chat_id": "<TELEGRAM_CHAT_ID>"
}
JSON
chmod 600 ~/.eth-meta-pipeline/telegram.json
```

The installer places only the secret-file path in the plist; it never copies credentials into `EnvironmentVariables`. A present secret file with any group or other permission bits is rejected. Credential values are never printed.

## Manual run

```bash
python scripts/run_local_meta_pipeline.py \
  --tradingagents-repo /Users/xu/Documents/mcpx-projects/TradingAgents-codex-oauth
```

The script uses `gh` to locate and download the latest successful `scheduled-monitor.yml` artifact. It exits immediately with `NO_NEW_MONITOR_RUN` when the same GitHub run was already processed.

Use `--force-ta` for a deliberate full TradingAgents refresh. This is an operator override for analysis refresh only; it does not enable trading execution.

## macOS LaunchAgent

Production uses a clean `main` worktree, recommended path:

`/Users/xu/Documents/mcpx-projects/eth-phase-meter-production`

Install the 15-minute LaunchAgent from that worktree:

```bash
/opt/anaconda3/bin/python scripts/install_mac_meta_pipeline_launchd.py \
  --tradingagents-repo /Users/xu/Documents/mcpx-projects/TradingAgents-codex-oauth \
  --gh /opt/homebrew/bin/gh \
  --codex /opt/homebrew/bin/codex
```

The installer writes `~/Library/LaunchAgents/com.stanley.eth-meta-pipeline.plist`, explicitly sets `HOME`, a PATH containing the Python, GitHub CLI, and Codex CLI directories, and `PYTHONUNBUFFERED=1`, and schedules the bridge every 900 seconds. `RunAtLoad` is intentionally false so installation itself does not unexpectedly launch an expensive TradingAgents graph. Use `--kickstart` only when an immediate run is desired.

## Progress and hang troubleshooting

Each invocation appends flushed stage records to `~/.eth-meta-pipeline/progress.jsonl` and immediately prints the stage name (without detail values) to `launchd.stdout.log`. Explicit stages confirm completed GitHub artifact downloads and completed `state.json` writes for both normal and deferred runs. To see where the latest invocation stopped:

```bash
tail -n 30 ~/.eth-meta-pipeline/progress.jsonl
tail -n 100 ~/.eth-meta-pipeline/launchd.stdout.log
tail -n 100 ~/.eth-meta-pipeline/launchd.stderr.log
```

The GitHub run lookup, artifact download, and TradingAgents wrapper have hard time limits of 30 seconds, 120 seconds, and 3600 seconds. Their stable failure codes are `GH_RUN_LIST_TIMEOUT`, `GH_RUN_DOWNLOAD_TIMEOUT`, and `TRADINGAGENTS_TIMEOUT`. A timed-out subprocess is terminated with its POSIX process group so child processes do not remain behind.

The whole pipeline also has a POSIX watchdog of 4200 seconds. Override it for an operator diagnostic with `--watchdog-seconds SECONDS`, or disable it explicitly with `--watchdog-seconds 0`. Expiry reports `PIPELINE_WATCHDOG_TIMEOUT`; the watchdog alarm is cancelled when execution exits normally or with an error. While a run is active, delayed Python tracebacks are written to stderr every 60 seconds, which makes a minute-scale blocked stack visible in `launchd.stderr.log` without changing trigger, forecast, Meta Decision, or notification behavior.

## Non-goals

v1 intentionally does not:

- run TradingAgents inside GitHub Actions;
- add a webhook service;
- create an HTTP control plane;
- place trades or allocate capital;
- convert deterministic scores into forecast probabilities;
- merge TradingAgents and Phase Meter into one model.
