# 专利申请证据索引

版本日期：2026-09-07

本索引用于把申请文本中的事实、数值和方法逐项映射到可核验文件。未列入本索引的
性能数字不得写入申请文件。

## 1. 数据来源

| 事实 | 证据文件 | 核验字段 |
|---|---|---|
| 原始 APPLES 归档 SHA-256 | `data/apples_curated/manifest.json` | `source_archive_sha256` |
| 有效 YASA NPZ 为 847 个 | `data/apples_curated/manifest.json` | `counts.yasa` |
| 有效、去重 raw NPZ 为 483 个 | `data/apples_curated/manifest.json` | `counts.raw_1ch` |
| 排除损坏 NPZ 37 个 | `data/apples_curated/manifest.json` | `counts.corrupt_entries` |
| 临床合并队列 1073 人 | `data/apples_curated/cohort_summary.json` | `subjects` |
| YASA 且 TST 不少于 4 小时为 798 人 | `data/apples_curated/cohort_summary.json` | `yasa_over_4h` |
| raw 且 TST 不少于 4 小时为 443 人 | `data/apples_curated/cohort_summary.json` | `raw_1ch_over_4h` |
| 主分析所用临床文件 | `data/apples_curated/manifest.json` | `clinical_files` |

清洗和合并复现脚本：

- `scripts/curate_apples_archive.py`
- `scripts/build_apples_cohort.py`
- `scripts/extract_apples_sequence_features.py`

## 2. 分期与校准方法

| 申请内容 | 代码证据 |
|---|---|
| 受试者级五折 OOF | `scripts/generate_apples_oof_posteriors.py` 中 `StratifiedKFold` |
| 每个训练折保留 20% 校准受试者 | 同脚本中 `train_test_split(test_size=0.2)` |
| 温度参数仅由校准集合拟合 | 同脚本中 `fit_temperature` 及外层 fold 处理 |
| 温度搜索范围 0.2 至 5.0 | 同脚本 `minimize_scalar` 的 `bounds` |
| 归一化 posterior entropy | 同脚本 `normalized_entropy` |
| ECE 采用 15 个区间 | 同脚本 `expected_calibration_error(..., bins=15)` |
| ExtraTrees backbone | 同脚本 `--classifier extra_trees` 分支 |

分期结果：

`results/apples/posterior_extratrees/staging_metrics.json`

| 指标 | 数值 | JSON 路径 |
|---|---:|---|
| 受试者 | 798 | `subjects` |
| Accuracy | 0.76540994 | `mean.accuracy` |
| Macro-F1 | 0.65029586 | `mean.macro_f1` |
| 校准前 NLL | 0.63601329 | `mean.uncalibrated_nll` |
| 校准后 NLL | 0.61020985 | `mean.calibrated_nll` |
| 校准前 ECE | 0.08311237 | `mean.uncalibrated_ece` |
| 校准后 ECE | 0.01580941 | `mean.calibrated_ece` |

## 3. 风险模型特征

完整特征名单：

`results/apples/posterior_ablation_extratrees/metrics.json`
中的 `feature_sets`。

E4 相对 E3 新增的十项特征：

- `entropy_mean`
- `entropy_std`
- `entropy_p90`
- `posterior_margin_mean`
- `entropy_boundary_excess`
- `entropy_w_mean`
- `entropy_n1_mean`
- `entropy_n2_mean`
- `entropy_n3_mean`
- `entropy_rem_mean`

特征聚合实现：

- `src/sleepdep/features.py`
- `scripts/generate_apples_oof_posteriors.py`

风险模型训练、嵌套验证和留一中心验证：

- `scripts/run_apples_clinical_experiments.py`
- `scripts/run_apples_posterior_experiments.py`

## 4. 支持的正面效果

唯一建议写入摘要或有益效果的任务是 ExtraTrees backbone 上的 HAMD 阈值分类。

来源：

