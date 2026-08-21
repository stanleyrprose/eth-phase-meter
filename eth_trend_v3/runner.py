import datetime as dt
import json
from pathlib import Path
import eth_phase_meter as core
from .collectors import collect
from .features import all_factors
from .engine import evaluate
from .notify import telegram_text
from .storage import update_history
from .pit import build_pit_record, write_pit_snapshot, write_run_manifest
from .persistence import persist_json_record, persistence_mode

OUTPUT = Path(core.OUTPUT_DIR)


def run_one(timeframe):
    ts = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    raw = collect(timeframe)
    factors = all_factors(raw)
    result = evaluate(timeframe, raw, factors, ts)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # Legacy CSV remains a research convenience only; it is not the PIT source of truth.
    update_history(OUTPUT / 'v3_history.csv', result)
    (OUTPUT / f'v3_snapshot_{timeframe}.json').write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8'
    )

    pit_path = write_pit_snapshot(OUTPUT, timeframe, raw, result)
    pit_record = build_pit_record(timeframe, raw, result)
    persisted = persist_json_record('pit_snapshot', pit_record)
    pit_record['quality_flags']['external_persisted'] = persisted
    pit_path.write_text(json.dumps(pit_record, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    text = telegram_text(result)
    print(text)
    print(f'PIT persistence: {persistence_mode()} | external_persisted={persisted}')
    if core.TG_BOT_TOKEN and core.TG_CHAT_ID:
        core.send_tg_message(text)
    return result


def apply_execution_gate(results):
    r1, r4 = results.get('1h'), results.get('4h')
    if not r1 or not r4:
        return
    d1, d4 = r1.final_direction, r4.final_direction
    if abs(d1) >= 20 and abs(d4) >= 20 and d1 * d4 < 0:
        r1.execution_gate = 'BLOCKED'
        r1.execution_reason = f'1h与4h方向冲突 (1h={d1:+d}, 4h={d4:+d})'
    elif abs(d1) >= 20 and abs(d4) < 20:
        r1.execution_gate = 'WAIT'
        r1.execution_reason = f'4h方向证据不足 ({d4:+d})'
    else:
        r1.execution_gate = 'PASS'
        r1.execution_reason = f'4h={d4:+d}'


def main():
    results = {'4h': run_one('4h'), '1h': run_one('1h')}
    apply_execution_gate(results)
    manifest_path = write_run_manifest(OUTPUT, results)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['external_persisted'] = persist_json_record('run_manifest', manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    r1 = results['1h']
    gate = f"🚦 Execution Gate: <b>{r1.execution_gate}</b> | {r1.execution_reason}"
    print(gate)
    if core.TG_BOT_TOKEN and core.TG_CHAT_ID:
        core.send_tg_message(gate)
    return results


if __name__ == '__main__':
    main()
