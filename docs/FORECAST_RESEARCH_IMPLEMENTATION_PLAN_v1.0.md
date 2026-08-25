# ETH Phase Meter — Forecast Research Implementation Plan v1.0

- **Based on PRD**: `eth-phase-meter_forecast-research-prd_v2.3.md`
- **Repository**: `stanleyrprose/eth-phase-meter`
- **Plan Type**: GitHub Milestone / Issue / PR Execution Plan
- **Status**: Ready for Implementation
- **Scope**: PRD Phase 1–9
- **Out of Scope**: Phase 10 Adaptive Model Management / Decision Layer
- **Primary Constraint**:
  - GitHub Repository = Source of Truth
  - GitHub Actions = Reference Orchestration + Validation Evidence
  - No direct development on `main`
  - No statistical gate may be weakened to make a model pass

---

# 1. Implementation Philosophy

This plan converts the PRD into an executable engineering sequence.

Every major unit follows:

```text
Requirement
↓
Issue
↓
Feature Branch
↓
Implementation
↓
Tests
↓
Pull Request
↓
CI PASS
↓
Merge main
↓
Reference GitHub Actions Run
↓
Evidence Artifact / Registry Record
↓
Milestone Gate
```

A PR is not considered complete merely because code compiles.

For research-related work:

```text
Software PASS
≠
Statistical PASS
```

Both must be reported independently.

---

# 2. Global Branch / PR Policy

## Branch naming

Recommended:

```text
feat/research-foundation-*
feat/dynamic-baseline-*
feat/horizon-features-*
feat/simple-models-*
feat/feature-ablation-*
feat/hmm-conditioning-*
feat/calibration-*
feat/shadow-forecast-*
feat/production-promotion-*

fix/*
test/*
docs/*
```

## PR requirements

Every PR must contain:

- Scope
- PRD requirement references
- Files changed
- New tests
- Risks
- Rollback path
- Acceptance evidence

## Merge gate

Required:

```text
Unit Tests PASS
Integration Tests PASS (where applicable)
No critical secret scan finding
No known leakage regression
No invalid schema migration
```

Research PRs additionally require:

```text
Reference workflow completes successfully
Experiment artifact generated
Experiment Registry entry generated
```

---

# 3. Milestone Overview

| Milestone | PRD Phase | Core Goal | Approx. PR Count |
|---|---:|---|---:|
| M1 Research Foundation | 1 | Correct validation + reproducibility | 6–8 |
| M2 Dynamic Baseline | 2 | Establish hard-to-beat baseline | 3–4 |
| M3 Horizon Features | 3 | Build PIT-safe horizon-aligned features | 4–6 |
| M4 Simple Models | 4 | Test simple probabilistic models | 3–4 |
| M5 Ablation | 5 | Prove incremental feature value | 3–5 |
| M6 HMM Conditioning | 6 | Establish predictive or descriptive role | 3–4 |
| M7 Calibration | 7 | Validate calibration only if eligible | 3–4 |
| M8 Shadow | 8 | Real future OOS evidence | 4–6 |
| M9 Production Promotion | 9 | Safe promotion / degradation | 5–7 |

Recommended total:

```text
34–48 PRs
```

Do not artificially combine unrelated work into giant PRs.

---

# 4. Milestone 1 — Forecast Research Foundation

## Goal

Build the research validity foundation before any new forecast model development.

## Dependencies

None.

## M1-I01 — Standard Research Sample Contract

### Scope

Define a normalized research sample containing:

```text
feature_time
available_at
label_start_time
label_end_time
horizon
feature_snapshot_id
dataset_version
```

### Acceptance

- Schema explicitly defined
- Closed-bar semantics documented
- Invalid timing rejected
- Unit tests for boundary cases

### Done Evidence

```text
test_sample_contract PASS
```

---

## M1-I02 — Purged Walk-Forward Splitter

### Scope

Implement reusable purged walk-forward validation.

Rule:

```text
train.label_end_time < test_start
```

### Required tests

- safe sample retained
- crossing sample purged
- equality boundary purged
- 3D / 7D / 30D behavior
- no test labels inside train

### Report

Per fold:

```text
train_before
purged_count
purged_ratio
train_after
```

### Gate

Any known crossing label:

```text
INVALID
```

---

## M1-I03 — Horizon-Aware Embargo

### Scope

Separate Embargo from Purge.

Support:

```text
0.5H
1.0H
1.5H
```

### Required test

Prove that changing embargo does not alter purge semantics.

