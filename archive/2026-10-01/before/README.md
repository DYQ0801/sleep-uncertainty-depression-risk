# 睡眠 EEG 与抑郁风险实验工程

本仓库公开研究代码、实验文档和聚合指标，用于复现“睡眠分期概率校准与不确定性特征融合的抑郁症状风险评估”实验。原始睡眠信号、临床表格、个体级预测结果和模型权重不随仓库分发。

## 数据与复现边界

- APPLES 数据需通过官方 NSRR 数据申请流程获得，并遵守其数据使用协议。
- 本仓库不包含 `data/` 下的原始数据、临床表格、压缩归档或个体级派生数据。
- `results/` 仅保留聚合实验指标 JSON；个体级预测表和受试者级特征表不公开。
- `external/` 中的第三方项目仅保留必要的源码和数据说明；原始样本、预训练权重及第三方 Git 历史不纳入本仓库。
- 运行 APPLES 脚本前，需要将获得授权的数据放置到脚本参数指定的位置。

目标是检验：在年龄、性别、BMI、中心和 OSA 严重度之外，整夜睡眠结构、转移动态和**经校准的睡眠分期后验不确定性**是否能增量预测 BDI-I。

## 当前边界

- APPLES 原始 CSV/EDF 受 NSRR 数据使用协议控制，不能匿名下载。
- L-SeqSleepNet 官方模型输出 `score` 和 `prediction`，未直接定义 `night_emb`。
- SleepTransformer 的 posterior entropy 是模型决策不确定性，不是 EEG 信号熵；它与抑郁的关系是本项目要检验的假设。
- LPSGM 已公开 APPLES 抑郁分类实现，因此仅做“预训练 PSG 模型 + 抑郁分类”不具备足够新颖性。

## 环境

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest
```

## 已可复现实验

使用 L-SeqSleepNet 仓库自带的真实 Sleep-EDF-20 整夜数据验证睡眠结构和动态特征：

```bash
.venv/bin/python scripts/extract_sleepedf_features.py
.venv/bin/pytest
```

结果写入 `results/sleepedf/`。

使用公开 Bovy et al. 2022 三个 MDD 睡眠队列运行留一数据集外部验证：

```bash
.venv/bin/python scripts/download_bovy_hypnograms.py
.venv/bin/python scripts/run_bovy_external_validation.py
```

结果写入 `results/bovy2022/`。基础分析纳入 219 晚，逐 epoch 动态完整病例为
213 晚。宏结构+动态+微结构 pooled AUROC 为 0.782（95% CI 0.721-0.841），
但未用药外部队列 AUROC 仅 0.547，且 HAMD 外部回归全部为负 `R²`。详见
`docs/experiment_report.md`。

## APPLES 数据接入

在 NSRR 完成 APPLES 数据申请并下载后，将授权数据放置在本地目录，再运行：

- `apples-dataset-0.1.0.csv`
- diagnostic visit 的 EDF 与 XML annotation

先运行不依赖原始波形的临床基线：

```bash
.venv/bin/python scripts/run_apples_baseline.py \
  --dataset data/raw/apples/apples-dataset-0.1.0.csv
```

基线分别评估混杂变量、传统睡眠指标、两者融合。任何深度表征或不确定性结果必须超过“混杂变量 + 传统睡眠指标”，并报告外层交叉验证的 OOF 指标。

## 公开仓库中的实验结果

公开的聚合指标位于 `results/`，主要包括睡眠分期校准指标、消融实验指标、留一中心验证结果和 Sleep-EDF 汇总结果。受试者级结果不作为公开仓库内容。

## 核心实验结论

在 APPLES 主分析队列中，ExtraTrees 睡眠分期模型结合受试者隔离的温度校准后，睡眠阶段后验概率的预期校准误差（ECE）由 `0.0831` 降至 `0.0158`，负对数似然（NLL）由 `0.6360` 降至 `0.6102`，说明校准能够明显改善分期概率的可靠性。

在 HAMD 总分大于等于 8 的抑郁症状风险辅助评估任务中，加入校准后的睡眠分期不确定性特征后，嵌套交叉验证 AUROC 由 `0.6348` 提升至 `0.6745`，增量为 `0.0401`（95% CI：`0.0108–0.0712`）；留一中心验证 AUROC 由 `0.6242` 提升至 `0.6589`，增量为 `0.0347`（95% CI：`0.0021–0.0682`）。这表明睡眠分期后验不确定性可以为传统睡眠结构、动态及临床变量提供额外信息。

当前结果支持的结论是：睡眠分期概率校准与不确定性特征融合具有抑郁症状风险辅助评估价值。该模型输出的是研究性 `0–1` 风险评分，尚不能替代临床诊断；其临床适用性仍需独立队列和前瞻性研究进一步验证。

## 校准敏感性风险区间

仓库新增了校准敏感性传播实验。该实验不重新训练睡眠分期模型，而是将已校准后验
概率按一组温度倍率重新缩放，重新计算受试者级不确定性特征，并将各组特征输入同一
个风险模型。多次计算所得风险评分的最小值和最大值构成风险区间。风险区间跨过模型
判别阈值时，系统输出“结果不稳定，建议复核”，不输出确定性分类。

```bash
.venv/bin/python scripts/run_apples_risk_stability.py
```

在默认的正负 10% 温度敏感性范围内，嵌套五折验证有 44 人发生阈值翻转。这组样本的
误判率为 `61.36%`，未翻转样本的误判率为 `33.02%`，两组差值为 `28.34` 个百分点
（95% CI：`13.48–43.22`）。风险模型层留一中心验证中，两组误判率差值为 `19.31`
个百分点（95% CI：`3.11–34.96`）。该结果支持把阈值翻转作为不稳定结果的复核条件，
不支持将风险区间解释为临床置信区间。

实现与证据位于：

- `src/sleepdep/stability.py`
- `scripts/run_apples_risk_stability.py`
- `results/apples/risk_stability/metrics.json`

## 主要实验矩阵

| 编号 | 输入 | 目的 |
|---|---|---|
| E0 | 年龄、性别、BMI、中心、OSA | 混杂基线 |
| E1 | 人工分期的 architecture + dynamics | 临床可解释基线 |
| E2 | 自动分期的 architecture + dynamics | 自动化代价 |
| E3 | E2 + 未校准 entropy | 识别模型失配风险 |
| E4 | E2 + 折内温度校准 entropy | 核心增量检验 |
| E5 | E4 + 条件残差 entropy | 负结果对照 |
| E6 | E5 + 周期相位特征 | 负结果对照 |
| S1 | E4 + 校准敏感性风险区间 | 阈值稳定性与待复核判别 |

当前专利实施例使用 HAMD 总分不低于 8 的阈值任务验证风险稳定性。连续 BDI-I、
连续 HAMD 和 BDI-I 阈值任务仍作为负结果或探索性结果保留。数据切分必须按受试者
执行，预处理、校准和超参选择均限制在训练折内。
