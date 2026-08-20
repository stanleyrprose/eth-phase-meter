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

The workflow cron is `15 */4 * * *`, which means 00:15, 04:15, 08:15, 12:15, 16:15 and 20:15 UTC every day.

## Reports

Each workflow run uploads the `eth_reports/` directory as a GitHub Actions artifact and retains it for 14 days.
