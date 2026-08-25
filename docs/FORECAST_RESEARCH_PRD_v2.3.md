# ETH / 加密货币趋势监控与概率决策系统
# Forecast Research & Model Promotion PRD v2.3

- **文档状态**：Consolidated Draft for Implementation
- **版本**：v2.3
- **日期**：2026-08-24
- **范围**：Forecast Research Phase 1–9
- **未来路线**：Phase 10 仅作为 Roadmap，不属于本版本 Done Definition
- **代码仓库**：`stanleyrprose/eth-phase-meter`
- **核心架构约束**：
  - GitHub Repository = Source of Truth
  - GitHub Actions = 标准 CI / Research / Shadow / Production 编排与证据环境
  - Hosted / Self-hosted Runner 均可作为计算载体，但正式 reference run 必须由 GitHub Actions 编排并留存证据
  - 外部持久化存储 = Runtime State / PIT / Experiment Registry / Shadow Forecast 的事实来源
  - 本系统定位为**概率决策支持系统**，不是自动交易系统

---

# 0. v2.3 版本说明

v2.3 是一份**完整、自包含**的 PRD，不是对旧版本的增量补丁。

未来每一个正式 PRD 版本都必须遵循：

> **新版本必须能够独立用于实施，不要求工程人员同时阅读旧版本才能理解完整需求。**

## 0.1 继承自 v2.0

- Purged Walk-Forward
- Horizon-aware Embargo
- Dynamic Baseline
- Horizon-Aligned Features
- Simple Probabilistic Models
- Feature Ablation
- HMM Regime Conditioning
- Calibration
- Shadow Forecast
- Production Promotion
- PIT / Experiment Reproducibility
- GitHub / GitHub Actions 约束
- Fail Closed

## 0.2 继承自 v2.1

- Controlled Interaction Feature Layer
- Macro Context Feature Group
- Forecast Layer / Decision Layer 分离
- Path Risk Profile
- Emergency Control Plane
- Adaptive Model Management Roadmap

## 0.3 继承并强化自 v2.2

- Research Integrity Framework
- Data Leakage Prevention
- Multiple Testing / Data Snooping Control
- Effective Sample Awareness
- Data Contract Framework
- Experiment Governance
- Validation Safety Gate
- Production Reliability Framework
- Schema / Secrets / Dependency Safety
- Implementation Acceptance Checklist

## 0.4 v2.3 新增修正

1. **Never-Touched Holdout 污染规则**：一旦查看结果，该区间即不再是 never-touched holdout。
2. **Research Gate Versioning**：所有 heuristic gate 必须实验前固定并记录版本。
3. **Brier Skill Score**：除绝对 Brier 外，必须报告相对 Dynamic Baseline 的 Skill。
4. **Shadow Evidence 使用 Effective Settled Evidence**，而不只看原始 forecast 数量。
5. **Ablation Order Robustness**：关键 feature group 必须检查顺序依赖。
6. **SHAP 仅作为解释工具**，不得作为增量预测价值的统计证明。
7. **Emergency Override 不得晋级模型**，只能 freeze / demote / annotate。
8. **Train / Shadow / Production Inference Parity** 被提升为 Hard Gate。
9. **模型 artifact、dataset、config 均要求 hash**，提高可复现性。
10. **GitHub Actions 是标准编排环境，而非强制唯一算力来源**。

---

# 1. 文档目的

本 PRD 定义 ETH / 加密货币趋势监控与概率决策系统后续 Forecast Research Phase 1–9 的产品、统计、数据、模型、工程、治理与验收要求。

系统的核心目标不是“增加更多模型”，而是建设：

> **可证伪、可复现、可审计、可晋级、可降级、可淘汰的金融机器学习研究与生产制度。**

只有当历史 OOS 与真实 Shadow OOS 均支持某一模型对未来 3D / 7D / 30D 方向概率具有稳定增量预测价值时，系统才允许输出正式 `P(up)`。

如果没有模型符合要求：

```text
Forecast: UNAVAILABLE
```

必须同时输出标准 Reason Code，而不是生成未经验证的概率。

---

# 2. 当前背景与已知研究事实

现有系统已经具备：

- PIT 数据采集与持久化
- Market State Vector
- HMM Regime Engine
- 3D / 7D / 30D Forecast 框架
- Logistic Regression
- Calibration
- Walk-Forward
- Brier Score / Log Loss / Calibration Error
- HMM Forecast Ablation
- Forecast Baseline Benchmark
- PostgreSQL / Neon persistence
- GitHub Actions
- Telegram

现有研究已经证明或强烈提示：

