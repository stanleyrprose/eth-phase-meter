# GitHub Actions deployment

`ETH Phase Meter` can run on GitHub-hosted runners every four hours and can also be triggered manually.

## Repository secrets

Open **Settings → Secrets and variables → Actions → New repository secret** and add these required Telegram credentials:

- `TG_BOT_TOKEN`
- `TG_CHAT_ID`

For full data-source coverage, also add these optional secrets if you have them:

- `FRED_API_KEY`
- `FINNHUB_API_KEY`
- `CRYPTOPANIC_API_KEY`
- `ETHERSCAN_API_KEY`

The workflow injects these values only as environment variables. They are not stored in repository files.

## Manual run

Open **Actions → ETH Phase Meter → Run workflow**.

## Schedule

The production monitor cron is `15 */4 * * *`, which means 00:15, 04:15, 08:15, 12:15, 16:15 and 20:15 UTC every day.

### Scheduled-monitor watchdog

`ETH Scheduled Monitor Watchdog` runs hourly at minute 45. It queries the production monitor run history and uses a 4-hour expected cadence with a 5-hour stale threshold.

- If the latest successful monitor is fresh, it records `LATEST_SUCCESS_FRESH` and does nothing.
- If a monitor is already queued/in progress, it records `ACTIVE_MONITOR_RUN_PRESENT` and does not dispatch a duplicate.
- If the latest successful monitor is older than 5 hours, or no successful run exists, it dispatches the existing `scheduled-monitor.yml` on `main` via `workflow_dispatch`.
- Every watchdog run uploads `watchdog-report.json` with the expected cadence, actual latest success, age, decision, and recovery reason.

The watchdog does not implement a second monitoring path and does not alter model/forecast state itself; recovery always goes through the canonical scheduled-monitor workflow.

## Reports

Production monitor runs upload `eth_reports/`, and watchdog runs upload `watchdog-report.json`. Both are retained for 30 days.
