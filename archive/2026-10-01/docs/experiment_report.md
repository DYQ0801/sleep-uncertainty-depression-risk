# 阶段性实验报告

日期：2026-08-02

## 1. 已完成

- 解包并审阅 12 篇用户提供的 PDF 和 1 份方案说明。
- 拉取 L-SeqSleepNet 官方代码、SHHS 预训练权重和其自带 Sleep-EDF-20 数据。
- 拉取 APPLES 数据字典与官方数据说明。
- 拉取 LPSGM 最新代码、论文和 460 例 APPLES 抑郁标签。
- 实现 64 个整夜睡眠结构和转移动态特征。
- 实现经校准分期概率的 entropy、posterior margin、边界/稳定段差异、分期条件和周期相位对齐特征。
- 实现 APPLES 连续 BDI-I 的嵌套交叉验证临床基线。
- 从 OSF 拉取并统一 Bovy et al. 2022 的三个独立 MDD 睡眠队列。
- 完成按数据集留一外部验证、消融、bootstrap 置信区间和 HAMD 严重度回归。

## 2. 真实数据验证

数据源：L-SeqSleepNet 官方仓库附带的 Sleep-EDF-20 预处理数据。

有效记录：39 晚。官方目录缺少 `n14_2`，因此不是预期的 40 晚。

| 指标 | 结果 |
|---|---:|
| TST 均值 | 432.3 min |
| TST 中位数 | 432.0 min |
| 睡眠效率中位数 | 0.793 |
| REM latency 中位数 | 79.5 min |
| REM latency 范围 | 26.5-225.5 min |
| REM/TST 中位数 | 0.223 |
| 每小时阶段切换中位数 | 11.46 |

输出：

- `results/sleepedf/night_features.csv`
- `results/sleepedf/night_features.summary.json`

这些结果验证了特征提取器能处理真实整夜标注，但不构成抑郁预测实验，因为 Sleep-EDF 不含 BDI 或临床抑郁结局。

## 3. 数据质控发现

- 部分 Sleep-EDF 文件保留很长的记录前清醒段，SOL 最大达到 481 min。
- 正式 APPLES 实验必须使用 lights-off/lights-on 或 PSG 在床边界，不能直接使用 EDF 首尾。
- L-SeqSleepNet 数据标签为 `1..5`，工程入口已显式映射为 `0..4`。
- 后验 entropy 暂未在真实数据上计算，因为官方模型依赖 Python 3.7/TensorFlow 1.x，当前 macOS ARM 环境没有兼容运行时；正式实验优先用容器或现代 PyTorch backbone 生成概率。

## 4. APPLES 阻塞项

NSRR 页面和数据字典可公开访问，但 phenotype CSV、EDF 和 annotation 需要登录、同意数据使用协议并获得 APPLES 授权。匿名请求会返回文件浏览登录页。

授权后需要放置：

```text
data/raw/apples/
  apples-dataset-0.1.0.csv
  edfs/
  annotations/
```

随后可立即运行：

```bash
.venv/bin/python scripts/run_apples_baseline.py \
  --dataset data/raw/apples/apples-dataset-0.1.0.csv
```

## 5. 替代 MDD 队列外部验证

数据源：Bovy et al. 2022 公开 OSF 项目 `bdez9` 的 Dataset A/B/C 派生数据。

分析纳入 219 晚：

| 队列 | 对照 | MDD | MDD 状态 |
|---|---:|---:|---|
| A | 40 | 40 | 长期用药 |
| B | 40 | 40 | 未用药 |
| C | 28 | 31 | 用药 7 天 |

按作者脚本剔除了 C 中与 A 重复的 7 名受试者。每晚两个中央通道的
spindle/slow-wave 指标取均值；S3 与 S4 合并为 SWS。模型训练和调参均不接触
留出数据集，内层按训练数据集分组选择正则强度。

### 5.1 MDD 与对照分类

| 留出队列 | 人口学 AUROC | +宏结构 AUROC | +微结构 AUROC |
|---|---:|---:|---:|
| A | 0.599 | 0.730 | 0.781 |
| B | 0.504 | 0.538 | 0.526 |
| C | 0.501 | 0.815 | 0.805 |
| 跨队列宏平均 | 0.535 | 0.694 | 0.704 |

