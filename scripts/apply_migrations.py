from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def apply_migrations(migrations_dir: str = "migrations") -> dict:
    dsn = os.getenv("DATABASE_URL")
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_configured": bool(dsn),
        "applied": [],
        "skipped": [],
        "status": "SKIPPED_NO_DATABASE" if not dsn else "UNKNOWN",
    }
    if not dsn:
        return report

    import psycopg
    paths = sorted(Path(migrations_dir).glob("*.sql"))
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS eth_schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            for path in paths:
                version = path.name
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                cur.execute("SELECT checksum FROM eth_schema_migrations WHERE version=%s", (version,))
                row = cur.fetchone()
                if row:
                    if row[0] != checksum:
                        raise RuntimeError(f"migration checksum mismatch: {version}")
                    report["skipped"].append(version)
                    continue
                cur.execute(sql)
                cur.execute("INSERT INTO eth_schema_migrations(version,checksum) VALUES(%s,%s)", (version, checksum))
                report["applied"].append(version)
        conn.commit()
    report["status"] = "PASS"
    return report


def main():
    report = apply_migrations()
    out = Path("eth_reports/governance")
    out.mkdir(parents=True, exist_ok=True)
    (out / "migration_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