1. 当前基础 Forecast 在多个 horizon 上不能稳定击败 historical base rate。
2. Platt / Isotonic 在部分 horizon 上可能明显恶化预测。
3. HMM posterior 目前没有证明具有稳定的 Forecast 增量价值。
4. 3D / 7D / 30D 标签高度重叠，普通 IID 假设不成立。
5. 24h 等短期特征直接预测 30D 存在明显 horizon mismatch。
6. Crypto 存在显著 regime shift，静态 base rate 不一定是合适 benchmark。
7. 研究结果最主要的风险不是“模型不够复杂”，而是：
   - leakage
   - data snooping
   - small effective sample
   - regime dependence
   - calibration overfit
   - train/serve skew

---

# 3. 产品目标与非目标

## 3.1 Primary Goal

建立：

```text
Raw PIT Data
    ↓
Data Contract / Availability Alignment
    ↓
Research Dataset
    ↓
Purged Walk-Forward + Embargo
    ↓
Dynamic Baseline
    ↓
Horizon-Specific Features
    ↓
Simple Probabilistic Models
    ↓
Controlled Interactions
    ↓
Feature Ablation
    ↓
Regime Conditioning
    ↓
Calibration
    ↓
Shadow Forecast
    ↓
Promotion Gate
    ↓
Production Probability
```

## 3.2 每个 Horizon 独立

3D / 7D / 30D 必须独立拥有：

- baseline
- feature set
- model
- calibration
- lifecycle status
- reliability evidence

允许最终状态为：

```text
3D  = PRODUCTION
7D  = UNAVAILABLE
30D = SHADOW
```

## 3.3 非目标

本阶段不包括：

- 自动下单
- Portfolio Optimization
- Position Sizing
- 高频交易
- 强化学习
- Transformer / LSTM
- 无约束 AutoML
- 以回测收益最大化为研究目标
- 为了让模型上线而事后修改 Gate
- 将业务风险偏好塞进 Forecast Probability Loss
- 用复杂模型掩盖无增量特征的问题

---

# 4. 核心原则

## 4.1 Probability First

Forecast 输出：

\[
P(Y_{t+H}=1 \mid I_t)
\]

其中 `I_t` 只能包含 t 时刻真实已知信息。

## 4.2 Point-in-Time

禁止：

- future price leakage
- future label leakage
- future revised macro data
- full-history scaler
- full-history feature selection
- full-history calibration
- HMM smoothing
- future interpolation

## 4.3 Baseline First

任何模型必须与对应 horizon 的 Dynamic Baseline Champion 比较。

## 4.4 Simplicity Before Complexity

```text
Dynamic Base Rate
↓
Logistic
↓
Regularized Logistic
↓
Controlled Interaction Logistic
↓
Only then consider shallow nonlinear models
```

## 4.5 Forecast ≠ Decision

Forecast Layer 回答：

> 市场上涨的条件概率是多少？

Decision Layer 回答：

> 在风险偏好与仓位约束下应该怎么行动？

本 PRD Phase 1–9 只负责 Forecast，不使用不对称业务损失扭曲概率模型。

## 4.6 Fail Closed

无可靠证据时：

```text
UNAVAILABLE
```

而不是：

```text
50%
```

---

# 5. 系统双质量轨道

系统必须同时维护两条互相独立的质量轨道：

## Track A — Software Correctness

```text
Unit
↓
Integration
↓
Contract
↓
Smoke
↓
Production Validation
```

回答：

> 软件是否按照设计运行？

## Track B — Statistical Validity

```text
PIT
↓
Purged Walk-Forward
↓
Embargo
↓
Dynamic Baseline
↓
Block Bootstrap
↓
Ablation
↓
Calibration
↓
Shadow OOS
```

回答：

> 模型是否真的有预测价值？

禁止因为 Track A 全 PASS 就宣称模型有效。

---

# 6. Research Integrity Framework

## 6.1 Critical Leakage Rule

任何 Critical Leakage：

```text
Experiment Status = INVALID
```

INVALID 与 FAIL 必须区分。

- FAIL：方法正确，但模型没预测价值。
- INVALID：验证本身不可信。

INVALID 不得参与模型比较。

## 6.2 Preprocessing Leakage

所有：

- StandardScaler
- Normalizer
- Feature Selector
- PCA / dimensionality reduction（若未来启用）
- Hyperparameter selection

必须在 train fold 内独立 fit。

## 6.3 Calibration Leakage

必须保证：

```text
Train
↓
Calibration
↓
Test
```

三部分在统计意义上隔离。

## 6.4 HMM Causality

Forecast 模块只允许使用 causal forward filtering。

禁止使用：

- future smoothing
- full-sequence posterior
- backward information

必须存在自动测试证明：

> t 时刻 posterior 不因 t+1 之后数据改变。

---

