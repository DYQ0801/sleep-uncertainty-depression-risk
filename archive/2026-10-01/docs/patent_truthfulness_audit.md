# 专利申请书真实性审计

审计日期：2026-09-07

审计对象：`docs/patent_application_full.md`

## 1. 审计结论

修订后的申请书未发现伪造的样本量、哈希、模型参数或性能指标。所有定量实验结果均
可映射到本地数据清单、脚本和结果 JSON。

但不能把这一结论表述为“所有内容均已由外部权威机构证明”。当前证据分为三层：

1. **本地直接可复核：** 数据文件哈希、文件数量、队列人数、算法实现、模型指标和
   bootstrap区间。
2. **公开来源可核验：** CN117530689A和SleepTransformer等在先技术的基本内容。
3. **尚待申请人或代理人核验：** APPLES归档的官方下载链和使用授权、申请人法人
   全称、共同申请权属、发明人身份以及完整专利查新。

## 2. 定量数据核验

| 申请书声明 | 核验结果 | 直接证据 |
|---|---|---|
| 原始归档SHA-256 | 一致 | `shasum -a 256 data/apples.zip`及`data/apples_curated/manifest.json` |
| 有效YASA文件847个 | 一致 | `manifest.json: counts.yasa`及实际文件计数 |
| 主分析798人 | 一致 | `cohort_summary.json: yasa_over_4h` |
| YASA时间片段特征为114维 | 一致 | 847个NPZ的`x.shape[1]`均为114 |
| HAMD阳性阈值为总分不低于8 | 一致 | `analysis_cohort.csv`中`diagnosis_hamd == (hamd >= 8)`对1073人全部成立 |
| 主分析HAMD阳性147人 | 一致，申请书未使用该数字 | `analysis_cohort.csv` |
| 五折模型/校准/测试人数 | 一致 | `staging_metrics.json: folds` |
| 五折温度参数 | 一致 | `staging_metrics.json: folds[].temperature` |
| ECE 0.0831降至0.0158 | 一致 | `staging_metrics.json: mean` |
| NLL 0.6360降至0.6102 | 一致 | `staging_metrics.json: mean` |
| nested AUROC 0.6348至0.6745 | 一致 | `metrics.json: tasks.hamd_classification.nested_cv` |
| nested ΔAUROC及95% CI | 一致 | `nested_paired_deltas.E4_minus_E3` |
| LOSO AUROC 0.6242至0.6589 | 一致 | `leave_one_site_out` |
| LOSO ΔAUROC及95% CI | 一致 | `loso_paired_deltas.E4_minus_E3` |
| 配对bootstrap 5000次 | 一致 | `scripts/run_apples_posterior_experiments.py:65-105` |
| 正负10%嵌套五折跨阈值44人 | 一致 | `risk_stability/metrics.json` |
| 嵌套五折跨阈值组误判率61.36% | 一致 | 同上 |
| 嵌套五折稳定组误判率33.02% | 一致 | 同上 |
| 嵌套五折误判率差值28.34个百分点 | 一致 | 同上 |
| 正负10%留一中心跨阈值41人 | 一致 | 同上 |
| 留一中心误判率差值19.31个百分点 | 一致 | 同上 |

核心结果文件：

- `results/apples/posterior_extratrees/staging_metrics.json`
- `results/apples/posterior_ablation_extratrees/metrics.json`
- `results/apples/posterior_ablation_extratrees/predictions.csv`
- `results/apples/risk_stability/metrics.json`
- `results/apples/risk_stability/predictions.csv`

审计时从`predictions.csv`独立重算AUROC，并按实验脚本相同随机种子重新执行5000次
配对bootstrap，得到的nested和LOSO AUROC、差值及置信区间与`metrics.json`逐位一致。
这说明申请书中的核心风险模型指标可以由逐受试者预测重建，并非只有汇总数字。

## 3. 算法实现核验

