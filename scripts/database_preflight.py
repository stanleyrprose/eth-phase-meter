from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os


@dataclass(frozen=True)
class DatabaseHealth:
    configured: bool
    available: bool
    reason: str
    error_type: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def classify_database_error(message: str) -> str:
    text = str(message).lower()
    if "exceeded the quota" in text or "quota" in text and "exceed" in text:
        return "QUOTA_EXCEEDED"
    if "network is unreachable" in text:
        return "NETWORK_UNREACHABLE"
    if "timeout" in text or "timed out" in text:
        return "CONNECTION_TIMEOUT"
    if "password authentication failed" in text or "authentication failed" in text:
        return "AUTHENTICATION_FAILED"
    return "DATABASE_UNAVAILABLE"


def check_database(dsn: str | None) -> DatabaseHealth:
    if not dsn:
        return DatabaseHealth(configured=False, available=False, reason="NOT_CONFIGURED")

    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return DatabaseHealth(configured=True, available=True, reason="OK")
    except Exception as exc:
        return DatabaseHealth(
            configured=True,
            available=False,
            reason=classify_database_error(str(exc)),
            error_type=type(exc).__name__,
        )


def _append_github_output(path: str | None, health: DatabaseHealth) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"available={'true' if health.available else 'false'}\n")
        handle.write(f"configured={'true' if health.configured else 'false'}\n")
        handle.write(f"reason={health.reason}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check PostgreSQL availability without exposing the DSN.")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT"))
    args = parser.parse_args()

    health = check_database(os.getenv("DATABASE_URL"))
    _append_github_output(args.github_output, health)
    print(json.dumps(health.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
