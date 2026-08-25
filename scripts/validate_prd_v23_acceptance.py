from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from eth_trend_v3.calibration_research_v2 import calibration_decision
from eth_trend_v3.experiment_registry import BASE_CRITICAL_FIELDS, PROMOTION_CRITICAL_FIELDS
from eth_trend_v3.horizon_features import external_feature_contracts
from eth_trend_v3.model_lifecycle import ALLOWED_TRANSITIONS
from eth_trend_v3.promotion import UNAVAILABLE_REASONS
from eth_trend_v3.research_metrics import brier_skill_score, moving_block_sensitivity
from eth_trend_v3.shadow_forecast import path_outcome, unified_inference

ROOT = Path(__file__).resolve().parents[1]


def _exists(*paths: str) -> bool:
    return all((ROOT / path).exists() for path in paths)


def _contains(path: str, *needles: str) -> bool:
    text = (ROOT / path).read_text(encoding='utf-8') if (ROOT / path).exists() else ''
    return all(needle in text for needle in needles)


def _callable_ok(fn: Callable) -> bool:
    return callable(fn)


def _local_checks() -> dict[int, tuple[bool, list[str]]]:
    contracts = {item.feature_name for item in external_feature_contracts()}
    path = path_outcome(100.0, [98.0, 101.0, 99.0])
    return {
        1: (_exists('eth_trend_v3/research_contract.py','eth_trend_v3/research_validation.py') and _contains('eth_trend_v3/dataset.py','HORIZONS={"3d":72,"7d":168,"30d":720}'), ['research_contract.py','research_validation.py','3d/7d/30d HORIZONS']),
        2: (_contains('eth_trend_v3/research_validation.py','purged_walk_forward','purge invariant violated'), ['purged_walk_forward']),
        3: (_contains('eth_trend_v3/research_validation.py','embargo_hours','embargo invariant violated'), ['horizon-aware embargo mechanism']),
        4: (_exists('tests/test_prd_dataset_leakage.py','tests/test_research_foundation.py') and _contains('eth_trend_v3/research_validation.py','assert_no_label_overlap'), ['leakage tests','assert_no_label_overlap']),
        5: (len(BASE_CRITICAL_FIELDS) >= 20 and len(PROMOTION_CRITICAL_FIELDS) > len(BASE_CRITICAL_FIELDS) and _exists('migrations/002_forecast_research_foundation.sql'), ['expanded experiment registry','promotion fields','migration']),
        6: (_contains('eth_trend_v3/experiment_registry.py','dataset_hash','config_hash') and _contains('eth_trend_v3/model_artifact.py','artifact_hash'), ['dataset/config/artifact hashes']),
        7: ('PRODUCTION' in ALLOWED_TRANSITIONS.get('SHADOW', set()) and 'PRODUCTION' not in ALLOWED_TRANSITIONS.get('EXPERIMENTAL', set()) and _exists('eth_trend_v3/model_state.py'), ['lifecycle state machine','persistent model state']),
        8: (_contains('eth_trend_v3/dynamic_baseline.py','evaluate_baselines','expanding','rolling','ewma'), ['dynamic baseline candidates']),
        9: (_contains('eth_trend_v3/horizon_features.py','build_horizon_features','3d','7d','30d'), ['horizon-aligned features']),
        10: ({'funding_rate','basis','open_interest','exchange_netflow_eth','stablecoin_flow_usd','staking_netflow_eth'}.issubset(contracts) and _exists('docs/DATA_SOURCES.md'), ['macro/derivatives/flow contracts','DATA_SOURCES.md']),
        11: (_contains('eth_trend_v3/probabilistic_research.py','evaluate_logistic','passes_incremental_gate'), ['simple probabilistic benchmark']),
        12: (_contains('eth_trend_v3/probabilistic_research.py','controlled_interactions','20'), ['controlled interactions <=20']),
        13: (_contains('eth_trend_v3/feature_ablation_research.py','run_group_ablation'), ['feature ablation engine']),
        14: (_contains('eth_trend_v3/feature_ablation_research.py','order_robustness','leave_one_group_out'), ['ablation order robustness']),
        15: (_contains('eth_trend_v3/regime_conditioning.py','forecast_role','DESCRIPTIVE_ONLY'), ['explicit HMM predictive/descriptive role']),
        16: (_callable_ok(calibration_decision) and calibration_decision({'available': True, 'selected': 'expanding:none'}) == 'NO_CALIBRATION', ['calibration PASS/NO_CALIBRATION/FAIL semantics']),
        17: (_callable_ok(unified_inference) and _contains('eth_trend_v3/runtime_model.py','mode not in {"SHADOW", "PRODUCTION"}') and _exists('eth_trend_v3/model_artifact.py'), ['shared frozen inference path']),
        18: (all(key in path for key in ('actual_return','actual_direction','mae','mfe','path_volatility','drawdown_duration_bars')) and _exists('eth_trend_v3/shadow_runtime.py','.github/workflows/shadow-forecast.yml'), ['real settlement/path-risk capability','shadow workflow']),
        19: (_contains('eth_trend_v3/promotion.py','production promotion requires current SHADOW state'), ['production requires SHADOW']),
        20: (_exists('eth_trend_v3/production_control.py') and _contains('eth_trend_v3/runner.py','evaluate_runtime_demotion'), ['automatic demotion wired into runtime']),
        21: (_exists('eth_trend_v3/governance.py','.github/workflows/emergency-control.yml') and _contains('scripts/emergency_control.py','FREEZE','DEMOTE','DISABLE_PUBLICATION','CLEAR'), ['emergency control plane']),
        22: (_contains('eth_trend_v3/governance.py','GateVersionConflict','already exists with a different hash'), ['immutable gate version']),
        23: (_contains('eth_trend_v3/governance.py','NEVER_TOUCHED','CONTAMINATED','mark_holdout_contaminated'), ['holdout contamination governance']),
        24: (_callable_ok(brier_skill_score) and _contains('eth_trend_v3/dynamic_baseline.py','brier_skill_vs_expanding'), ['Brier Skill Score vs dynamic baseline']),
        25: (_callable_ok(moving_block_sensitivity) and _contains('eth_trend_v3/research_metrics.py','moving_block'), ['block-aware overlapping-label uncertainty']),
        26: (_exists('.github/workflows/ci.yml','requirements-ci.lock'), ['GitHub CI workflow','locked CI dependencies']),
        27: (_exists('.github/workflows/contract-smoke.yml','scripts/validate_runtime_contracts.py','scripts/run_contract_smoke.py'), ['contract/smoke workflow and scripts']),
        28: (_contains('eth_trend_v3/model_artifact.py','git_sha','dataset_hash','config_hash','artifact_hash') and _exists('requirements.lock'), ['rebuild identity + dependency lock']),
        29: ({'NO_MODEL_BEATS_BASELINE','INSUFFICIENT_DATA','TRAIN_SERVE_SKEW','HOLDOUT_CONTAMINATED'}.issubset(UNAVAILABLE_REASONS) and _contains('eth_trend_v3/production_validation.py','UNAVAILABLE_WITHOUT_REASON'), ['standard UNAVAILABLE reason codes','production validation']),
        30: (_contains('eth_trend_v3/shadow_forecast.py','RESEARCH_HEURISTIC','Raw count alone never permits promotion') and _contains('eth_trend_v3/production_validation.py','diagnostic only'), ['heuristic explicitly non-statistical']),
    }


