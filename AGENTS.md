# AGENTS.md — ETH Phase Meter

> Project contract for AI coding agents working in `stanleyrprose/eth-phase-meter`.
> This repository is a production/research monitoring system. Engineering correctness and statistical evidence must remain separate.

## 1. Project Identity

ETH Phase Meter is an automated ETH / crypto market-state and forecasting system.

The project includes:

- legacy multidimensional ETH phase scoring;
- modular `eth_trend_v3` research/forecasting engine;
- PIT data capture and persistence;
- data-health gates;
- 3D / 7D / 30D forecast research;
- HMM regime research;
- calibration, ablation, drift, shadow forecasts, promotion gates;
- GitHub Actions scheduled execution and validation;
- artifact/report generation and Telegram delivery.

Repository:

```text
stanleyrprose/eth-phase-meter
```

GitHub is the source of truth for:

- code
- configuration templates
- tests
- workflows
- implementation evidence
- review history

GitHub Actions is the reference execution/verification environment.

## 2. Authority Order

When instructions conflict, use:

1. Platform/system safety rules.
2. User's latest explicit instruction.
3. Current approved PRD / implementation plan for the requested milestone.
4. `docs/PRD_IMPLEMENTATION_STATUS.md` and other current implementation-status evidence.
5. Relevant GitHub Actions workflow contract.
6. `docs/V3_ARCHITECTURE.md`, data-source and research docs.
7. README / legacy documentation.

Never let old README descriptions override the newer modular research implementation.

## 3. Current Forecast Research Production-Closure Context

As a current-state checkpoint, verify GitHub before acting.

The production-closure line has been developed on:

```text
fix/forecast-production-closure
```

A current milestone-completion commit is:

```text
402e7e7f199181b438045136cc3649fd36099370
```

That line completed remaining M1–M9 implementation-plan gaps including:

- moving-block sensitivity;
- paired regime-vs-no-regime OOS validation;
- calibration stability;
- shadow settlement/evidence;
- versioned promotion gates;
- fail-closed production publication behavior;
- M1–M9 implementation evidence workflow.

Do not assume this snapshot is still HEAD. Always inspect the remote branch, PR, Actions, and `main` before continuing.

## 4. Research Truth vs Production Truth

This project must distinguish:

### Engineering implemented

A feature exists and tests pass.

### Statistically validated

Enough real historical/PIT evidence exists and the defined empirical gate passes.

### Production-eligible

The candidate satisfies all promotion, data-health, calibration, and governance gates.

### Production-active

The candidate was manually reviewed/approved and is actually selected by the production path.

Never collapse these four states.

Do not claim predictive quality merely because code executes.

## 5. Non-Negotiable Statistical Invariants

The following must remain fail-closed unless empirical evidence supports promotion:

- calibrated 3D/7D/30D probabilities before sufficient PIT observations;
- HMM contribution before paired OOS/ablation evidence demonstrates incremental value;
- ETH-native valuation/flow/structural dimensions when required providers are unavailable;
- self-developed ETH cost-basis/SOPR-like proxy before benchmark validation;
- model promotion before statistical gates and human review.

When evidence is insufficient, outputs should remain explicitly:

- `UNAVAILABLE`
- `GATED`
- degraded/descriptive
- or otherwise clearly marked non-production

Never manufacture confidence, probability, reliability, or source availability.

## 6. Autonomous Engineering Mode

When the user says:

- `直接做`
- `继续`
- `按你的建议`
- `按 /goal 执行到底`
- `一次执行到底`
- `Autonomous Mode`

and scope is authorized:

```text
recover GitHub state
→ inspect branch/PR/Actions
→ inspect implementation status
→ implement smallest coherent change
→ minimal sufficient test
→ commit
→ push
→ GitHub Actions
→ fix CI if caused by this change
→ verify evidence/artifacts
→ update handoff/status
→ DONE or HARD STOP
```

Do not stop for ordinary reversible implementation decisions.

## 7. Mandatory Recovery Before Editing

Before any change:

1. Inspect `main`.
2. Inspect the requested/current feature or fix branch.
3. Inspect latest commits and remote divergence.
4. Inspect open PR status if one exists.
5. Inspect relevant GitHub Actions runs.
6. Read the current PRD/implementation-status document.
7. Identify the exact incomplete milestone/gate.
8. Continue from the latest valid checkpoint.

Do not start from an old local clone if GitHub has newer work.

Do not ask the user to re-explain state that is recoverable from GitHub.

## 8. Repository Areas

Key areas include:

