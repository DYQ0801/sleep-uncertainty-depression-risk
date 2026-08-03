# APPLES 主实验报告

日期：2026-08-02

## 1. 数据与队列

原始来源为 `data/apples.zip`，SHA-256：

```text
c14232eb07e92a875b6a16ca5975328884c742f29b225eb63aef14d435014f4a
```

清洗时验证了内嵌 NPZ 的 ZIP 结构与必要成员，按 `fileid` 去重，并跨访视连接：

- BL：BDI-I、HAMD、年龄、性别、种族、BMI。
- DX：PSG `fileid`、中心、AHI、觉醒指数和睡眠宏结构。

最终临床队列 1073 人；主分析限制为存在有效 YASA 特征且 TST 不少于 4 小时的
798 人。BDI-I 阳性定义为 `BDI >= 14`，HAMD 阳性定义为 `HAMD >= 8`。

## 2. 数据质量

- 有效 YASA NPZ：847，主分析 798。
- 有效单通道 C4-M1 NPZ：483，可匹配临床结局 471，主分析 443。
- 排除损坏 NPZ：37 个。
- 原始波形重复版本：143 个 ID，清洗后每个 `fileid` 仅保留一个版本。
- YASA 特征矩阵共 843655 epochs，仅 75 个 NaN，无 Inf。
- 单通道信号采样率统一为 100 Hz，每 epoch 3000 点。

## 3. 协议

- 所有抑郁模型按受试者五折外层交叉验证，四折内层选择正则参数。
- 增加 leave-one-site-out 五中心验证。
- 插补、标准化、类别编码和超参数选择均在训练折完成。
- 分期 posterior 采用受试者级五折 OOF。
- 每个分期训练折额外保留 20% 受试者，仅用于温度校准和条件 entropy 基线。
- 增量价值使用 5000 次配对 bootstrap。

实验组：

- E0：人口学、BMI、中心。
- E1：E0 + AHI、觉醒指数。
- E2：E1 + 睡眠宏结构。
- E3：E2 + 阶段转移和 bout。
- E4：E3 + 校准 posterior entropy。
- E5：E4 + 条件 entropy 残差。
- E6：E5 + NREM-REM 周期相位残差。

## 4. 传统特征结果

### BDI-I 连续回归

| 模型 | MAE | R² | Spearman |
|---|---:|---:|---:|
| E0 | 4.019 | 0.000 | 0.088 |
| E2 | 3.998 | 0.013 | 0.130 |
| E3 | 4.000 | 0.012 | 0.129 |

E3 相对 E2 的 `ΔMAE=-0.002`，95% CI -0.026–0.021。动态特征无增量。

### HAMD 连续回归

| 模型 | MAE | R² | Spearman |
|---|---:|---:|---:|
| E0 | 2.952 | 0.089 | 0.323 |
| E2 | 2.950 | 0.083 | 0.320 |
| E3 | 2.986 | 0.066 | 0.295 |

E3 相对 E2 显著恶化 MAE：`ΔMAE=-0.036`，95% CI -0.066–-0.008。

## 5. 分期与校准结果

| Backbone | Accuracy | Macro-F1 | 校准前 ECE | 校准后 ECE |
|---|---:|---:|---:|---:|
| SGD log-loss | 0.687 | 0.630 | 0.199 | 0.166 |
| ExtraTrees | 0.765 | 0.650 | 0.083 | 0.016 |

温度校准在两个 backbone 上均改善 NLL/ECE；ExtraTrees 作为当前较强基线。

## 6. Posterior 消融

### ExtraTrees，HAMD 二分类

| 模型 | Nested AUROC | LOSO AUROC |
|---|---:|---:|
| E3 | 0.635 | 0.624 |
| E4 | 0.675 | 0.659 |
| E5 | 0.662 | 0.646 |
| E6 | 0.647 | 0.617 |

E4 相对 E3：

- Nested `ΔAUROC=0.040`，95% CI 0.011–0.071。
- Leave-one-site-out `ΔAUROC=0.035`，95% CI 0.002–0.068。

E5 相对 E4 在 nested CV 中显著下降：
`ΔAUROC=-0.013`，95% CI -0.026–-0.001。

E6 相对 E5 同样下降：
`ΔAUROC=-0.015`，95% CI -0.029–-0.001。

### 其他终点

- BDI-I 连续回归：E4 MAE 3.973，E3 MAE 4.000，但增量 CI 跨零。
- HAMD 连续回归：E4 MAE 2.946，E3 MAE 2.986，但增量 CI 跨零。
- BDI 二分类：E4/E5/E6 均未显示稳定增量。
- SGD backbone 的结果方向不稳定，不能声称 backbone-independent。

## 7. 结论

当前数据支持以下事实：

1. 经温度校准的分期 posterior entropy 在较强 ExtraTrees backbone 上，对 HAMD
   二分类具有嵌套 CV 和留一中心增量。
2. 增量没有在 BDI-I、连续 HAMD 或 SGD backbone 上稳定复现。
3. 条件残差和周期相位是负结果，不支持作为当前主发明点。

因此现阶段可以形成可复现专利实施例，但不足以按“条件残差+周期相位”提交强
主权利要求。下一步应收缩到“跨中心校准不确定性”或更换条件残差建模方法，并
完成正式专利查新。

## 8. 复现文件

- `scripts/curate_apples_archive.py`
- `scripts/build_apples_cohort.py`
- `scripts/extract_apples_sequence_features.py`
- `scripts/run_apples_clinical_experiments.py`
- `scripts/generate_apples_oof_posteriors.py`
- `scripts/run_apples_posterior_experiments.py`
- `results/apples/clinical/metrics.json`
- `results/apples/posterior/staging_metrics.json`
- `results/apples/posterior_ablation/metrics.json`
- `results/apples/posterior_extratrees/staging_metrics.json`
- `results/apples/posterior_ablation_extratrees/metrics.json`
