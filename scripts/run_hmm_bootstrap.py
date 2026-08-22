from eth_trend_v3.hmm_bootstrap import run


if __name__ == "__main__":
    report = run(days=365)
    winner = report.get("winner")
    if winner:
        print(f"HMM_BOOTSTRAP_OK winner={winner['n_states']}-state observations={report['observation_count']}")
    else:
        print(f"HMM_BOOTSTRAP_NO_WINNER observations={report['observation_count']}")
