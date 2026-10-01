# 睡眠分期后验与抑郁症状研究

当前阶段：探索性研究。考察 APPLES 的 OSA 人群中，睡眠分期后验描述能否在临床变量、睡眠结构和动态之外，补充 HAMD≥8 症状分类信息。BDI 与连续量表结果保留为历史分析；HAMD 阈值不代表临床诊断。

**从[研究判断与下一轮实验](docs/research_decision.md)开始阅读。** 该文回答已有研究重合、CPU 与冻结深度模型的选择、现有数据局限，以及课题成立需要什么证据。所有逐步方法依据和论文链接统一维护在[实验依据与文献清单](docs/references/实验依据与文献清单.md)。

## 目录怎么用

| 路径 | 用途 |
|---|---|
| [docs/research_decision.md](docs/research_decision.md) | 当前研究判断和下一轮实验建议 |
| [docs/references/](docs/references/) | 文献清单、元数据及核验记录，共 78 条资料与线索，包含未取得全文的条目和专利线索 |
| [src/sleepdep/](src/sleepdep/) | 睡眠特征、概率和稳定性计算 |
| [scripts/](scripts/) | 现有实验入口 |
| [tests/](tests/) | 特征和稳定性计算测试 |
| [results/](results/) | 实验结果；对外仅保留聚合指标，个体表及后验留在本地 |
| [materials/思路/](materials/思路/) | 用户提供的论文与说明原件，去重后保留一份 |
| [materials/](materials/) | 论文原件及原始资料压缩包，本地保留 |
| [data/](data/) | 授权数据与派生数据；来源清单为 `data/apples_curated/manifest.json` |
| [external/](external/) | 本地第三方项目与模型资源 |
| [archive/](archive/README.md) | 旧报告、专利草稿、答辩 PPT 和生成文件；仅供历史追溯 |

旧文档中的新颖性、单通道、验证协议和专利判断不再作为当前依据。归档清单含原路径与 SHA-256，支持恢复原目录中的文档副本。此后更新研究判断与文献清单即可，避免再生成多份相互冲突的“最新方案”。

## 已有结果及边界

主分析 798 人，其中 HAMD≥8 为 147 人。当前 114 列分期输入尚未完成生成来源追溯，不能宣称已实现单通道全自动流程；798 人中有 422 人具备本地单导联原始波形。

| 已有观察 | 数值 | 当前解释 |
|---|---|---|
| ExtraTrees 分期温度校准 | 五折均值 ECE 0.0831→0.0158；NLL 0.6360→0.6102 | 分期概率评分改善，不能替代症状任务的校准评价 |
| HAMD≥8，E3→E4 | 风险层嵌套 AUROC 0.6348→0.6745；风险层留中心 0.6242→0.6589 | 探索性增量；缺少未校准同组后验对照 |
| E5、E6 | HAMD 嵌套 AUROC 0.6617、0.6466 | 当前复杂扩展未优于 E4 |
| ±10% 温度拒绝 | 保留 754 人错 249 人；同覆盖率边距错 248 人。留中心两者均错 260/757 人 | 尚未证明温度规则优于简单边距 |

上游分期 OOF 与下游风险模型分别划折，尚未贯穿同一外测试边界；“嵌套”和“留中心”不能解释为全流程独立验证。E3 使用人工阶段动态，E4 的 10 项新增字段包含熵和 margin 等后验描述。详细数字、原始结果路径和结论限制见[研究判断](docs/research_decision.md)。

## 实验编号以代码为准

字段数指编码前的原始字段数，不能视作最终模型参数数。

| 编号 | 实际输入 | 字段数 |
|---|---|---:|
| E0 | 年龄、性别、种族、BMI、中心 | 5 |
| E1 | E0＋AHI、觉醒指数 | 7 |
| E2 | E1＋10 项临床睡眠宏结构字段 | 17 |
| E3 | E2＋11 项人工阶段转移与 bout 特征 | 28 |
| E4 | E3＋10 项校准后验描述 | 38 |
| E5 | E4＋9 项条件残差描述 | 47 |
| E6 | E5＋7 项周期相位描述 | 54 |

定义见[临床实验脚本](scripts/run_apples_clinical_experiments.py)和[后验消融脚本](scripts/run_apples_posterior_experiments.py)。风险稳定性脚本在固定 E4 风险模型上改变温度后验，属于敏感性分析。

## 复现现有探索协议

以下命令复现旧协议，尚未实现研究判断文档中的修正。默认输出会写入对应 `results/` 目录；要保留既有运行记录，可使用各脚本的 `--output` 指向新的目录，并相应修改后续输入路径。

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/pytest
```

本地整理包 `data/apples.zip` 就绪后，APPLES 现有主流程为：

```bash
.venv/bin/python scripts/curate_apples_archive.py
.venv/bin/python scripts/build_apples_cohort.py
.venv/bin/python scripts/extract_apples_sequence_features.py
.venv/bin/python scripts/run_apples_clinical_experiments.py
.venv/bin/python scripts/generate_apples_oof_posteriors.py \
  --classifier extra_trees --output results/apples/posterior_extratrees
.venv/bin/python scripts/run_apples_posterior_experiments.py \
  --posterior-features results/apples/posterior_extratrees/posterior_features.csv \
  --output results/apples/posterior_ablation_extratrees
.venv/bin/python scripts/run_apples_risk_stability.py
```

`apples.zip` 是现有工程使用的本地整理包，不等于 NSRR 下载后可直接得到的官方标准包。当前 114 列生成过程仍需追溯，不能宣称上述命令已覆盖原始 EDF 到最终结果的完整复现。

Sleep-EDF 只验证特征计算，不验证抑郁预测；Bovy 数据只能评价公开的传统特征，未包含 E4 所需后验：

```bash
.venv/bin/python scripts/extract_sleepedf_features.py
.venv/bin/python scripts/download_bovy_hypnograms.py
.venv/bin/python scripts/run_bovy_external_validation.py
```

APPLES 需经 [NSRR 官方申请](https://sleepdata.org/datasets/apples)取得授权并遵守数据使用协议。原始信号、临床表、个体级结果、权重及论文原件不随仓库分发，相关目录由 `.gitignore` 排除。