# 7. Multiple Testing / Data Snooping Governance

## 7.1 Research Discovery Budget

所有实验必须记录：

```text
candidate_count
feature_variants_tested
models_tested
hyperparameter_variants_tested
interaction_variants_tested
```

## 7.2 Never-Touched Holdout

必须预留最终真实性验证区间。

原则：

```text
Research Train
↓
Research Validation
↓
Research Test
↓
--------------------
Never-Touched Holdout
```

只有候选模型完成主要研究流程后才能首次使用。

## 7.3 Holdout 污染规则

一旦研究者查看 holdout 结果并据此：

- 改 feature
- 改 model
- 改 parameter
- 改 Gate

该 holdout 即视为：

```text
CONTAMINATED
```

必须等待新的未来数据形成新的独立 holdout。

## 7.4 Multiple Testing Correction

不得机械要求单一统计校正方法。

可报告：

- Bonferroni / Holm 等保守校正结果作为诊断
- candidate count
- repeated OOS evidence

但最终可信度主要来自：

- 预注册研究设计
- Purged OOS
- untouched holdout
- Shadow OOS
- replication

原因：

大量 feature/model 实验之间并不独立，简单 Bonferroni 可能过度保守。

---

# 8. Overlapping Labels 与 Effective Sample

4h sampling 下：

```text
3D  = 18 bars
7D  = 42 bars
30D = 180 bars
```

相邻 target 高度重叠。

## 8.1 报告要求

必须同时输出：

```text
raw_oos_n
effective_sample_diagnostic
```

Effective Sample 不是唯一精确真值，因此必须标注：

```text
DIAGNOSTIC
```

不得制造虚假精确性。

## 8.2 Moving Block Bootstrap

默认初始 block：

- 3D → 18 bars
- 7D → 42 bars
- 30D → 180 bars

必须做 sensitivity：

- 0.5H
- 1.0H
- 1.5H

如果结论只在单一 block length 成立：

```text
STABILITY_FAIL
```

---

# 9. Data Contract Framework

每一个 Feature 必须有完整 metadata：

```yaml
feature_name:
feature_version:
source:
source_version:
formula:
lookback:
timestamp_semantics:
event_time:
retrieval_time:
available_at:
source_delay:
missing_policy:
information_cluster:
expected_direction:
horizon_relevance:
```

## 9.1 Availability Rule

必须满足：

```text
feature.available_at <= forecast_time
```

标签必须开始于预测信息集之后。

## 9.2 Current Bar Semantics

任何基于 close 的 feature 只有在该 bar 正式关闭后才能视为 available。

禁止用正在形成中的 partial bar 冒充 closed bar。

## 9.3 Missing Policy

禁止 silent zero-fill。

可配置：

- drop
- forward-fill（仅在统计与业务含义允许时）
- unavailable flag
- hold last valid value

禁止未来插值。

## 9.4 Correlation / Information Cluster

必须报告 feature correlation。

默认：

```text
|r| > 0.8
```

触发 redundancy review。

每个 feature 必须可标记：

```text
information_cluster
```

例如：

```text
trend_short
trend_medium
volatility
derivatives_crowding
macro_rates
macro_risk
capital_flow
```

---

# 10. Experiment Registry

每次实验必须产生唯一 `experiment_id`。

Critical fields 至少包括：

```text
experiment_id
experiment_family
git_sha
workflow_version
schema_version
dataset_version
dataset_hash
feature_set
feature_version
label_version
horizon
validation_method
purge_config
embargo_config
model_type
model_config
model_artifact_hash
random_seed
gate_version
candidate_count
data_start
data_end
train_windows
test_windows
holdout_status
brier
brier_skill_score
log_loss
calibration_error
raw_oos_n
effective_sample_diagnostic
bootstrap_method
bootstrap_ci
fold_metrics
promotion_gate_result
model_status
created_at
```

## 10.1 Schema Enforcement

Promotion 所需 critical fields 缺失：

```text
PROMOTION_BLOCKED
```

不得依赖人工检查。

## 10.2 Dataset Hash

必须基于实际 Research Dataset 内容生成 hash。

不能只记录：

```text
dataset_v3
```

## 10.3 Model Artifact Hash

Candidate / Shadow / Production 模型必须有不可混淆的 artifact hash。

---

# 11. Model Lifecycle Governance

主生命周期：

```text
EXPERIMENTAL
↓
CANDIDATE
↓
SHADOW
↓
PRODUCTION
↓
RETIRED
```

允许：

```text
PRODUCTION → DEGRADED
DEGRADED → SHADOW
SHADOW → CANDIDATE
CANDIDATE → RETIRED
```

HMM descriptive engine 可以使用：

```text
DESCRIPTIVE_PRODUCTION
```

