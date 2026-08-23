from eth_trend_v3.hmm_bootstrap import run
from eth_trend_v3.hmm_production import persist_production_model, build_production_model_record


if __name__ == "__main__":
    report = run(days=365)
    preferred = report.get("preferred_descriptive_variant")
    record = build_production_model_record(report)
    persisted = persist_production_model(report) if record else False
    if preferred:
        variant = (report.get("variants") or {}).get(preferred) or {}
        winner = variant.get("winner") or {}
        print(
            f"HMM_BOOTSTRAP_OK preferred={preferred} "
            f"winner={winner.get('n_states')}-state observations={report['observation_count']} "
            f"production_record={'yes' if record else 'no'} persisted={persisted}"
        )
    else:
        print(f"HMM_BOOTSTRAP_NO_WINNER observations={report['observation_count']}")
