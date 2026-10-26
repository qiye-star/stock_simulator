# domain/challenge（每日挑战纯函数包）— 给 agent 的说明

契约与算法依据：`docs/10.26-plan/03-每日挑战.md`（§1 对外契约、§3 时间模型、§4 剧本、§5 seed 保密、§8 计分）。本包零 I/O，遵守 `../CLAUDE.md` 与 `tests/unit/domain/test_purity.py`。

## 边界
- 只做常量、公共时间线的 tt 映射、剧本贪心挑回合、seed 派生与承诺、计分与排名。时间（now）、落库、调用 A/B 的行情与出题都在 `services/challenges/`。
- 不 import `services/`；可以 import `domain/clock`、`domain/events`（类型）、`domain/predictions`（题型与 `build_questions` 的结果）、`domain/scoring`、`domain/money`。
- 时间一律 epoch 毫秒整数；seed 与盐由服务层生成后传入（本包不取随机数）。`date` 只用于 ISO 周键，不调用 now。
- 时钟固定 v2（`CHALLENGE_CLOCK_RULES = 2`，`N_TPD = 242`）。停顿点必须 `holdable_v2`（偏移不是 120/241）。

## 文件
- `constants.py` 全部可调常量（回合数、时段 tick 上限、快放 tick 毫秒、奖励表 06 §4.3、承诺前缀）。调参只改这里。
- `timeline.py` `Timeline`、`build_timeline`、`target_tt`、`reached_ms`、`phase_at`、`minutes_to_tt`。
- `script.py` `MajorRef`、`RoundPlan`、`holdable_v2`、`major_ref`（由 GameEvent 与题目派生判定点）、`plan_rounds`（贪心挑回合）。
- `commit.py` `derive_seed`、`commitment_input`、`make_commitment`、`verify_commitment`、`sha256_hex`。承诺原文格式是对外契约，改动须升版本前缀。
- `scoring.py` `question_results`（同伴分 / 基线分）、`trade_scores`（交易同伴差，封顶 ±100）。
- `ranking.py` `competition_ranks`、`top_share_cutoff`、`reward_points`、`iso_week_key`。

## 不变量
- `minutes_to_tt` 返回全局 tick（分钟）数；只有交易分钟使 tt 加一，午休与隔夜瞬间跨过。与 `clock.v2_tick_of` 闭式逐值一致（测试覆盖）。
- `target_tt` 单调不减；`reached_ms(target_tt(t)) ≤ t`（t ≥ resume_1）；`target_tt(reached_ms(tt)) == tt`。
- `plan_rounds`：候选 trigger ≥ warmup、holdable，且同 tick 无另一条重大事件；相邻停顿 ≥ min_gap；每段快放 ≤ max_burst；resolve > hold；end_tt ≤ max_tt。非回合重大事件允许存在。
- 奖励只在 `reward_points` 内计算；“答过至少 1 回合或有成交”的门槛由服务层判定后传 rank=None。