宏结构模型的 pooled AUROC 为 0.653（95% bootstrap CI 0.572-0.723），最差
外部队列 AUROC 为 0.538。相对人口学基线，宏结构的配对
`ΔAUROC=0.140`（按数据集分层 bootstrap 95% CI 0.043-0.231）。

加入 spindle/slow-wave 后 pooled AUROC 降至 0.614；相对宏结构的
`ΔAUROC=-0.038`（95% CI -0.109-0.029）。因此微结构未显示稳定增量价值。

解释：

- A/C 的可分性较好，但未用药 B 队列接近随机，结果存在明显队列/用药异质性。
- 宏结构相对人口学有统计增量，但尚不足以称为稳定的跨中心临床分类器。
- 微结构可能受设备、参考导联和检测参数影响，直接跨中心拼接会降低稳健性。

### 5.2 逐 epoch 动态特征消融

OSF 还提供 299 个 hypnogram 目录对象。下载器保存每个对象的 URL、字节数和
SHA-256；与分析队列匹配后有 213 晚动态特征完整。R&K 的 N3/N4 合并，
`-1`（未评分）和 `8`（movement）作为序列断点，不计算跨断点转移。

| 留出队列 | 宏结构 | +转移/bout | +微结构 |
|---|---:|---:|---:|
| A | 0.731 | 0.803 | 0.878 |
| B | 0.549 | 0.555 | 0.547 |
| C | 0.803 | 0.809 | 0.871 |
| 跨队列宏平均 | 0.694 | 0.722 | 0.765 |
| pooled AUROC | 0.667 | 0.726 | 0.782 |

宏结构+动态的 pooled AUROC 为 0.726（95% CI 0.659-0.796）；相对宏结构
`ΔAUROC=0.060`（95% CI -0.010-0.123），尚未达到稳定增量。继续加入微结构后
pooled AUROC 为 0.782（95% CI 0.721-0.841），配对
`ΔAUROC=0.056`（95% CI 0.003-0.110）。

该阳性增量主要来自 A/C，B 队列仍仅为 0.547。因此结论是“融合特征在 pooled
外部预测中有增量，但受用药状态/队列域显著调节”，不能声称三个外部中心方向
一致或达到临床部署标准。

### 5.3 HAMD 严重度外部回归

患者样本为 A=33、B=40、C=31。A/B 使用与 PSG 对应的 `hamd_0`，C 使用
7 天访视 `hamd_week1`。

| 留出队列 | 宏结构 MAE | 宏结构 R² | 宏结构 Spearman |
|---|---:|---:|---:|
| A | 5.57 | -0.678 | -0.021 |
| B | 3.68 | -0.462 | -0.089 |
| C | 5.47 | -0.069 | 0.079 |

融合微结构没有实质改善。当前特征不能外部预测 HAMD 严重度；该负结果必须保留，
不能以队列内随机切分结果替代。

### 5.4 复现产物

- `scripts/download_bovy_hypnograms.py`
- `scripts/run_bovy_external_validation.py`
- `data/external/bovy2022/hypnograms_manifest.json`
- `results/bovy2022/analysis_cohort.csv`
- `results/bovy2022/diagnosis_predictions.csv`
- `results/bovy2022/dynamics_diagnosis_predictions.csv`
- `results/bovy2022/severity_predictions.csv`
- `results/bovy2022/external_validation.json`

复现命令：

```bash
.venv/bin/python scripts/download_bovy_hypnograms.py
.venv/bin/python scripts/run_bovy_external_validation.py
```

## 6. 当前可验证性

```text
6 passed
```

单元测试覆盖：

- SOL/TST/WASO/REM latency 定义。
- 转移矩阵行归一化和阶段切换率。
- 边界 entropy 与稳定段 entropy。
- REM episode 终止周期的相位对齐和周期间漂移。
- 非法概率形状及未归一化输入拒绝。

## 7. 尚不能声称的结果

- 尚无 APPLES BDI-I 的 OOF MAE、`R²` 或 AUROC。
- 尚未证明不确定性特征与抑郁相关。
- 尚未完成正式专利查新和自由实施分析。
- Bovy 数据不含 epoch 后验概率，不能用于验证周期相位条件化 entropy。
- 当前已达到“可复现多队列外部验证 + 明确正负结果”的研究原型标准，但核心
  entropy 发明点尚未达到论文主结论或专利实施例的证据标准。
