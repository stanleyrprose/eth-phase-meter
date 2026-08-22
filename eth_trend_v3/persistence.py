from __future__ import annotations
import json
import os


def persistence_mode() -> str:
    return "POSTGRES" if os.getenv("DATABASE_URL") else "ARTIFACT_ONLY"


def persist_json_record(record_type: str, payload: dict) -> bool:
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
                cur.execute("INSERT INTO eth_monitor_records(record_type, payload) VALUES (%s, %s::jsonb)", (record_type, json.dumps(payload, ensure_ascii=False, default=str)))
            conn.commit()
        return True
    except Exception:
        return False


def load_latest_record(record_type: str) -> dict | None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        return None
    try:
        import psycopg
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM eth_monitor_records WHERE record_type=%s ORDER BY created_at DESC LIMIT 1", (record_type,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None