### Acceptance

Embargo config stored in Experiment Registry.

---

## M1-I04 — Experiment Registry v1

### Required fields

At minimum:

```text
experiment_id
git_sha
workflow_version
dataset_version
dataset_hash
feature_version
label_version
horizon
validation_method
purge_config
embargo_config
model_type
model_config
random_seed
gate_version
candidate_count
metrics
status
created_at
```

### Database requirements

- Critical promotion fields enforce non-null / equivalent validation
- schema version tracked
- migration managed

### Evidence

Insert + read-back integration test.

---

## M1-I05 — Model Lifecycle State Machine

### States

```text
EXPERIMENTAL
CANDIDATE
SHADOW
PRODUCTION
DEGRADED
RETIRED
DESCRIPTIVE_PRODUCTION
```

### Required invalid transition test

```text
EXPERIMENTAL → PRODUCTION
```

must fail.

### Transition Log

Record:

```text
from_state
to_state
reason
trigger
operator_or_system
timestamp
gate_version
```

---

## M1-I06 — Research Run Manifest

Every research workflow emits:

```text
run_id
git_sha
workflow
python_version
dependency_hash
dataset_hash
experiment_ids
started_at
completed_at
result
artifacts
```

---

## M1-I07 — Leakage Guard Test Suite

Tests:

- scaler fit only on train
- baseline fit only on train
- calibration split isolation
- future interpolation prohibited
- HMM future posterior prohibited
- current partial candle prohibited

Leakage failure:

```text
EXPERIMENT INVALID
```

not ordinary FAIL.

---

## M1-I08 — Research Foundation GitHub Action

New reference workflow:

```text
Forecast Research Foundation Validation
```

Runs:

```text
unit tests
integration tests
split validation
registry validation
manifest generation
artifact upload
```

## M1 Gate

Milestone passes only when:

```text
Purged splitter PASS
Embargo PASS
Registry PASS
Lifecycle PASS
Leakage guard PASS
Reference Actions run PASS
```

---

# 5. Milestone 2 — Dynamic Baseline Benchmark v2

## Goal

Establish one robust baseline champion per horizon.

## Dependency

M1 PASS.

## M2-I01 — Baseline Candidate Engine

Candidates:

```text
Expanding
Rolling 90D
Rolling 180D
Rolling 365D
EWMA half-life 30D
EWMA 60D
EWMA 90D
EWMA 180D
```

All fit train-only.

---

## M2-I02 — Regime Baseline Candidates

Research candidates:

```text
Hard Regime Conditional
Shrunk Regime Conditional
```

Low regime N:

```text
fallback → global baseline
```

Do not assume HMM predictive value yet.

---

## M2-I03 — Baseline Evaluation Metrics

Required:

```text
Brier
Brier Skill Score
Log Loss
Calibration Error
Fold metrics
Moving-block CI
Block sensitivity
Effective-sample diagnostic
```

## Brier Skill Score

```text
BSS = 1 - BS_model / BS_reference
```

---

## M2-I04 — Baseline Champion Selection

Selection considers:

```text
mean performance
uncertainty
fold stability
complexity
```

Tie:

```text
prefer simpler
```

Must not choose champion on tiny point estimate differences.

## M2 Gate

Output for each horizon:

```text
BASELINE_CHAMPION
RUNNER_UP
SELECTION_EVIDENCE
experiment_id
```

---

# 6. Milestone 3 — Horizon-Aligned Feature Benchmark

## Goal

Build PIT-safe feature families aligned with 3D / 7D / 30D horizons.

## Dependency

M2 PASS.

## M3-I01 — Feature Metadata Registry

Every feature defines:

```text
feature_name
feature_version
source
formula
lookback
timestamp_semantics
event_time
retrieval_time
available_at
source_delay
missing_policy
information_cluster
horizon_relevance
```

---

## M3-I02 — Price / Trend / Volatility Features

3D / 7D / 30D specific windows per PRD.

Must use closed data only.

---

## M3-I03 — Macro Context Contract

Candidate sources/features:

```text
DXY
US10Y
US2Y
SPX
Nasdaq
BTC
ETH/BTC relative strength
rolling correlations
```

Before enabling any macro feature:

- Source availability contract
- Event time vs retrieval time
- Revision behavior
- freshness threshold

must be documented.

---

## M3-I04 — Derivatives / Flow / Structural Schema

Prepare compatible feature contracts for:

```text
funding
basis
OI
taker/CVD
exchange flow
stablecoin flow
staking
valuation proxies
```

This issue does not require every source to be immediately production-ready.

---

## M3-I05 — Missingness / Data Health Feature Gate

Required report:

```text
missing rate
freshness
source status
feature availability
```

Silent zero-fill prohibited.

---

## M3-I06 — Correlation / Information Cluster Audit

Report:

- feature correlation
- clusters
- derived duplicates

Default review trigger:

```text
|r| > 0.8
```

## M3 Gate

Each horizon must have:

```text
FEATURE_CANDIDATE_SET
FEATURE_METADATA
MISSINGNESS_REPORT
TIMESTAMP_AUDIT
CORRELATION_CLUSTER_REPORT
```

---

# 7. Milestone 4 — Simple Probabilistic Model Benchmark

## Goal

Determine whether horizon-aligned features actually beat dynamic baselines.

## Dependency

M3 PASS.

## M4-I01 — Logistic Baseline Model

Models:

```text
Dynamic Baseline Champion
Logistic
Regularized Logistic
```

Preprocessing fit train-only.

---

## M4-I02 — Controlled Interaction Logistic

Maximum research budget:

```text
<= 20 interactions
```

Candidate examples:

```text
volatility × trend
funding × OI
macro × crypto trend
regime × trend
```

Interaction selection must be registered.

---

## M4-I03 — Hyperparameter Governance

MVP preference:

```text
fixed conservative parameters
```

If tuning:

```text
nested train-only selection
```

Full-dataset GridSearch forbidden.

---

## M4-I04 — Go / No-Go Report

For each horizon:

```text
GO
```

only if simple model provides credible incremental evidence.

Otherwise:

```text
FEATURE_SET_HAS_NO_PROVEN_INCREMENTAL_VALUE
```

Do not automatically escalate to complex models.

## M4 Gate

At least one of:

```text
GO_TO_ABLATION
RETURN_TO_FEATURE_RESEARCH
NO_MODEL_ELIGIBLE
```

must be explicitly recorded.

---

# 8. Milestone 5 — Feature Ablation Ladder

## Goal

Prove which information groups add real OOS value.

## Dependency

M4 GO.

## M5-I01 — Sequential Ablation

Ladder:

```text
Dynamic Baseline
+ Price/Trend
+ Volatility
+ Volume
+ Derivatives
+ Macro
+ Capital Flow
+ Structural Supply
+ Valuation
+ Regime
```

---

## M5-I02 — Leave-One-Group-Out

Required for final survivor candidate.

Answers:

```text
What happens if group X is removed?
```

---

## M5-I03 — Order Robustness

For important groups:

- selected reverse ordering
- group permutation
- pairwise interaction test when theoretically justified

Avoid claiming attribution from one arbitrary order.

---

## M5-I04 — Interpretation Report

May use:

- coefficient stability
- SHAP for interpretation only

SHAP must not be used as statistical evidence of incremental value.

## M5 Gate

Output per horizon:

```text
FEATURE_SURVIVOR_SET
REJECTED_FEATURE_SET
REJECTION_REASON
ORDER_ROBUSTNESS
```

---

# 9. Milestone 6 — HMM Regime Conditioning

## Goal

Decide whether HMM should influence Forecast or remain descriptive only.

## Dependency

M5.

## M6-I01 — Causal HMM API Guard

Forecast-facing API exposes only causal filtering.

Regression test:

Changing future observations must not change past posterior.

---

## M6-I02 — State Alignment

Every refit:

- derive state profiles
- align labels
- compare semantic drift

Pure label permutation must not cause false transition drift.

---

## M6-I03 — Regime Forecast Comparison

Compare:

```text
No Regime
Hard Regime Rate
Shrunk Regime Rate
Soft Posterior K-1
```

---

## M6-I04 — Regime Latency / Distribution Diagnostics

Report:

```text
detection latency
occupancy
duration
mean
volatility
skew
kurtosis
```

Gaussian HMM alternatives remain future research unless current method demonstrably fails.

## M6 Gate

One of:

```text
HMM_FORECAST_INCREMENTAL_VALUE_CONFIRMED
HMM_DESCRIPTIVE_ONLY
HMM_INVALID
```

---

# 10. Milestone 7 — Calibration Research

## Goal

Only calibrate models that already beat baseline.

## Dependency

Eligible raw model from M4–M6.

## M7-I01 — Calibration Eligibility Gate

If raw model fails baseline:

```text
CALIBRATION_NOT_ELIGIBLE
```

---

## M7-I02 — Calibration Methods

Compare:

```text
No Calibration
Platt
Isotonic
Beta (optional)
```

---

## M7-I03 — Sample Sufficiency

Report:

```text
raw calibration N
effective evidence
class balance
probability coverage
```

Insufficient evidence:

```text
NO_CALIBRATION
```

---

## M7-I04 — Calibration Stability

Compare:

```text
expanding
rolling
recency-weighted
```

without using final test for selection.

## M7 Gate

Output:

```text
CALIBRATION_CHAMPION
NO_CALIBRATION
CALIBRATION_FAILED
```

---

# 11. Milestone 8 — Shadow Forecast

## Goal

Collect real future OOS evidence using production-equivalent inference.

## Dependency

CANDIDATE model.

## M8-I01 — Unified Inference Pipeline

One inference function / pipeline.

Modes:

```text
SHADOW
PRODUCTION
```

Same:

- data
- features
- preprocessing
- model artifact

Train/serve skew is a Hard Failure.

---

## M8-I02 — Shadow Forecast Persistence

Record:

```text
forecast_id
experiment_id
model_version
artifact_hash
git_sha
forecast_time
horizon
probability
baseline_probability
market_state
regime
data_health
feature_snapshot_id
settlement_time
settled
```

---

## M8-I03 — Forecast Settlement

When horizon matures, add:

```text
actual_return
actual_direction
brier
log_loss
MAE
MFE
path_volatility
drawdown_duration
```

---

## M8-I04 — Shadow Metrics

Report:

```text
live Brier
live BSS
live Log Loss
live calibration
settled forecasts
effective settled evidence
regime coverage
data-health segmentation
```

---

## M8-I05 — Shadow Evidence Gate

Initial heuristic planning values:

```text
3D  >= 50 settled
7D  >= 30 settled
30D >= 15 settled
```

But raw count alone never permits promotion.

Must also consider:

- overlap
- temporal span
- regime coverage
- data health

---

## M8-I06 — Path Risk Profile

Outputs:

```text
MAE
MFE
path volatility
drawdown duration
```

Do not call this statistical confidence.

## M8 Gate

One of:

```text
SHADOW_CONTINUE
PROMOTION_ELIGIBLE
DEMOTE_TO_CANDIDATE
RESEARCH_INVALIDATED
```

---

# 12. Milestone 9 — Production Promotion

## Goal

Safely expose only qualified probabilities.

## Dependency

M8 PROMOTION_ELIGIBLE.

## M9-I01 — Versioned Promotion Gate

Every promotion decision stores:

```text
gate_version
thresholds
experiment_id
model_version
artifact_hash
```

Changing heuristic thresholds creates new Gate version.

---

## M9-I02 — Hard Gate Enforcement

Must block promotion if any:

```text
leakage
registry incomplete
PIT invalid
artifact mismatch
train/serve skew
shadow incomplete
data health critical
emergency freeze
```

---

## M9-I03 — Production Output Semantics

Qualified:

```text
3D P(up): 57%
Baseline: 52%
Status: PRODUCTION
Reliability: Medium
Data Health: NORMAL
```

Not qualified:

```text
Forecast: UNAVAILABLE
Reason: ...
```

---

## M9-I04 — Automatic Degradation

Possible triggers:

```text
rolling Brier below baseline
BSS < threshold
calibration drift
data health CRITICAL
feature unavailable
source contract failure
artifact mismatch
```

All thresholds versioned.

---

## M9-I05 — Emergency Control Plane

Human actions allowed:

```text
freeze
demote
disable publication
annotate abnormal period
```

Forbidden:

```text
manual promotion
```

---

## M9-I06 — Reliability Engine

Reliability derived reproducibly from:

```text
Research OOS
Shadow/live OOS
Calibration
Data Health
Drift
```

No manual uplift.

---

## M9-I07 — Production Validation Workflow

After production run verify:

```text
latest record exists
timestamp fresh
model artifact matches
probability valid
baseline available
data health valid
notification status
```

## M9 Gate

Production enabled only if all Hard Gates pass.

---

# 13. Cross-Milestone Engineering Issues

These can be scheduled alongside M1–M9.

## X-I01 — Database Migration Management

Adopt:

```text
Alembic or equivalent
```

Need:

- schema_version
- upgrade
- rollback awareness

---

## X-I02 — Dependency Lock

Require:

```text
fully pinned environment / lockfile
dependency_hash
```