但不得因此获得 Forecast predictive status。

## 11.1 Illegal Transition

禁止：

```text
EXPERIMENTAL → PRODUCTION
```

## 11.2 Transition Log

每次状态变化必须记录：

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

# 12. Research Gate Governance

## 12.1 Hard Gates

不可放宽：

- no critical leakage
- PIT valid
- dataset reconstructable
- model reproducible
- probability ∈ [0,1]
- registry complete
- train/serve parity
- required Shadow completed
- unresolved CRITICAL Data Health = false

## 12.2 Research Heuristic Gates

例如：

- minimum ΔBrier
- minimum Brier Skill Score
- minimum fold win-rate
- minimum bootstrap CI
- minimum Shadow evidence
- calibration tolerance

必须：

1. 实验开始前固定；
2. 记录 `gate_version`；
3. 标记为 `RESEARCH_HEURISTIC`；
4. 变更 Gate 后必须生成新 experiment family / version。

禁止看到结果以后为上线而降低阈值。

---

# 13. Phase 1 — Forecast Research Foundation

## 13.1 目标

建立所有 Phase 共用的：

- Purged Walk-Forward
- Embargo
- Experiment Registry
- Lifecycle State Machine
- Leakage Guards
- Validation Report

## 13.2 Purged Walk-Forward

每个样本必须至少有：

```text
feature_time
available_at
label_start_time
label_end_time
horizon
```

对于 test fold：

任何训练样本若：

```text
label_end_time >= test_start
```

必须 purge。

## 13.3 Purge Test

必须有人工可验证的小型 fixture。

测试至少包含：

- boundary sample
- exact equality sample
- label crossing sample
- safe train sample

并断言最终：

```text
max(train.label_end_time) < test_start
```

在 embargo 적용后还需满足对应隔离条件。

## 13.4 Purge Report

每 fold 输出：

```text
train_before
purged_count
purged_ratio
embargo_removed_count
train_after
```

异常 purge ratio 需要告警，但不得仅凭固定 50% 自动判错；应结合 horizon 与 fold design。

## 13.5 Embargo

Purge 与 Embargo 必须逻辑分离。

- Purge：看 label 是否跨测试边界。
- Embargo：人为增加时间隔离带。

必须支持：

```text
0.5H
1.0H
1.5H
```

## 13.6 Done Definition

Phase 1 完成要求：

- reusable purged splitter
- configurable embargo
- Experiment Registry schema
- lifecycle validator
- leakage test suite
- run manifest
- CI PASS
- GitHub Actions reference run PASS

---

# 14. Phase 2 — Dynamic Baseline Benchmark v2

## 14.1 目标

为每个 horizon 找到真正难以击败、PIT-valid 的 baseline。

## 14.2 Candidate Baselines

### Expanding Historical Base Rate

\[
p_t = \frac{1}{n_t}\sum_{i \in train_t} y_i
\]

### Rolling Base Rate

候选：

- 90D
- 180D
- 365D

### EWMA Base Rate

候选 half-life：

- 30D
- 60D
- 90D
- 180D

### Regime-Conditioned Base Rate

\[
P(up \mid regime_t)
\]

### Shrunk Regime Base Rate

\[
p = \lambda p_{regime} + (1-\lambda)p_{global}
\]

λ 必须随 regime 样本量变化。

## 14.3 Baseline Leakage Guard

所有参数必须仅使用 train fold。

EWMA half-life 若通过选择获得，也必须在 train 内选择。

## 14.4 Minimum Regime Evidence

Regime 样本不足时：

```text
fallback → global / rolling baseline
```

minimum regime count 是 heuristic，必须预先配置并记录。

## 14.5 Champion Selection

不得仅以最低 mean Brier 排名。

必须同时考虑：

- Brier
- Brier Skill
- CI
- fold stability
- complexity

差异不明确时：

> 选择更简单 baseline。

## 14.6 输出

每个 horizon 输出：

```text
BASELINE_CHAMPION
BASELINE_RUNNER_UP
SELECTION_EVIDENCE
```

---

# 15. Phase 3 — Horizon-Aligned Feature Benchmark

## 15.1 目标

解决 feature memory 与 prediction horizon 不匹配。

## 15.2 3D Candidate

- return_4h
- return_24h
- return_72h
- RV_24h
- RV_72h
- volume_change_24h
- volume_change_72h
- distance_to_ma_3d
- trend_slope_3d

## 15.3 7D Candidate

- return_1d
- return_3d
- return_7d
- RV_3d
- RV_7d
- volume_change_3d
- volume_change_7d
- distance_to_ma_7d
- trend_slope_7d

## 15.4 30D Candidate