```text
eth_phase_meter.py
github_actions_runner.py
actions_*.py
v3_actions_entrypoint.py

eth_trend_v3/
  collectors.py
  data_health.py
  dataset.py
  dynamic_baseline.py
  horizon_features.py
  feature_ablation_research.py
  regime_conditioning.py
  calibration_research_v2.py
  shadow_forecast.py
  promotion.py
  runner.py
  persistence.py
  pit.py
  model_lifecycle.py
  ...

migrations/
scripts/
tests/
.github/workflows/
docs/
eth_reports/
```

Prefer modular `eth_trend_v3` code for new forecast/research behavior unless the PRD explicitly requires a legacy path change.

Do not perform opportunistic large refactors of the legacy monolith while implementing research milestones.

## 9. Data and PIT Invariants

PIT (point-in-time) integrity is foundational.

Preserve:

- source timestamps;
- observation timestamps;
- raw payload hashes where defined;
- version identifiers;
- Git SHA/workflow run traceability;
- no future leakage;
- time-respecting train/calibration/test splits;
- reproducible implementation evidence.

Do not use future information in feature construction, normalization, regime labeling, calibration, or evaluation.

A test or backtest that leaks future data is invalid even if metrics improve.

## 10. Persistence

External PostgreSQL persistence is preferred where configured.

Artifact-only persistence is an explicitly degraded mode, not equivalent durability.

Rules:

- preserve backward compatibility of stored records unless a migration explicitly changes it;
- use migration files for schema changes;
- do not silently drop historical PIT/shadow evidence;
- do not rewrite historical observations to make later models appear cleaner;
- migrations must be reviewable and recoverable.

## 11. Data Sources and Failure Behavior

External data can be missing, stale, rate-limited, or semantically inconsistent.

Each source/feature should preserve:

- availability status;
- stale status;
- coverage;
- normalized errors;
- provenance;
- explicit fallback/degraded semantics.

Never silently substitute a different metric/provider when the semantics differ.

A fallback is allowed only when already defined by the product/data-source contract and clearly represented in output/evidence.

## 12. Testing Policy — Minimal Sufficient Testing

Use **Minimal Sufficient Testing**.

For each change, test only the paths materially affected.

### Priorities

1. changed forecasting/research logic;
2. leakage/PIT correctness;
3. persistence/migration if touched;
4. promotion/fail-closed behavior;
5. directly affected Actions entrypoint/workflow;
6. one minimal regression test for a real bug.

Do not run every boundary case merely for coverage.

Do not add many speculative tests for unchanged components.

### Targeted examples

For forecast research M1–M9 work, relevant tests may include:

```bash
python -m pytest -q \
  tests/test_research_foundation.py \
  tests/test_forecast_research_m2_m9.py \
  tests/test_forecast_research_completion.py
```

Use an even smaller subset when only one module/test path changed.

For a real bug fix:

```text
stable reproduction
→ fix
→ one minimal regression test
```

### Full CI

The general `CI` workflow intentionally performs a broader gate including:

- compile check;
- full test suite;
- backtest smoke;
- model validation smoke;
- hard-coded secret sanity check.

Do not duplicate the full CI locally unless necessary. Let GitHub Actions be the broad integration gate after targeted local verification.

## 13. GitHub Actions

Important workflows include:

- `ci.yml`
- `scheduled-monitor.yml`
- `backtest.yml`
- `model-validation.yml`
- `research-foundation.yml`
- `forecast-research-m2-m9.yml`
- `forecast-research-completion.yml`
- `baseline-benchmark.yml`
- HMM bootstrap/ablation workflows

The production scheduled monitor runs every four hours via:

```text
15 */4 * * *
```

It uses repository Secrets for credentials/data providers and uploads run artifacts.

Never commit secret values into workflow YAML, examples, tests, docs, logs, or reports.

### Forecast Research Completion gate

The dedicated completion workflow is an evidence gate for M1–M9 and generates:

```text
eth_reports/forecast-research/implementation_evidence.json
```

Do not mark the implementation plan complete if this required evidence gate fails.

## 14. Secrets

Never commit or expose:

- `TG_BOT_TOKEN`
- `TG_CHAT_ID`
- `DATABASE_URL`
- `DUNE_API_KEY`
- `FRED_API_KEY`
- `FINNHUB_API_KEY`
- `CRYPTOPANIC_API_KEY`
- `ETHERSCAN_API_KEY`
- ETH valuation/flow/structural provider tokens
- any future private API credential

Use GitHub Actions Secrets / environment variables.

Test fixtures must use synthetic values.

## 15. Model Promotion and Governance

Candidate promotion must remain conservative.

Rules:

- passing an offline metric gate does not automatically activate a model;
- candidate promotion is manual through PR/review;
- keep versioned promotion/demotion evidence;
- preserve rollback to the previous production candidate;
- fail closed if required evidence is missing;
- do not let scheduled workflows autonomously rewrite production selection unless the PRD explicitly changes this governance model.

