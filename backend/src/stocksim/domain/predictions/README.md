# domain/predictions

预测卡（模式 B）的纯函数：题型（方向+幅度、产业链冲击排序、传闻真假）、出题与真值口径、答案校验、用户级称号目录。

- 设计依据：`docs/10.26-plan/02-预测卡.md`。
- 常量集中在 `constants.py`，积分经济数值也在此（06 §4.3 建议值）。
- 计分函数在上一层的 `domain/scoring.py`；积分与落库在 `services/points.py`、`services/predictions.py`。
