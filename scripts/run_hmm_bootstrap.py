from eth_trend_v3.hmm_bootstrap import run
from eth_trend_v3.hmm_production import build_production_model_record, persist_production_model


if __name__ == "__main__":
    report = run(days=365)
    preferred = report.get("preferred_descriptive_variant")
    variant = (report.get("variants") or {}).get(preferred) if preferred else None
    winner = (variant or {}).get("winner")
    production = build_production_model_record(report)
    if winner:
        print(
            f"HMM_BOOTSTRAP_OK variant={preferred} winner={winner['n_states']}-state "
            f"observations={report['observation_count']}"
        )
    else:
        print(f"HMM_BOOTSTRAP_NO_WINNER observations={report['observation_count']}")
    if production is None:
        print("HMM_PRODUCTION_NOT_ELIGIBLE")
    else:
        persisted = persist_production_model(report)
        print(f"HMM_PRODUCTION_PERSISTED={persisted}")
