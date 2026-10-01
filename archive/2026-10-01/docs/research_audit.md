# 技术方案审计与研究路线

更新日期：2026-08-02

状态：历史研究路线。后续实验已证实条件残差和周期相位特征没有带来正向增量，因此
不再作为专利主线。当前申请方案见 `docs/patent_application_full.md`。

## 1. 结论

原方案的医学动机成立，但“长序列睡眠分期表征 + 睡眠结构特征 + 抑郁分类”已经有高度接近的公开工作，不能直接作为论文或发明专利的核心创新。

建议把科学问题收敛为：

> 经跨中心校准并去除分期难度、信号质量和 OSA 混杂后的“周期相位条件化睡眠状态模糊性指纹”，能否在传统睡眠结构和深度整夜表征之外增量预测 BDI-I？

这里的“模糊性”来自睡眠分期模型的后验分布。它是待验证的数字生物标志物，不应预先称为抑郁生物标志物。

## 2. 原方案中需要修正的论断

1. SleepTransformer 证明的是 posterior entropy 可用于识别低置信度 epoch 和辅助人工复核，没有证明该熵与抑郁相关。
2. 后验熵与 EEG 多尺度熵不是同一概念。前者依赖模型、校准和域偏移；后者是原始信号复杂度。
3. L-SeqSleepNet 官方实现输出 epoch score/prediction，不直接输出定义好的 `night_emb`。任何整夜向量都必须明确池化算子并做消融。
4. “端到端模型根本不能捕捉周期结构”不成立。全夜 Transformer 和大规模 PSG 基础模型可以捕捉长程结构。更严谨的主张是：显式中间表征更适合小样本、混杂控制和临床解释。
5. APPLES 是 OSA 富集队列。若不控制 AHI、arousal index、BMI、年龄、性别和中心，模型很可能学习 OSA 或中心差异。
6. APPLES 使用 BDI-I，不是 BDI-II。主任务应优先做连续分数回归；阈值分类作为次要分析。
7. LPSGM 公布的 460 例标签结合既往抑郁、HAM-D 和 BDI 构造，不能用于声称“预测 BDI”。其论文当前版本又将 APPLES 任务描述为 ongoing depression medical history，公开标签说明与论文表述需要进一步向作者核验。

## 3. 近邻工作与新颖性边界

| 工作 | 已覆盖内容 | 对本项目的影响 |
|---|---|---|
| L-SeqSleepNet, JBHI 2023 | 单通道 EEG、约 200 epoch、整周期分期 | 可作为分期基线，不能独占“长序列” |
| SleepTransformer, TBME 2022 | 分期后验熵、注意力解释、人工复核 | 覆盖一般性 entropy，不覆盖抑郁增量价值 |
| Pan et al., IEEE TCDS 2024 | 自动分期后提取 7 个睡眠结构特征区分 UDD/BD/健康 | 覆盖“先分期再抑郁检测”主路径 |
| Bechny et al., NSS 2024 | 大规模跨库不确定性引导人工复核 | 证明不确定性强受域和病例难度影响 |
| LPSGM, medRxiv 2024-2026 | 大规模 PSG 预训练并在 APPLES 做抑郁筛查 | 覆盖“PSG 基础模型迁移到抑郁” |
| Enkhbayar et al., Bioengineering 2025 | PSG phenotype + 可解释模型预测抑郁 | 覆盖传统 PSG 表型路线 |
| Defillo et al., Frontiers in Sleep 2025 | 829 例、ORP 与 PHQ-9 的非线性关联 | 提示连续睡眠深度和动态特征是强对手 |

专利检索目前只完成技术关键词和公开网页初筛，不构成 FTO 或正式查新。提交前必须由专利代理人按 CNIPA、WIPO、EPO、USPTO 的权利要求全文继续检索。

## 4. 候选发明点

### 名称

一种基于校准残差与睡眠周期相位对齐的抑郁症状风险评估方法及系统。

### 方法链路

1. 获取整夜单通道或多通道 EEG，并输出每个 epoch 的五分类后验概率。
2. 使用与目标中心匹配且与评估对象隔离的校准集进行温度校准或向量校准。
3. 建立条件不确定性基线：
   `E[entropy | stage, transition_distance, signal_quality, AHI_bin, site]`。
4. 计算观测 entropy 相对条件基线的残差，降低模型失配、分期边界和 OSA 对 entropy 的污染。
5. 依据 NREM-REM 周期或 REM episode 对整夜序列做相位归一化，对周期早期、中期、REM 前后和周期间漂移分别聚合。
6. 在训练折内将上述指纹对年龄、性别、BMI、AHI、arousal index、中心做正交化。
7. 将残差指纹与传统 architecture/dynamics、整夜 embedding 融合，输出连续 BDI-I、风险区间和贡献解释。

