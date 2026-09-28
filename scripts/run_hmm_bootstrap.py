import os

from eth_trend_v3.hmm_bootstrap import run_resilient
from eth_trend_v3.hmm_production import persist_production_model, build_production_model_record


def _set_output(name: str, value: str) -> None:
    target = os.getenv("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


if __name__ == "__main__":
    report = run_resilient(days=365)
    if report.get("status") == "EXTERNAL_DATA_UNAVAILABLE":
        _set_output("available", "false")
        _set_output("status", "EXTERNAL_DATA_UNAVAILABLE")
        print(
            f"HMM_BOOTSTRAP_EXTERNAL_DATA_UNAVAILABLE source={report.get('source')} "
            f"status_code={report.get('status_code')}"
        )
    else:
        _set_output("available", "true")
        _set_output("status", "OK")
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