| 方法声明 | 状态 | 代码证据 |
|---|---|---|
| 按受试者五折生成OOF后验 | 已实现 | `generate_apples_oof_posteriors.py:253-275` |
| 每个训练折保留20%校准受试者 | 已实现 | 同文件`:277-282` |
| ExtraTrees 160棵树 | 已实现 | 同文件`:305-313` |
| 温度搜索范围0.2至5.0 | 已实现 | 同文件`:67-78` |
| 温度目标为多分类NLL | 已实现 | 同文件`:67-70` |
| 归一化Shannon entropy | 已实现 | `src/sleepdep/features.py:196-205` |
| posterior margin | 已实现 | 同文件`:198-205` |
| 阶段内与边界entropy | 已实现 | 同文件`:210-227` |
| 类别加权逻辑回归 | 已实现 | `run_apples_clinical_experiments.py:108-120` |
| 风险模型四折内层调参、五折外层评估 | 已实现 | 同文件`:123-143,167-208` |
| 风险模型层留一中心 | 已实现 | 同文件`:211-251` |
| 从校准后验直接生成温度敏感性后验 | 已实现 | `src/sleepdep/stability.py`中的`temperature_rescale` |
| 风险区间、宽度和稳定性指数 | 已实现 | 同文件中的`risk_interval_summary` |
| 跨阈值组和稳定组误判率比较 | 已实现 | `scripts/run_apples_risk_stability.py` |
| 受试者级bootstrap误判率差值 | 已实现 | `bootstrap_group_error_difference` |

## 4. 已发现并修正的问题

### 4.1 未实现的数据质量和校准域提示

原申请书权利要求11包含“数据质量标志和超出校准范围提示”，但当前代码没有对应
实现或实验。该权利要求已删除，后续设备权利要求已重新编号。

### 4.2 不存在风险模型特征选择

原说明书声称“特征选择只在训练折完成”，但当前风险模型使用预先固定的特征集合，
没有折内特征选择步骤。该表述已删除。

### 4.3 风险评分不是临床绝对概率

当前逻辑回归使用`class_weight="balanced"`，且没有对风险模型输出再做概率校准。
申请书已将其改为“0至1模型评分”，明确不解释为人群绝对患病概率。

### 4.4 留一中心不是全流程中心隔离

分期后验先通过一套受试者五折生成，风险模型再使用另一套嵌套五折或留一中心切分。
风险模型的留一中心测试对象可能参与过用于生成其他受试者后验特征的上游分期模型。
因此，原“留一中心验证”已改为“风险模型层留一中心验证”，并明确不是全流程端到端
中心外部验证。

### 4.5 E3并非完全自动分期特征

当前E3中的睡眠宏结构来自APPLES临床表，睡眠阶段动态特征由YASA文件中保存的人工
睡眠阶段标签计算。申请书已补充该事实，避免把整个基线描述为自动分期结果。

### 4.6 过宽的输入模态和模型范围

原说明书列举EEG、EOG、EMG、ECG、呼吸、血氧、体动以及CNN、RNN、Transformer，
但当前实施例只验证YASA脑电时间片段特征上的ExtraTrees和SGD。已将说明书收缩到
脑电时间片段特征及实际验证的两个分期模型。

### 4.7 风险区间不是统计置信区间

实施例中的正负5%、正负10%和正负15%是预设工程敏感性容差。当前代码没有从校准
样本估计温度参数的统计置信区间，因此申请书只使用“风险区间”或“校准敏感性区间”，
不使用“置信区间”描述单名受试者的风险上下界。

### 4.8 拒绝机制不提高全体样本准确率

跨阈值规则把部分样本转为待复核，改变了自动输出覆盖率。它识别出了误判率更高的
样本组，但不能据此声称全体受试者的AUROC或准确率得到提高。当前实验还显示，以风险
稳定性指数排序的风险覆盖曲线没有稳定优于简单的风险评分边距，因此主张限定为校准
敏感性引起的阈值翻转判别。