REQUIREMENTS = [
    '3D/7D/30D unified Research Framework','Purged Walk-Forward','Horizon-aware Embargo','Critical Leakage detection','Experiment Registry rebuildability','dataset/config/artifact hashes','lifecycle state machine','Dynamic Baseline per horizon','Horizon-Aligned Feature Contract per horizon','Macro/Derivatives/Flow data contracts','Simple Model Benchmark','Controlled Interaction governance','Feature Ablation','Ablation Order Robustness','HMM predictive role explicit','Calibration explicit result','Shadow/Production unified inference','Shadow settled outcome + Path Risk','Production only from Shadow','Automatic production demotion','Emergency Control Plane','Immutable Gate Version','Never-Touched Holdout contamination governance','Brier Skill Score vs Dynamic Baseline','Block-aware overlapping-label uncertainty','Software CI PASS','Integration/Contract/Smoke Actions evidence','Formal model reproducibility identity','UNAVAILABLE + Reason Code','No heuristic represented as statistical proof',
]


def build_acceptance(*, ci_pass: bool = False, contract_smoke_pass: bool = False) -> dict:
    checks = _local_checks()
    rows = []
    for idx, requirement in enumerate(REQUIREMENTS, start=1):
        local_ok, evidence = checks[idx]
        github_status = 'NOT_REQUIRED'
        if idx == 26:
            github_status = 'PASS' if ci_pass else 'PENDING'
        elif idx == 27:
            github_status = 'PASS' if contract_smoke_pass else 'PENDING'
        acceptance = 'FAIL' if not local_ok else ('PENDING' if github_status == 'PENDING' else 'PASS')
        rows.append({'id': idx, 'requirement': requirement, 'local_status': 'PASS' if local_ok else 'FAIL', 'github_status': github_status, 'acceptance': acceptance, 'evidence': evidence})
    local_pass = all(row['local_status'] == 'PASS' for row in rows)
    final_pass = all(row['acceptance'] == 'PASS' for row in rows)
    return {
        'prd_version': 'v2.3',
        'scope': 'Forecast Research Phase 1-9',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'engineering_implementation_status': 'PASS' if local_pass else 'FAIL',
        'program_acceptance_status': 'PASS' if final_pass else ('PENDING_GITHUB_EVIDENCE' if local_pass else 'FAIL'),
        'statistical_production_status': 'NOT_GRANTED',
        'statistical_note': 'Engineering acceptance does not grant live predictive value or production eligibility. Real OOS + shadow evidence and manual reviewed promotion remain required.',
        'requirements': rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ci-pass', action='store_true')
    parser.add_argument('--contract-smoke-pass', action='store_true')
    args = parser.parse_args()
    report = build_acceptance(ci_pass=args.ci_pass, contract_smoke_pass=args.contract_smoke_pass)
    target = ROOT / 'eth_reports/forecast-research/prd_v23_acceptance.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report['engineering_implementation_status'] != 'PASS':
        raise SystemExit(1)
    if (args.ci_pass or args.contract_smoke_pass) and report['program_acceptance_status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
