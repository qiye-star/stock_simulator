# domain/predictions（预测卡纯函数包）— 给 agent 的说明

契约与算法依据：`docs/10.26-plan/02-预测卡.md`（§1 对外契约、§4 题型与出题、§8 称号）。本包零 I/O，遵守 `../CLAUDE.md` 与 `test_purity.py`。

## 边界
- 只做题型、出题、真值口径（理论冲击）、答案校验与称号判定；积分、落库、时间推进都在 `services/`。
- 所有随机只经 `rng.rand_below`，诱饵抽样的 tick 为 `PREDICTION_TICK_BASE − 排期日`，idx = 槽位，k = 第 j 个诱饵（见 `rng.py` 文档字符串）。
- 公开 JSON（`to_public()`）只含白名单字段（dir：qid/kind/target_kind/target/target_name/edges_bp/from_day/to_day；rank：qid/kind/k/exclude/candidates/at_day；rumor：qid/kind）。`RankQ.tt_end` 只在服务端结算时用，不外发。

## 文件
- `constants.py` 全部可调常量（噪声 σ 的 v1/v2 参数、档位下限、排序题参数、积分经济：欢迎 200、预测日上限 1000、情报价 100/200/80、每日 8 次；称号阈值）。调参只改这里。
- `types.py` `BucketQ / RankQ / BinaryQ`（`to_public()`）。
- `questions.py` `Structure`、`QuestionContext`、`bucket_edges_bp`（§4.1 公式，clock_rules=1 时与原式逐位相同）、`impact_at`、`rank_truth` / `resolve_rank`、`build_questions`、`validate_answers`。
- `titles.py` `TITLE_CATALOG`（11 条）、`ScoredAnswer/ScoredCard`、`compute_title_stats`、`evaluate_titles`。

## 不变量
- 档位只依赖公开的 n、窗口、目标类型、时钟版本，不依赖事件的 M（不泄密）。v1 与 v2 的档位表与 02 §4.1 一致（`test_prediction_questions.py`）。
- 排序题：候选 = 真受影响前 `RANK_TRUE_MAX` 个（冲击降序、下标升序）+ 诱饵；**诱饵池排除全部真受影响行业**（而非仅排除入选的前 5 个），保证真前三一定在候选内（见 `services/` 的说明）。候选按行业下标升序输出。
- 题目 JSON 出卡后固化，结算只读它与事件（`events_for_days(include_unpublished=True)`）。

## 验证
`cd backend && uv run pytest tests/unit/domain -q -k "scoring or prediction"`