- return_3d
- return_7d
- return_14d
- return_30d
- RV_7d
- RV_14d
- RV_30d
- trend_slope_14d
- trend_slope_30d
- drawdown_30d
- distance_to_ma_30d

## 15.5 Macro Context Group

至少预留/评估：

### Dollar
- DXY return
- DXY trend
- DXY volatility

### Rates
- US10Y change
- US2Y change
- curve slope
- real-yield proxy

### Risk Assets
- SPX return
- Nasdaq return
- BTC return
- ETH/BTC relative strength

### Correlation
- ETH-BTC rolling correlation
- ETH-SPX rolling correlation
- ETH-DXY rolling correlation

宏观数据必须符合 PIT / release availability。

## 15.6 Additional Information Schema

即使 Phase 3 初期不全部启用，也必须预留 schema：

- funding
- basis
- OI
- taker/CVD
- exchange flows
- stablecoin flows
- staking
- MVRV / valuation proxy

## 15.7 Feature Benchmark 输出

每个 horizon 形成：

```text
FEATURE_CANDIDATE_SET
FEATURE_INFORMATION_CLUSTERS
FEATURE_MISSINGNESS_REPORT
FEATURE_TIMESTAMP_AUDIT
```

---

# 16. Phase 4 — Simple Probabilistic Model Benchmark

## 16.1 目标

判断 feature set 是否具有增量预测信息。

## 16.2 Candidate Models

第一层：

- Dynamic Baseline
- Logistic Regression
- Regularized Logistic

第二层：

- Controlled Interaction Logistic

只有前述模型有明确增量证据后，才允许探索：

- shallow tree
- shallow gradient boosting

## 16.3 Hyperparameter Policy

MVP 优先固定保守参数，减少搜索。

若进行超参数选择：

必须 nested within train fold。

禁止全数据 GridSearchCV。

## 16.4 Controlled Interaction Layer

只允许有限交互。

例：

- volatility × trend
- funding × OI
- macro × crypto trend
- regime × trend
- oversold × volatility

默认最大：

```text
20 interactions
```

这是工程/研究预算，不是统计常数。

## 16.5 Go / No-Go

若 Logistic 无法稳定击败 Dynamic Baseline：

```text
FEATURE_SET_HAS_NO_PROVEN_INCREMENTAL_VALUE
```

该 horizon 不得因为“不甘心”直接升级复杂模型。

---

# 17. Phase 5 — Feature Ablation Ladder

## 17.1 默认 Ladder

```text
Dynamic Baseline
↓
+ Price / Trend
↓
+ Volatility
↓
+ Volume
↓
+ Derivatives
↓
+ Macro
↓
+ Capital Flow
↓
+ Structural Supply
↓
+ Valuation
↓
+ Regime
```

## 17.2 每层指标

必须报告：

\[
\Delta Brier = Brier_{previous} - Brier_{new}
\]

以及：

- ΔBrier Skill
- ΔLogLoss
- ΔCalibration
- fold win-rate
- moving-block CI
- OOS N
- effective sample diagnostic

## 17.3 Ablation Order Robustness

固定顺序会影响归因。

对于关键信息组，至少使用：

- leave-one-group-out
- reverse / selected order permutation
- pairwise interaction check（若有理论理由）

来判断结论是否依赖于单一顺序。

## 17.4 SHAP Policy

SHAP 可以用于：

- 模型解释
- 发现可能的 interaction

但不得作为：

> “这个 feature 具有真实增量预测价值”

的统计证明。

增量价值必须由 OOS ablation 判断。

## 17.5 Feature Kill

无稳定增量：

```text
REJECTED
```

不是“理论上应该有用所以保留”。

---

# 18. Phase 6 — HMM Regime Conditioning

## 18.1 定位

HMM = Context Engine。

不默认等于 Prediction Engine。

## 18.2 比较

### Hard Regime

\[
P(up \mid z_t)
\]

### Shrunk Regime

\[
p = \lambda p_{regime}+(1-\lambda)p_{global}
\]

### Soft Posterior

使用 K-1 posterior components。

## 18.3 Causal Filtering

必须严格 causal。

## 18.4 State Alignment

每次 HMM refit 后必须对齐状态语义。

不得直接假设：

```text
state 0 = bull
```

永远成立。

状态对齐应基于：

- return
- volatility
- volume / other state features

进行确定性 mapping / permutation alignment。

## 18.5 Regime Latency

必须报告：

```text
regime_detection_latency
```

如果 HMM 对快速切换反应太慢：

结论可以是：

> 仅适合作为 slow context，不用于 3D Forecast。

## 18.6 Distribution Misspecification

Gaussian HMM 的厚尾问题需要诊断：

- skew
- kurtosis
- extreme occupancy