`results/apples/posterior_ablation_extratrees/metrics.json`
中的 `tasks.hamd_classification`。

| 结果 | 数值 | JSON 路径 |
|---|---:|---|
| E3 nested AUROC | 0.63477434 | `nested_cv.E3_dynamics.overall.auroc` |
| E4 nested AUROC | 0.67450390 | `nested_cv.E4_calibrated_entropy.overall.auroc` |
| nested ΔAUROC | 0.04005326 | `nested_paired_deltas.E4_minus_E3.estimate` |
| nested 95% CI | [0.01080402, 0.07118787] | `nested_paired_deltas.E4_minus_E3.ci` |
| E3 LOSO AUROC | 0.62419930 | `leave_one_site_out.E3_dynamics.overall.auroc` |
| E4 LOSO AUROC | 0.65892348 | `leave_one_site_out.E4_calibrated_entropy.overall.auroc` |
| LOSO ΔAUROC | 0.03474277 | `loso_paired_deltas.E4_minus_E3.estimate` |
| LOSO 95% CI | [0.00210778, 0.06819030] | `loso_paired_deltas.E4_minus_E3.ci` |

配对区间由 `scripts/run_apples_posterior_experiments.py` 中
`paired_deltas(..., iterations=5000)` 生成。

## 5. 校准敏感性传播证据

实现文件：

- `src/sleepdep/stability.py`
- `scripts/run_apples_risk_stability.py`
- `tests/test_stability.py`

结果文件：

- `results/apples/risk_stability/metrics.json`
- `results/apples/risk_stability/predictions.csv`

实施例使用已保存的校准后验概率，通过概率幂变换生成不同温度倍率下的后验序列。
该变换不改变每个时间片段的最大概率类别，也不重新执行睡眠分期模型。风险模型只在
基准倍率特征上训练一次，各温度倍率共用同一组风险模型参数。

五折温度参数为0.6757、0.7060、0.6995、0.7649和0.7570，中位数为0.7060，相对
中位数的变化范围为-4.29%至8.35%。正负10%作为覆盖该折间变化的工程敏感性容差，
不是由统计推断得到的置信区间。

正负10%温度范围、2.5%步长的主要结果：

| 协议 | 跨阈值人数 | 跨阈值比例 | 跨阈值组误判率 | 稳定组误判率 | 误判率差值 | 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| 嵌套五折 | 44 | 5.51% | 61.36% | 33.02% | 28.34个百分点 | 13.48至43.22个百分点 |
| 风险模型层留一中心 | 41 | 5.14% | 53.66% | 34.35% | 19.31个百分点 | 3.11至34.96个百分点 |

对应的Fisher精确检验：

| 协议 | 优势比 | \(p\) 值 |
|---|---:|---:|
| 嵌套五折 | 3.2211 | 0.000243 |
| 风险模型层留一中心 | 2.2134 | 0.017760 |

允许写入申请文件的结论：

- 校准参数敏感性可以传播为受试者级风险区间。
- 风险区间跨过判别阈值的样本在两套验证协议中均有更高误判率。
- 跨阈值条件可以作为输出待复核标志的可执行规则。
- 概率幂变换能够从已保存的校准后验直接生成温度视图，无需重新执行分期模型。
- 逐受试者结果以`-1`表示待复核、`0`表示稳定低风险倾向、`1`表示稳定高风险倾向。

不得写入申请文件的结论：

- 温度敏感性范围是统计置信区间。
- 拒绝机制提高了全体受试者的AUROC或分类准确率。
- 正负10%对所有模型、数据集或量表都是最优范围。
- 待复核标志能够替代临床判断。

## 6. 必须披露的负结果

