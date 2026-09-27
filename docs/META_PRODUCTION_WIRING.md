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
        |
        +--> freeze meta-action-v1 event
        |        |
        |        +--> gh workflow dispatch
        |                 |
        |                 v
        |          GitHub Actions: ETH Meta Action Outcomes
        |                 +--> TG fallback via GitHub Secrets when local TG is unavailable
        |                 +--> BKK PostgreSQL append-only event/outcome research
        |
        v
non-secret runtime status surface
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
- `meta_action_event.json`: latest frozen non-secret `meta-action-v1` research event awaiting/already sent to GitHub.
- `telegram.json`: optional local Telegram credentials (owner-readable only).
- `progress.jsonl`: append-only, flushed JSONL stage progress for the current and previous invocations.
- `launchd.stdout.log` / `launchd.stderr.log`: local scheduler logs.

A failed TradingAgents execution does not mark the GitHub monitor run as processed, so a later scheduler invocation can retry the same source artifact.

## Runtime deployment/update

From a development checkout, the normal one-command deployment or update is:

```bash
/opt/anaconda3/bin/python scripts/deploy_mac_meta_runtime.py
```

On first bootstrap, provide the existing TradingAgents environment file; it is copied into the clean runtime with owner-only permissions:

```bash
/opt/anaconda3/bin/python scripts/deploy_mac_meta_runtime.py \
  --tradingagents-env-source /path/to/TradingAgents/.env
```

Dependency installation is skipped when the virtual environment is complete and the dependency manifests are unchanged. Use `--refresh-deps` to force an editable dependency reinstall; an incomplete virtual environment is always repaired in place and synchronized.

The default smoke checks TradingAgents detect-only readiness, Codex login, and the latest successful GitHub monitor run, then temporarily launches the local pipeline with `--help` under `launchd`. It does **not** run a full TradingAgents graph and does **not** kickstart the production pipeline. Add `--kickstart-production` only when the deployment should explicitly start the installed production LaunchAgent immediately after all checks pass.

## Per-monitor Action-first Telegram notification

Every newly processed successful 4H monitor artifact produces one Meta Action snapshot, even when the recommendation is unchanged. The pipeline already deduplicates GitHub monitor run IDs, so this makes the current `ADD` / `HOLD` / `REDUCE` / `AVOID` decision visible without creating duplicate notifications for the same source run.

The message is Action-first: recommendation and exposure semantics come first, followed by evidence alignment, TradingAgents, 1H/4H direction and regime, 4H momentum/order-flow/options/volatility, confirmation gaps or blocking reasons, optional Kronos shadow context, and the explicit no-order-execution guardrail. `evidence_alignment` remains descriptive and is not presented as a calibrated confidence or probability.

Telegram delivery remains fail-open. Local Mac credentials are optional: if local delivery is not `SENT`, the frozen Meta Action event requests a GitHub delivery fallback. The Mac dispatches only non-secret evidence; the `ETH Meta Action Outcomes` workflow uses the repository's existing `TG_BOT_TOKEN` / `TG_CHAT_ID` Secrets to send the same Action-first message. This also avoids copying Telegram credentials into the launchd environment.

A failed GitHub dispatch is research/delivery fail-soft relative to the Meta decision and leaves the monitor run processed. The bridge records the failed dispatch and, on later 15-minute polls of the same already-processed 4H run, retries the frozen event until GitHub accepts it. PostgreSQL event insertion is idempotent by deterministic event id.

Local credentials still remain supported. Environment variables `TG_BOT_TOKEN` and `TG_CHAT_ID` take precedence. If a local secret file is used, restrict it to the owner:

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
  --tradingagents-repo ~/.openclaw/workspace/tools/eth-meta-runtime/TradingAgents
```

The script uses `gh` to locate and download the latest successful `scheduled-monitor.yml` artifact. It exits immediately with `NO_NEW_MONITOR_RUN` when the same GitHub run was already processed.

Use `--force-ta` for a deliberate full TradingAgents refresh. This is an operator override for analysis refresh only; it does not enable trading execution.

To inspect the current production state without exposing credentials:

```bash
python scripts/meta_runtime_status.py
```

The status surface reports the last processed monitor run, Meta recommendation/alignment, TradingAgents decision, local notification state, and Meta research dispatch state. It never reads or prints Telegram credential values.

## macOS LaunchAgent

Production uses clean runtime worktrees outside macOS TCC-protected user folders. The recommended layout is:

```text
~/.openclaw/workspace/tools/eth-meta-runtime/
├── eth-phase-meter/
└── TradingAgents/
```

Real `launchd` A/B testing showed that background Python can hang before script execution when its script or repository is under `~/Documents`; macOS `tccd` logs corroborated TCC attribution. The installer therefore fails closed when either runtime repository is `~/Documents`, `~/Desktop`, `~/Downloads`, or any descendant. Development repositories may remain in `Documents`, but the `launchd` runtime worktrees must not.

Install the 15-minute LaunchAgent from that worktree:

```bash
cd ~/.openclaw/workspace/tools/eth-meta-runtime/eth-phase-meter
/opt/anaconda3/bin/python scripts/install_mac_meta_pipeline_launchd.py \
  --tradingagents-repo ~/.openclaw/workspace/tools/eth-meta-runtime/TradingAgents \
  --gh /opt/homebrew/bin/gh \
  --codex /opt/homebrew/bin/codex
```

The LaunchAgent installer defaults the TradingAgents runtime to `~/.openclaw/workspace/tools/eth-meta-runtime/TradingAgents`, so `--tradingagents-repo` may be omitted for this layout. Paths under `~/.openclaw`, `~/.local`, `~/Library`, and `/tmp` are not rejected by this TCC guard.

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