但 t-distribution HMM 等复杂方案仅作为 Future Research Candidate，不是 Phase 6 必做项。

## 18.7 Fail Rule

如果 Forecast 无增量：

HMM 保持：

```text
DESCRIPTIVE_PRODUCTION
```

---

# 19. Phase 7 — Calibration Research

## 19.1 前置条件

Raw model 必须先击败 Dynamic Baseline。

否则：

```text
CALIBRATION_NOT_ELIGIBLE
```

## 19.2 Candidates

- No Calibration
- Platt
- Isotonic
- Beta Calibration（可选）

## 19.3 Sample Sufficiency

Calibration 必须看：

- raw sample
- effective sample
- class balance
- probability coverage

例如“100 个非重叠样本”只能作为研究启发，不作为统一硬阈值。

如果样本不足：

```text
NO_CALIBRATION
```

## 19.4 Calibration Diagnostics

必须：

- reliability curve
- bin counts
- calibration slope
- calibration intercept
- Brier
- Log Loss

## 19.5 Failure

若 calibration 明显恶化：

选择：

```text
NO_CALIBRATION
```

而不是强行校准。

---

# 20. Phase 8 — Shadow Forecast

## 20.1 目标

验证真实未来、真实数据管道下的模型表现。

## 20.2 Train / Shadow / Production Parity

Shadow 和 Production 必须共用：

- data collector
- feature calculation
- inference function
- model artifact
- preprocessing artifact

唯一区别：

```text
SHADOW → store only
PRODUCTION → store + publish
```

这是 Hard Gate。

## 20.3 Shadow Record

必须记录：

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

结算后：

```text
actual_return
actual_direction
brier_loss
log_loss
MAE
MFE
path_volatility
drawdown_duration
```

## 20.4 Path Risk Profile

增加：

- MAE
- MFE
- path volatility
- drawdown duration

不使用“Path Confidence”命名，避免把路径特征误认为统计置信度。

建议命名：

```text
Path Risk Profile
```

## 20.5 Shadow Minimum Evidence

初始 planning heuristic：

- 3D：≥ 50 settled
- 7D：≥ 30 settled
- 30D：≥ 15 settled

但不得仅凭 raw count 晋级。

还必须考虑：

- effective settled evidence
- label overlap
- market regime coverage
- Data Health
- temporal span

上述数量必须标记：

```text
RESEARCH_HEURISTIC
```

## 20.6 Data Health Segmentation

`data_health != NORMAL` 的 Shadow forecast：

必须单独统计。

禁止与 NORMAL 样本无差别混算。

---

# 21. Phase 9 — Production Promotion

## 21.1 Promotion Hard Gates

必须全部满足：

- Research OOS valid
- no critical leakage
- PIT valid
- Dynamic Baseline comparison complete
- model reproducible
- artifact hash valid
- train/serve parity
- Shadow completed
- no CRITICAL Data Health
- no unresolved emergency freeze
- registry complete

## 21.2 Promotion Evidence

必须同时评估：

- Brier
- Brier Skill Score
- Log Loss
- Calibration
- fold stability
- block bootstrap
- Shadow OOS
- Path Risk Profile
- regime coverage

## 21.3 Brier Skill Score

相对 Dynamic Baseline：

\[
BSS = 1-\frac{BS_{model}}{BS_{baseline}}
\]

解释：

- BSS > 0：优于 baseline
- BSS = 0：与 baseline 相同
- BSS < 0：弱于 baseline

禁止只看绝对 Brier。

## 21.4 Automatic Demotion

Production 必须支持自动降级。

触发条件可包括：

- rolling Brier 持续弱于 baseline
- calibration drift
- probability collapse
- missing feature
- Data Health CRITICAL
- artifact mismatch
- source contract failure

具体 N、window、threshold 属于 versioned heuristic config。

## 21.5 Reliability

Reliability 必须可复现。

输入只能来自：

- research OOS
- Shadow / live OOS
- calibration
- data health
- model drift

禁止人工直接把：

```text
Medium → High
```

## 21.6 Emergency Override

Human Override 可以：

- freeze promotion
- demote
- disable publication
- mark abnormal period

禁止：

```text
manual override → promote model
```

Override 必须记录：

- operator
- reason
- timestamp
- action

## 21.7 User Output

Production：

```text
3D P(up): 57%
Dynamic Baseline: 52%
Status: PRODUCTION
Reliability: Medium
Data Health: NORMAL
```

No Qualified Model：

```text
3D Forecast: UNAVAILABLE
Reason: NO_MODEL_BEATS_BASELINE
```

建议固定提示：

```text
Probability decision support; not an automatic trading instruction.
```

---

# 22. Standard UNAVAILABLE / INVALID Reason Codes

