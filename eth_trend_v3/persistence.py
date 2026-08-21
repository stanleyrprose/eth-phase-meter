from __future__ import annotations
import json
import os
from pathlib import Path


def persistence_mode() -> str:
    return "POSTGRES" if os.getenv("DATABASE_URL") else "ARTIFACT_ONLY"


def persist_json_record(record_type: str, payload: dict) -> bool:
    """Best-effort external persistence hook.

    Phase 0 does not pretend PostgreSQL is configured. When DATABASE_URL is absent,
    callers keep artifact output only and mark persistence degraded. When configured,
    psycopg is imported lazily and records are appended to a generic JSONB table.
    """
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        return False
    try:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS eth_monitor_records (
                        id BIGSERIAL PRIMARY KEY,
                        record_type TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        payload JSONB NOT NULL
                    )
                """)
                cur.execute(
                    "INSERT INTO eth_monitor_records(record_type, payload) VALUES (%s, %s::jsonb)",
                    (record_type, json.dumps(payload, ensure_ascii=False, default=str)),
                )
            conn.commit()
        return True
    except Exception:
        return False