---

## X-I03 — Secret Scanning

CI:

- GitHub secret scanning and/or dedicated scanner
- log masking
- artifact secret audit

---

## X-I04 — Contract Test Workflow

Daily / manual:

```text
Deribit
Dune
Macro provider
PostgreSQL
```

---

## X-I05 — Smoke Test Workflow

Real pipeline without unnecessary notification side-effects.

---

# 14. Proposed GitHub Actions Layout

```text
.github/workflows/

ci.yml
research-foundation.yml
dynamic-baseline.yml
horizon-feature-benchmark.yml
simple-model-benchmark.yml
feature-ablation.yml
hmm-regime-research.yml
calibration-research.yml
shadow-forecast.yml
forecast-settlement.yml
production-monitor.yml
production-validation.yml
contract-tests.yml
smoke-test.yml
```

Avoid giant all-in-one workflows.

---

# 15. Recommended Implementation Order

Exact sequence:

```text
PR 1  Research sample contract
PR 2  Purged splitter
PR 3  Embargo
PR 4  Experiment Registry
PR 5  Lifecycle state machine
PR 6  Leakage guard suite
PR 7  Foundation Actions workflow

→ M1 Gate

PR 8  Baseline candidates
PR 9  Regime baseline
PR 10 Baseline statistics
PR 11 Baseline champion workflow

→ M2 Gate

PR 12 Feature metadata
PR 13 Horizon price/trend features
PR 14 Macro contract
PR 15 Derivatives/flow schema
PR 16 Missingness/data-health integration
PR 17 Correlation cluster audit

→ M3 Gate

PR 18 Logistic benchmark
PR 19 Regularized logistic governance
PR 20 Controlled interactions
PR 21 Model benchmark workflow

→ M4 Gate

PR 22 Ablation engine
PR 23 Leave-one-group-out
PR 24 Order robustness
PR 25 Ablation report/workflow

→ M5 Gate

PR 26 Causal HMM guard
PR 27 State alignment
PR 28 Regime comparison
PR 29 HMM diagnostics

→ M6 Gate

PR 30 Calibration eligibility
PR 31 Calibration candidates
PR 32 Calibration stability
PR 33 Calibration workflow

→ M7 Gate

PR 34 Unified inference
PR 35 Shadow persistence
PR 36 Settlement engine
PR 37 Shadow metrics
PR 38 Path risk profile
PR 39 Shadow workflow

→ M8 Gate

PR 40 Promotion gate
PR 41 Automatic demotion
PR 42 Emergency control
PR 43 Reliability engine
PR 44 Production validation
PR 45 Production output integration

→ M9 Gate
```

Actual PR count may change after code audit, but order should remain dependency-driven.

---

# 16. Stop / Replan Rules

Stop current implementation and re-plan if:

```text
Critical leakage found
Dataset semantics invalid
Train/serve skew found
Baseline validation framework invalid
Database schema migration unsafe
Current main behavior contradicts PRD assumptions
```

Do not patch around these issues merely to continue downstream phases.

---

# 17. Evidence Required at Every Milestone

Every milestone completion report must contain:

```text
Git SHA
PR list
CI status
reference workflow
experiment IDs
artifacts
database migration version
tests added
known limitations
statistical result
milestone gate result
```

---

# 18. Final Program Done Definition

The Phase 1–9 implementation program is complete when:

1. M1–M9 Hard Gates are implemented.
2. Every research run is reproducible.
3. Every forecast horizon has a valid Dynamic Baseline.
4. Feature sets are PIT-safe and horizon-aligned.
5. Feature incremental value is tested, not assumed.
6. HMM predictive role is explicitly accepted or rejected.
7. Calibration is used only when it improves eligible raw models.
8. Shadow uses the exact production inference path.
9. Real future outcomes are settled and audited.
10. Production promotion is versioned and reproducible.
11. Models can automatically demote.
12. Human overrides cannot promote models.
13. Invalid research cannot enter production.
14. UNAVAILABLE is a first-class output.
15. GitHub Actions contains durable execution evidence.

A valid final outcome may be:

```text
3D  → PRODUCTION
7D  → UNAVAILABLE
30D → UNAVAILABLE
```

or even:

```text
3D  → UNAVAILABLE
7D  → UNAVAILABLE
30D → UNAVAILABLE
```

provided the research system correctly demonstrates that no candidate has sufficient predictive evidence.

That is not a failed implementation.

It is a successful refusal to fabricate predictive certainty.