至少支持：

```text
NO_MODEL_BEATS_BASELINE
INSUFFICIENT_DATA
INSUFFICIENT_EFFECTIVE_SAMPLE
CALIBRATION_FAILED
DATA_HEALTH_CRITICAL
MODEL_DEGRADED
MODEL_ARTIFACT_MISSING
FEATURE_UNAVAILABLE
SOURCE_CONTRACT_FAILED
SHADOW_INSUFFICIENT
REGISTRY_INCOMPLETE
LEAKAGE_DETECTED
TRAIN_SERVE_SKEW
HOLDOUT_CONTAMINATED
```

其中：

```text
LEAKAGE_DETECTED
```

应导致 Experiment INVALID。

---

# 23. GitHub / GitHub Actions Execution Architecture

## 23.1 Source of Truth

所有正式：

- code
- config
- gate
- schema
- workflow
- model definition

必须存在 GitHub repo。

## 23.2 Standard Flow

```text
feature branch
↓
PR
↓
CI
↓
merge main
↓
Research / Shadow / Production Workflow
↓
Evidence Artifact + Registry
```

## 23.3 Execution Profiles

### Small

Hosted runner：

- CI
- inference
- light benchmark

### Medium

Hosted / self-hosted：

- baseline
- ablation
- calibration

### Heavy

优先 self-hosted runner，但仍由 GitHub Actions 编排：

- large bootstrap
- large sensitivity runs
- future large-scale model comparison

GitHub Actions 是标准 orchestration / evidence layer，不强制 hosted runner 承担所有计算。

## 23.4 Workflow Runtime Budget

每个 research workflow 必须记录：

- elapsed time
- peak memory（若可测）
- candidate count
- bootstrap count

超出预算时：

- shard
- cache
- self-hosted runner

不得为了超时而降低统计标准。

---

# 24. Software Test Strategy

## Unit

必须覆盖：

- purge boundary
- embargo
- label timing
- scaler fold isolation
- causal HMM
- state alignment
- baseline train-only
- probability bounds
- lifecycle transition
- Gate validation
- reason code

## Integration

至少覆盖：

```text
PIT
→ Dataset
→ Split
→ Feature
→ Model
→ Registry
```

## Contract

真实检查：

- Deribit
- Dune
- macro provider（启用后）
- PostgreSQL

Contract Test 尽量 read-only。

## Smoke

真实 GitHub Actions 环境：

```text
collect
→ transform
→ infer
→ persist
→ validate
```

禁止不必要的 Telegram 副作用。

## Production Validation

检查：

- freshness
- DB record
- artifact
- model version
- probability validity
- Data Health
- source parity

---

# 25. Persistence / Schema Governance

## 25.1 Required Persistent Domains

- PIT Records
- Experiment Registry
- Model Governance
- Shadow Forecasts
- Production Forecasts
- Transition Logs
- Override Logs

## 25.2 Schema Migration

必须：

- versioned
- reviewable
- rollback-aware

推荐：

- Alembic 或等价 migration 机制

禁止生产数据库 schema 通过临时 SQL 无记录漂移。

## 25.3 Backward Compatibility

新增字段原则：

- migration 明确
- historical records 可读
- schema_version 可追踪

---

# 26. Secrets / Dependency / Reproducibility

## 26.1 Secrets

只能使用：

- GitHub Secrets
- approved environment secrets

必须：

- secret scanning
- log masking
- artifact inspection

## 26.2 Dependency Lock

必须锁定完整依赖环境。

可采用：

- pinned requirements
- lockfile
- dependency hash

Run Manifest 必须记录：

```text
python_version
dependency_hash
```

## 26.3 Reference Reproduction

定期运行 reference experiment，验证：

相同：

- Git SHA
- dataset hash
- config
- seed

能够得到容许误差内一致结果。

---

# 27. Observability

系统必须能够回答：

- 当前 3D / 7D / 30D 各是什么状态？
- 当前 Baseline 是什么？
- 当前 Production Model 是什么？
- 为什么某 horizon UNAVAILABLE？
- 当前模型 Brier / BSS / Log Loss？
- 当前 Calibration 状态？
- 最近 Shadow settled count / effective evidence？
- Data Health？
- 最近一次模型晋级/降级原因？
- Git SHA / experiment_id / artifact_hash？
- Gate Version？
- Holdout 是否已污染？

---

# 28. Phase Gate Summary