## 5. 外部依据核验

### CN117530689A

公开信息能够核验该专利名称为《一种基于睡眠生理数据的抑郁障碍识别系统》，公开
内容包括分窗、睡眠分期、整夜分期曲线、睡眠量化指标和抑郁障碍识别。申请书对其
描述与公开摘要一致。

来源：

`https://patents.google.com/patent/CN117530689A/zh`

### SleepTransformer

论文题目为“SleepTransformer: Automatic Sleep Staging With Interpretability and
Uncertainty Quantification”，DOI为`10.1109/TBME.2022.3147187`。公开摘要明确
说明使用基于entropy的方法量化模型决策不确定性并将低置信度epoch交由人工检查。

来源：

`https://doi.org/10.1109/TBME.2022.3147187`

### 不确定性复核与选择性预测

Bechny等人的研究使用睡眠分期不确定性选择需要人工复核的时间片段；
InsightSleepNet使用能量分数拒绝低置信度睡眠分期结果；Kompa等人的综述讨论了医疗
机器学习中的不确定性表达和选择性预测。这些工作说明“不确定时拒绝”本身属于已知
思想，不能单独作为本申请的创新点。

来源：

- `https://doi.org/10.2147/NSS.S455649`
- `https://doi.org/10.1186/s12911-024-02437-y`
- `https://doi.org/10.1038/s41746-020-00367-3`

### APPLES与睡眠抑郁背景

APPLES可由临床试验登记`NCT00051363`和NSRR综述进行外部核验；NSRR综述DOI为
`10.1093/sleep/zsae088`。抑郁与睡眠连续性、非快速眼动睡眠和REM睡眠改变的背景
可由综述“Depression and Sleep”核验，DOI为`10.3390/ijms20030607`。

这些公开来源只能证明队列和一般医学背景，不能替代对本地`data/apples.zip`下载授权
和文件来源链的核验。

## 6. 仍不能确认的事项

以下事项不属于实验代码能够证明的范围：

- `data/apples.zip`是否通过申请人本人获授权的官方渠道下载；
- 数据使用协议是否允许将具体实验结果写入专利并提交；
- “超级机器人研究院（黄埔）”是否为请求书中应填写的准确法人名称；
- 华南理工大学与研究院之间的共同申请比例、发明人归属和职务发明手续；
- 当前权利要求是否满足新颖性、创造性、充分公开和专利客体要求；
- 是否存在尚未检索到的国内外在先专利。

## 7. 最终使用规则

1. 可确认“当前申请书没有编造定量实验数据”。
2. 不可确认“当前方案必然授权”或“已完成正式全球查新”。
3. 对外提交时应保留本审计涉及的脚本、JSON、预测表、归档哈希和环境信息。
4. 在完成端到端严格嵌套验证前，不得把当前LOSO结果称为完整流程的跨中心外部验证。
5. 申请人和发明人信息必须由所属单位科研或知识产权部门最终确认。
6. 正负10%只能写为本实施例参数，不得写成普适最优值或统计置信范围。

## 8. 审计快照哈希

```text
申请书：
325d58a8f60f93ac8c78b099ac13c2cc9f15ffe3454cf391dc062fd93abf3283

分期指标：
467bacdf5699b40d26d89c6ff8564534c1b767b868ee5ad26e05d2450ec5e15c

风险模型指标：
3f8b5712444635aa01ed98904da3d8dbbb9ea128e0ffb718ac1ea5e60452c1eb

逐受试者预测：
7b40021d5ab3d1e54f28cbb8a5d2dcbc27852acb9744bf3072a2b72bee8f1a66

校准敏感性指标：
e0ff512a34eed5f06bd06bb519f7672e91b672c5d049e753707be3b4f55301a7

校准敏感性逐受试者结果：
aea6cd6966ff2271cd1061828b178186c7d94ff9ed5663e9f008c00e2dbefb20
```

申请书再次修改后，其哈希会改变，应重新生成审计快照。