| 比较 | 估计值 | 95% CI | JSON 路径 |
|---|---:|---:|---|
| E5-E4 nested ΔAUROC | -0.01283473 | [-0.02553600, -0.00053856] | `hamd_classification.nested_paired_deltas.E5_minus_E4` |
| E6-E5 nested ΔAUROC | -0.01512093 | [-0.02948247, -0.00091645] | `hamd_classification.nested_paired_deltas.E6_minus_E5` |
| E6-E5 LOSO ΔAUROC | -0.02892274 | [-0.04417110, -0.01381293] | `hamd_classification.loso_paired_deltas.E6_minus_E5` |

其他限制：

- BDI-I 分类没有稳定增量；
- 连续 HAMD 和连续 BDI-I 的增量置信区间跨零；
- SGD backbone 没有稳定复现；
- Bovy 数据不包含本实验所需的分期 posterior，不能作为 E4 外部验证。

## 7. 文献依据

| 依据 | 可核验标识 | 本申请允许引用的结论 |
|---|---|---|
| SleepTransformer | DOI `10.1109/TBME.2022.3147187` | 后验熵可量化分期决策不确定性并辅助复核 |
| Kang et al., NPJ Digital Medicine 2021 | DOI `10.1038/s41746-021-00515-3` | Shannon entropy 可用于选择需人工复核的分期 epoch |
| L-SeqSleepNet | DOI `10.1109/JBHI.2023.3303217` | 长序列单通道 EEG 自动分期 |
| Pan et al. | DOI `10.1109/TCDS.2024.3358022` | 自动分期后使用睡眠结构进行抑郁检测 |
| Bechny et al. | DOI `10.2147/NSS.S455649` | 自动分期不确定性和临床复核 |
| InsightSleepNet | DOI `10.1186/s12911-024-02437-y` | 睡眠分期层的低置信度拒绝 |
| Kompa et al. | DOI `10.1038/s41746-020-00367-3` | 医疗机器学习中的不确定性表达和选择性预测 |
| LPSGM 预印本 | DOI `10.1101/2024.12.11.24318815` | PSG 基础模型用于睡眠分期和精神障碍任务；当前为预印本 |
| APPLES/NSRR 资源说明 | DOI `10.1093/sleep/zsae088` | NSRR 数据资源背景，不替代 APPLES 数据使用协议 |

引用上述论文不得扩张为“论文已证明 posterior entropy 与抑郁相关”。该关联只来自
本项目当前 APPLES 实验，且仅在一个模型和一个二分类终点得到支持。

## 8. 专利依据

| 公开号 | 申请日/公开日 | 核验来源 | 与本申请的关系 |
|---|---|---|---|
| CN106859673A | 2017-01-13 / 2017-06-20 | 公开号全文 | 睡眠脑电抑郁风险筛查系统 |
| CN117530689A | 2023-10-17 / 2024-02-09 | 公开号全文 | 分期曲线、睡眠量化指标和抑郁识别 |
| CN119700114A | 2024-12-11 / 2025-03-28 | 公开号全文 | CNN-BiLSTM 分期与 DepNet2D 抑郁筛查 |
| CN120913883A | 2025-07-31 / 2025-11-07 | 公开号全文 | 预训练分期模型与抑郁任务联合微调 |
| CN105517484A | 公开文本 | 公开号全文 | 睡眠数据和多个生物标记用于抑郁等医学状况 |

正式提交前应从 CNIPA、WIPO、EPO 或 USPTO 的权威数据库保存全文、权利要求和法律
状态。本索引中的网页初筛不构成自由实施分析。

## 9. 真实性检查规则

1. 申请中的每个样本数、性能数字和置信区间必须能映射到本索引。
2. 统计结果保留至少四位小数后再按统一规则展示三位小数。
3. “显著”仅用于配对 bootstrap 区间不跨零的预先定义指标。
4. 当前实施例必须写明使用 YASA 时间片段特征，而非声称使用 raw C4-M1 波形。
5. 阴性结果不得从内部交底和代理人材料中删除。
6. 新增实验应先保存脚本、预测、指标 JSON、环境和数据哈希，再更新申请文本。