| Phase | Required Gate |
|---|---|
| 1 | Research Foundation valid; leakage guards + registry + lifecycle ready |
| 2 | Dynamic Baseline established with stable evidence |
| 3 | Horizon-aligned feature/data contracts established |
| 4 | Simple probabilistic models tested vs baseline |
| 5 | Incremental feature layers validated / rejected |
| 6 | HMM predictive role independently established or rejected |
| 7 | Calibration independently validated or explicitly rejected |
| 8 | Real Shadow evidence accumulated with train/serve parity |
| 9 | Hard Gates + Research Evidence + Shadow Evidence all passed |

后一阶段不得绕过前一阶段 Hard Gate。

---

# 29. Implementation Acceptance Contract

每一个 PRD Requirement 都必须尽可能映射为：

```text
Requirement
↓
Implementation
↓
Automated Test
↓
GitHub Actions Evidence
↓
Artifact / Registry Record
↓
Acceptance
```

不得以：

> “代码已经写了”

作为 Phase Done。

---

# 30. 风险优先级

## P0

- Data Leakage
- Purge Logic
- Causal HMM
- Train/Serve Skew
- Registry / Dataset Reproducibility

## P1

- Multiple Testing
- Overlapping Labels
- Dynamic Baseline Leakage
- Gate Manipulation
- Calibration Small Sample
- State Label Switching

## P2

- Feature Information Limits
- Macro / Alternative Source Quality
- Shadow Duration
- Runtime / Infrastructure Cost
- Dependency Drift

---

# 31. 项目最终 Done Definition — Phase 1–9

Phase 1–9 完成必须同时满足：

1. 3D / 7D / 30D 都接入统一 Research Framework。
2. Purged Walk-Forward 生效。
3. Horizon-aware Embargo 生效。
4. Critical Leakage 自动检测。
5. Experiment Registry 可重建实验。
6. dataset / config / artifact 均有 hash。
7. lifecycle 状态机生效。
8. 每 horizon 有 Dynamic Baseline。
9. 每 horizon 有 Horizon-Aligned Feature Contract。
10. Macro / Derivatives / Flow 等数据 schema 有明确接入规则。
11. Simple Model Benchmark 已完成。
12. Controlled Interaction 已被严格限制与验证。
13. Feature Ablation 已完成。
14. Ablation Order Robustness 已检查。
15. HMM predictive role 已明确 PASS 或 FAIL。
16. Calibration 已明确 PASS / NO_CALIBRATION / FAIL。
17. Shadow / Production 完全共用 inference pipeline。
18. Shadow 记录真实 settled outcome 与 Path Risk。
19. Production 只能从 Shadow 晋级。
20. Production 可自动降级。
21. Emergency Control Plane 生效。
22. Gate Version 不可事后静默修改。
23. Never-Touched Holdout 有污染管理规则。
24. Brier Skill Score 相对 Dynamic Baseline 被报告。
25. Overlapping labels 使用 block-aware uncertainty。
26. Software CI PASS。
27. Integration / Contract / Smoke 有明确运行证据。
28. 正式模型可由 Git SHA + dataset hash + config + artifact hash 重建。
29. 不合格 horizon 输出标准 `UNAVAILABLE + Reason Code`。
30. 不存在 heuristic 被包装成统计证明或 probability confidence。

如果最终没有任何 horizon 获得 PRODUCTION 资格，但所有研究流程正确执行并证明：

```text
NO_MODEL_BEATS_BASELINE
```

则研究系统本身仍可视为：

```text
SUCCESSFUL IMPLEMENTATION
```

因为系统成功完成了其最重要职责：

> 拒绝输出没有证据支持的概率。

---

# 32. Phase 10 Roadmap — Adaptive Model Management（本版本非实施范围）

未来可研究：

```text
Champion
↓
Challenger
↓
Shadow Competition
↓
Promotion
```

允许：

```text
Production Artifact
↓
Warm-start Candidate
```

但必须重新完成：

- validation
- ablation
- calibration
- shadow

Warm Start 只用于提高研究效率，不继承 Production 信任。

未来 Decision Layer 也在 Phase 10+ 另立 PRD：

- asymmetric business loss
- risk preference
- position sizing
- action policy

不得反向污染 Forecast Probability Layer。

---

# 33. 最终产品哲学

ETH Phase Meter 不追求：

> 每天必须回答“涨还是跌”。

它追求：

```text
Observe
↓
Record PIT
↓
Understand Context
↓
Estimate Dynamic Baseline
↓
Test Incremental Information
↓
Validate Without Leakage
↓
Measure Uncertainty
↓
Calibrate if justified
↓
Shadow
↓
Promote
↓
Monitor
↓
Demote when evidence disappears
```

最终系统必须知道三件事：

1. **什么时候有证据。**
2. **证据有多稳定。**
3. **什么时候应该承认不知道。**

系统最重要的输出之一不是某个概率，而是：

```text
UNAVAILABLE
```

当且仅当证据不足时，诚实地不预测。