单纯“计算 entropy 均值/CV/边界均值”过于直接，专利强度不足。候选权利要求的技术贡献应落在“条件校准残差 + 周期相位对齐 + 混杂正交化”的组合及其具体数据流。

## 5. 实验假设

- H1：传统 architecture/dynamics 在混杂基线之外对 BDI-I 有显著增量价值。
- H2：未校准 entropy 的增益在跨中心或高 AHI 人群中衰减。
- H3：校准残差不确定性在混杂基线和传统睡眠指标之外仍有增量价值。
- H4：周期相位条件化特征优于全夜 entropy 均值。
- H5：上述增益在外部队列中方向一致，并且不依赖单一 backbone。

H3/H4 是项目继续冲击专利和论文的最低证据门槛；若不成立，应停止包装该创新点。

## 6. 预注册式实验设计

### 队列

- 开发/内部验证：APPLES diagnostic PSG，主终点 BDI-I。
- 外部验证优先级：带抑郁量表和 PSG 的独立 NSRR 队列；若量表不同，做标准化症状分数并明确量表迁移限制。
- 排除：缺失主要结局、有效 EEG 时长不足、无法可靠对齐 epoch、严重记录损坏。

### 数据切分

- 按受试者分组，禁止同一人的重复访视跨折。
- 外层 5 折评估，内层选择超参。
- 校准器、缺失值填补、标准化、特征选择、正交化全部仅在训练折拟合。
- 若存在中心信息，增加 leave-one-site-out 验证。

### 比较组

- E0：人口学 + BMI + AHI + arousal index + site。
- E1：E0 + 人工分期 architecture/dynamics。
- E2：E0 + 自动分期 architecture/dynamics。
- E3：E2 + 未校准 entropy。
- E4：E2 + 校准 entropy。
- E5：E2 + 条件校准残差。
- E6：E5 + 周期相位条件化。
- E7：冻结 backbone night embedding。
- E8：E6 + E7。

至少使用 L-SeqSleepNet 和一个现代全夜/基础模型，验证结论不是特定 backbone 的副产物。

### 指标与统计

- 连续主终点：MAE、RMSE、Spearman、OOF `R²`。
- 二分类次终点：AUROC、AUPRC、balanced accuracy、Brier、ECE、灵敏度/特异度及 95% CI。
- 增量价值：外层 OOF 配对 bootstrap 的 `ΔMAE/ΔR²/ΔAUPRC`。
- 临床价值：decision curve；按 AHI、性别、年龄、中心分层。
- 多重检验：预先指定一个主比较 E6 vs E2，其余使用 Benjamini-Hochberg。

## 7. 论文与专利停止条件

- E6 相对 E2 的 OOF 增益方向不稳定或置信区间跨越无效区间。
- leave-one-site-out 明显失效且无法由校准纠正。
- entropy 与信号质量/AHI 的关联强于与 BDI 的关联，正交化后信号消失。
- 结果仅在联合构造的抑郁标签成立，而对连续 BDI-I 不成立。
- 正式专利检索发现覆盖“条件不确定性残差 + 周期相位聚合”的在先权利要求。

## 8. 关键文献

- Phan et al. L-SeqSleepNet. IEEE JBHI, 2023. DOI: 10.1109/JBHI.2023.3303217.
- Phan et al. SleepTransformer. IEEE TBME, 2022. DOI: 10.1109/TBME.2022.3147187.
- Pan et al. Depression Detection Using an Automatic Sleep Staging Method. IEEE TCDS, 2024. DOI: 10.1109/TCDS.2024.3358022.
- Bechny et al. Bridging AI and Clinical Practice. Nature and Science of Sleep, 2024. DOI: 10.2147/NSS.S455649.
- Zhang et al. National Sleep Research Resource. Sleep, 2024. DOI: 10.1093/sleep/zsae088.
- Yun. EEG-based biomarkers for psychiatric disorders. J Yeungnam Med Sci, 2024. DOI: 10.12701/jyms.2024.00668.
- Enkhbayar et al. Explainable AI Models for Predicting Depression Based on PSG Phenotypes. Bioengineering, 2025. DOI: 10.3390/bioengineering12020186.
- Klingaman and Gehrman. Sleep EEG biomarkers of psychopathology. Sleep, 2025. DOI: 10.1093/sleep/zsae270.