A model that is statistically interesting but not production-eligible should remain research/shadow only.

## 16. HMM / Regime Rules

HMM complexity is optional, not sacred.

HMM should remain excluded from production prediction unless incremental OOS value is demonstrated according to the approved paired comparison/ablation gates.

Do not tune the validation rules after observing the desired result.

If HMM fails the gate, prefer the simpler baseline rather than weakening the gate.

## 17. Calibration Rules

Calibration must respect time.

Do not fit calibration using future evaluation observations.

Track stability, not just one aggregate score.

If calibration is unstable or evidence is insufficient:

- retain raw/uncalibrated research output where appropriate;
- mark calibrated production probability as gated/unavailable;
- do not force a calibrated number.

## 18. Shadow Forecast Rules

Shadow forecasts exist to accumulate unbiased forward evidence.

Preserve:

- prediction timestamp;
- horizon;
- frozen model/version;
- frozen feature/input evidence;
- settlement logic;
- outcome timestamp/value;
- evaluation evidence.

Never retroactively edit a shadow forecast after observing the outcome except through an auditable correction path.

## 19. Git Rules

Default workflow:

```text
main
→ feature/fix/research branch
→ implementation
→ targeted tests
→ commit
→ push
→ GitHub Actions
→ PR/review
→ merge/integration
```

Rules:

- do not directly develop on `main`;
- keep commits atomic and scoped;
- do not modify unrelated files;
- do not rewrite shared history;
- do not force-push without explicit authorization;
- preserve evidence artifacts/workflow definitions needed for reproducibility;
- update implementation status when a milestone materially changes.

## 20. CI Failure Handling

When GitHub Actions fails:

1. identify whether the failure is caused by the current change;
2. fix only relevant failures;
3. run the smallest local reproducer;
4. commit/push the fix;
5. re-check the required workflow.

Do not perform broad dependency upgrades or unrelated refactors merely because CI exposes an old issue.

If a failure is clearly pre-existing and unrelated, record it separately unless it blocks the authorized release.

## 21. Scheduled Production Monitor

Treat the scheduled monitor as a production path.

Changes to it require special attention to:

- secret availability;
- data-source degradation;
- PostgreSQL vs artifact-only persistence;
- duplicate/concurrent runs;
- artifact generation;
- Telegram delivery;
- fail-closed model publication;
- runtime timeout.

Do not make a research-only candidate silently become the scheduled production forecast.

## 22. Scope Discipline

If the task is limited to Forecast Research M1–M9 production closure:

- do not redesign the legacy phase scoring model;
- do not add unrelated dashboard features;
- do not create new provider integrations unless required for an approved gate;
- do not expand into trading execution;
- do not implement automated capital allocation/orders;
- do not weaken statistical gates to obtain a "PASS".

Future improvements may be recorded separately.

## 23. Hard Stops

Stop for human input only when:

- an irreversible/destructive data operation is required;
- a new credential/private key or permission escalation is required;
- a direct paid service/financial commitment is required;
- two authoritative requirements materially conflict;
- the current PRD/research gate is unavailable and a material requirement cannot be reconstructed safely;
- a change would alter model-governance policy beyond the approved scope;
- production historical/PIT evidence is at risk of loss or corruption;
- a PRD explicitly defines a Hard Stop.

Ordinary implementation choices are not Hard Stops.

A statistically failed gate is **not** a Hard Stop: record the failure and keep the feature gated.

## 24. Handoff / Checkpoint

After meaningful work, record enough state for another AI to continue.

Include:

- current branch;
- current HEAD;
- base/main SHA;
- PR if any;
- exact milestone/gate;
- completed work;
- next action;
- changed files;
- targeted tests/results;
- required Actions run/result;
- evidence artifacts;
- migration state;
- production/shadow/promotion state;
- rollback point;
- known risks.

GitHub state is preferred over chat memory as the operational source of truth.

## 25. Definition of Done

For ordinary code changes:

```text
requirement satisfied
+ targeted tests pass
+ no unrelated changes
+ commit
+ push
+ required Actions green
+ checkpoint/status updated
```

For Forecast Research milestone completion:

```text
implementation complete
+ PIT/leakage invariants preserved
+ relevant statistical gates honestly represented
+ completion/evidence workflow green
+ implementation evidence generated
+ no unauthorized auto-promotion
+ production path remains fail-closed where evidence is insufficient
```

For production-path changes:

```text
CI green
+ scheduled-monitor semantics verified
+ secrets remain external
+ persistence behavior verified
+ artifacts/evidence verified
+ rollback path preserved
```

Only then report `DONE`.
