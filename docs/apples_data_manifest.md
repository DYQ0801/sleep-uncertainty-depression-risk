# APPLES 数据使用与清理清单

## 实际用于当前实验

### 临床数据

- `apples-dataset-0.1.0.csv`
- `apples-harmonized-dataset-0.1.0.csv`
- `subject_labels_diagnosis.csv`
- `subject_labels_morethan4h.csv`

用途：跨 BL/DX 访视连接结局、人口学、BMI、中心、AHI、觉醒和宏结构。

### YASA 数据

- 847 个通过内部 ZIP 和成员校验的 `features_yasa/*.npz`
- 其中 798 人满足 TST 不少于 4 小时并进入主分析

用途：人工阶段序列、114 维 epoch 特征、OOF 分期 posterior、entropy、条件残差
和周期相位特征。

## 保留但尚未用于当前统计结果

- 483 个有效、去重后的 `raw_1ch/*.npz`
- 其中 471 人有临床标签，443 人满足 TST 不少于 4 小时

用途：后续训练原始 C4-M1 波形 backbone，验证结论不依赖 YASA 特征。

## 已排除且未抽取

- 37 个内部结构损坏或成员损坏的 NPZ。
- 143 个重复 raw NPZ 版本。
- `output/` 下历史 checkpoint、TensorBoard 日志和旧预测。
- `features_yasa/*.txt`，与 NPZ 中 `y` 重复。
- 多份 `annotations.txt/csv`，与 NPZ 标签和筛选表重复。
- `datasets/archive/` 中重复的 0.1.0 临床表。
- 旧模型作者生成的混淆矩阵和结果 CSV。

## 文件位置

- 不可变来源：`data/apples.zip`
- 清洗数据：`data/apples_curated/`
- 完整来源及排除清单：`data/apples_curated/manifest.json`

原始 ZIP 当前保留用于来源追溯、哈希核验和重新清洗。删除它不会改变当前实验，
但属于不可逆的数据来源删除，不建议在专利和论文归档完成前执行。
