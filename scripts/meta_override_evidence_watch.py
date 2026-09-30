#!/usr/bin/env python3
from __future__ import annotations
import json, os
from eth_trend_v3.meta_action_outcomes import load_meta_action_events
from scripts.send_system_health import send_message

CHECKPOINTS=(1,5,10,20,30)
REASONS={"PHASE_BULLISH_TA_NEUTRAL","PHASE_BEARISH_TA_NEUTRAL"}
WATCH_KEY="meta-override-evidence-v1"

def override_count(events):
    return sum(any(r in REASONS for r in (e.get("reason_codes") or [])) for e in events)

def reached_checkpoint(n, last):
    reached=[x for x in CHECKPOINTS if last < x <= n]
    return max(reached) if reached else None

def message(n, checkpoint):
    review="YES — review gate reached; no automatic promotion." if n>=30 else "NO — continue accumulating prospective evidence."
    return "\n".join([
        "🔬 <b>ETH Meta Override Evidence</b>",
        f"Checkpoint: <b>N={checkpoint}</b>",
        f"Independent override events: <b>{n}</b>",
        "Signal: TA-neutral + strong Phase confirmation → ADD/REDUCE",
        f"Promotion review ready: <b>{review}</b>",
        "Guardrail: research-only; no threshold, sizing, model promotion, or execution change.",
    ])

def main():
    dsn=os.getenv("DATABASE_URL")
    if not dsn: raise SystemExit("DATABASE_URL is required")
    import psycopg
    n=override_count(load_meta_action_events(dsn))
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(WATCH_KEY,))
            cur.execute("SELECT last_notified_checkpoint FROM eth_meta_override_evidence_watch WHERE watch_key=%s",(WATCH_KEY,))
            row=cur.fetchone(); last=int(row[0]) if row else 0
            checkpoint=reached_checkpoint(n,last)
            result={"status":"NO_NEW_CHECKPOINT","override_event_count":n,"last_notified_checkpoint":last}
            if checkpoint is not None:
                sent=send_message(message(n,checkpoint))
                result={"status":sent.get("status"),"override_event_count":n,"checkpoint":checkpoint,"telegram":sent}
                if sent.get("status")=="SENT":
                    cur.execute("""INSERT INTO eth_meta_override_evidence_watch(watch_key,last_notified_checkpoint)
                      VALUES(%s,%s) ON CONFLICT(watch_key) DO UPDATE SET
                      last_notified_checkpoint=EXCLUDED.last_notified_checkpoint,updated_at=NOW()""",(WATCH_KEY,checkpoint))
            conn.commit()
    print(json.dumps(result,sort_keys=True))
    return 1 if result["status"]=="FAILED" else 0
if __name__=="__main__": raise SystemExit(main())
