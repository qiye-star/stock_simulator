# services/challenges/ — 每日挑战服务（给 agent）

模式 C（每日挑战）的服务层，实现 `docs/10.26-plan/03-每日挑战.md` §7。已完成 C3–C10：配置与生成、推进与镜像、报名与回合、结算与排行、给 D 的契约函数、runner/CLI（C8）、REST 所用的视图与平移（C9）、WS 的 challenge 帧与时钟覆盖（C10，`views.clock_overrides`，由 `market.clock_view` 按 mode 调用）。契约（API、错误码、表名）以 03 为准，本目录不是契约来源。

## 边界
- 公式只来自 `domain/challenge/`（时间线、剧本、承诺、计分）与 `domain/predictions/`、`domain/scoring.py`（B）。本目录不另写公式。
- B 的接口只在 `rounds.py` 适配（`structure_for`、`change_bp_for`、`validate_answers`、`build_questions`、`resolve_rank`）。
- 推进只经 `market._run_ticks`，不直接改 `save.tick` / `clock_minute`（v2 对齐不变量）。
- 取当前时间只经 `timeutil.now()`；配置只经 `config.current_settings()`（`create_app` 登记本应用的 Settings）。
- 钩子（`hooks.py`）运行在调用方事务内，**不得 commit**，必须幂等。
- 结算（C6）：成绩字段确定可重算；积分只经 `points.credit(reason="challenge", idempotency_key=f"challenge:{cid}:{uid}")`，delta=0 不入账但 `points_awarded=0` 照写。`run_settled` 在写 status 之前；status 最后一个事务才改（乐观锁冲突即重做，已非 running 返回 False）。
- 奖励：仅 `eligible` 且（答过 ≥1 回合 或 有成交）的报名发放 `reward_points(rank, eligible_count)`（参与 50；前 10% +100；前三 +300/200/100，见 `domain/challenge/constants.py`，06 §4.3 建议值，偏离 03 §8.4）。
- 排行口径：日榜只含合格报名；周/总榜只含 settled 挑战的合格报名（缺席计 0）。名次只在服务层算，不用 `points.totals_by_user`。
- 读 master 行情前（§1.7 的 `public_event`/`reference_change_bp`/`challenge_events`）先经 `sync.advance_master` 推到 tt(now)（会 commit）。
- `__init__.py` 不重导出子模块：`market` / `trading` / `saves` 在函数内延迟导入 `sync`、`views`，顶层导入会循环。§1.7 名字经模块级 `__getattr__` 惰性解析，不在导入期触发循环。

## 不变量
- master（`mode='challenge_market'`，`user_id` 为空）永不被用户接口访问；玩家存档（`mode='challenge'`）只镜像 master 的 `tick / clock_minute / trading_day / paused`，**永不超前**。
- `paused = phase ∉ {burst, final}`。挑战存档不走墙钟补推与 v2 调度，`market._advance_to_now_once` 在 `paused` 判断之前分发到 `sync.sync_entry_save`。
- 推进在每个 `hold_tt` 与每题 `resolve_tt` 处精确停下（同一事务）：先 `rounds.materialize_round`（出题，`opened_at` 为幂等键）并触发 `RoundOpenHook`，再 `rounds.resolve_question`（判定，`outcomes[qid]` 为幂等键）并触发 `QuestionResolvedHook`。
- 题目与回合由 seed 与回合事件确定，重放幂等；服务端 `QuestionSpec` 每次由 `build_questions` 重算，不依赖 `questions` JSON。
- 作答截止（`closes_at`）与可见性（`hold_at`）按真实时间判断，调用方传入的 `now` 为准。未到停顿的回合对玩家返回 `CHALLENGE_ROUND_NOT_FOUND`。
- 修改次数：`existing.revision >= CHALLENGE_MAX_REVISIONS` 时拒绝（`CHALLENGE_ANSWER_LIMIT`）。
- 判定结构：`outcomes[qid]` 为 `{"outcome_bucket","change_bp"}` / `{"relevance"}` / `{"truth"}`，dir 真值为 None 时 `{"void": true}`。`challenge_answers.results[qid]` 为 `{"raw","uniform_score","baseline","peer","score","used"}`，作废题为 `{"void": true, "score": 0}`。`round_score` 为各题 `score` 之和。
- 日志只记 `challenge_date`、`seed_attempt`、`seed_commitment`；不得出现 seed、盐、`commitment_input`（caplog 测试）。
- 懒触发节流只在本层（`runner.py`），`domain` 不得 import time。`run_due` 每步独立事务、可重入；清理每次合计 ≤ 50 个存档，先删玩家存档（`challenge_entries.save_id` 置空），再删 master（`challenges.master_save_id` 置空）。
- 报名错误码：scheduled → `CHALLENGE_NOT_STARTED`；settled 或 running 且已过终局 → `CHALLENGE_ENDED`；其它（含 void、过截止）→ `CHALLENGE_ENTRY_CLOSED`。
- 视图保密（03 §5）：回合的 `event_id/hold_at`、题目在 `now < hold_at` 前不输出；`crowd` 只在 `now ≥ closes_at` 后、只统计合格报名；`ChallengeOut` 无 end_tt/ends_at/seed/salt/commitment_input。
- 生成的 seed 派生密钥：`CHALLENGE_SEED_KEY`（UTF-8）优先，否则 `HMAC(SECRET_KEY, "stocksim/challenge-seed-key/v1")`。
- `compact` 调度只允许 `ENABLE_DEBUG_API=true`（`create_app` 检查）。

## 文件地图
| 模块 | 职责 |
| --- | --- |
| `__init__.py` | 包说明（不重导出） |
| `timeutil.py` | `now()`（测试 monkeypatch 此处）、`to_ms/from_ms`、`local_date`（固定 UTC+8）、`slot_to_utc`、`parse_slots`、`ceil_5s`、`iso_week` |
| `config.py` | `use_settings`（create_app 登记）、`current_settings` |
| `clock.py` | `timeline_of`（由 rounds 与 challenges 行重建 `Timeline`，按 `(id, version)` 缓存）、`tt_at`、`reached_at`、`phase_at` |
| `registry.py` | 查询；03 §1.7 给 D 的契约函数（`get_challenge`、`live_challenges`、`round_event_ids`、`public_trading_tick`、`real_time_of`、`challenge_events`、`public_event`、`reference_change_bp`、`knowledge_trading_tick`、`expected_participants`）与 `ChallengeInfo` / `info_of`；`promote_if_due`（scheduled→running 懒迁移）、`market_save_for`、`challenge_of_save`、`entry_for`、`rounds_of`、`round_by_index`、`visible_rounds` |
| `settle.py` | 结算（03 §7.6）：`settle_if_due` 推到 end_tt → 只读计算成绩与排名 → 每 200 人一个事务写成绩与积分 → 最后事务跑 `run_settled` 钩子并置 settled |
| `boards.py` | 日榜 `day_board`（settled 后，合格报名，标准竞赛排名）、周榜/总榜 `period_board`（合格报名求和，`sort=avg` 需 ≥5 天）；游标 base64url `[score, username]`，`me` 不受页限制 |
| `generate.py` | `seed_key`、`ensure_challenge`（剧本筛选 64 次、单事务建 master + 行情 + 挑战 + 回合，唯一键冲突回滚重读）、`void_challenge` |
| `rounds.py` | `event_of`、`round_specs`、`resolve_tt_of`、`materialize_round`、`answer_round`、`resolve_question` |
| `sync.py` | `advance_master`（检查点推进）、`sync_entry_save`（镜像，先调 `runner.maybe_run_due`）、`before_trade`（下单前同步；`ended` 抛 `CHALLENGE_ENDED`） |
| `entries.py` | `join`（报名，`created` 返回值；已报名幂等） |
| `hooks.py` | 03 §1.3 的全部钩子类型与注册、`run_*` 调用入口；`register_defaults`（当前为空） |
| `policy.py` | B 的 `CardPolicy`：挑战存档不出卡、不发积分、不给情报 |
| `runner.py` | `run_due(session_factory, now)`（六步：生成今日/明日、开始、推进、关闭钩子、结算、清理；每步独立短事务，单步失败记日志并计入 `RunReport.errors`）；`maybe_run_due(db_or_factory, now)`（进程内 monotonic 节流 `CHALLENGE_RUN_DUE_MIN_INTERVAL_S`，失败只记日志）；`reset_throttle()`（create_app 调用） |
| `shift.py` | `shift_challenge(db, id, seconds)`：调试用，把挑战全部时刻前移（已结算/作废 409 `CHALLENGE_ENDED`）；时间线缓存靠 `version_id_col` 自动失效 |
| `views.py` | 对外 dict 的唯一出口：`challenge_out`、`round_out`/`round_card_out`（保密规则逐条落实）、`entry_out`/`entry_result_out`、`review_out`、`reveal_out`（settled 与 void 可用）、`export_challenge_block`；`phase_of`（`next_change_at` 只在 before/hold 给出，burst 的 hold_at 与 final 的 ends_at 保密为 None）、`round_state`、`is_visible`；`clock_overrides`（ClockOut 的挑战覆盖，03 §3.2） |

## 公共函数（供后续段调用）
- `generate.ensure_challenge(db, day: date, *, now, settings=None) -> Challenge`；`generate.void_challenge(db, ch, reason) -> Challenge`；`generate.seed_key(settings=None) -> bytes`
- `sync.advance_master(db, ch, now) -> int`；`sync.sync_entry_save(db, save, now) -> int`；`sync.before_trade(db, save) -> None`；`runner.run_due(session_factory, now) -> RunReport`；`runner.maybe_run_due(db_or_factory, now) -> bool`；`runner.reset_throttle()`；`shift.shift_challenge(db, id, seconds) -> Challenge`
- `entries.join(db, ch, user, now) -> tuple[ChallengeEntry, bool]`
- `rounds.materialize_round(db, ch, master, rnd, now) -> bool`（首次打开返回 True，调用方据此触发 `hooks.run_round_open`）；`rounds.answer_round(db, ch, master, entry, round_index, answers_in, *, now, round_row) -> ChallengeAnswer`；`rounds.resolve_question(db, ch, rnd, qid, master, *, now) -> None`
- `registry.*`、`clock.*` 见上表。
- `hooks.register_challenge_hooks(on_created, on_revoked)`、`register_round_open_hook`、`register_round_closed_hook`、`register_question_resolved_hook`、`register_settled_hook`、`clear_hooks()`
- `settle.settle_if_due(db, ch, now) -> bool`（幂等；未到期、已结算、作废返回 False）；`settle.SETTLE_BATCH = 200`
- `boards.day_board(db, ch, *, board, limit, cursor, viewer_id) -> dict`；`boards.period_board(db, *, scope, week, sort, limit, cursor, viewer_id, now) -> dict`
- `views.reveal_out(db, ch) -> dict`（未结算抛 `CHALLENGE_NOT_SETTLED`）；`views.entry_result_out(entry, eligible_count) -> dict | None`
- §1.7（`registry`，也可 `from stocksim.services import challenges` 后 `challenges.get_challenge(...)` 惰性解析）：`ChallengeInfo` 含服务端专用 `timeline`（void 为 None）；`public_trading_tick(info, now)` 不读库；`real_time_of(info, tt)`；`reference_change_bp(db, ch, scope, subject, from_day, upto_tt)`（换日 tick 取 day−1 收盘，其余只允许等于当前公共 tt，否则 ValueError）；`public_event(db, ch, event_id, lang, at_tt)`；`knowledge_trading_tick`；`expected_participants`

## 常见任务
- 改时段或时间预算：只改 `domain/challenge/constants.py` 与 `config.py`，并重跑 `tests/integration/test_challenge_lifecycle.py -k generate`。
- 新增判定或计分：改 `rounds.py::_truth` / `_raw_scores` / `_score_question`，保持 `results[qid]` 结构不变。
- 新增挑战存档操作：在 `market.reject_challenge(save, feature)` 登记，feature 取值需在 03 §10.3 登记。

## 验证
`cd backend && uv run pytest tests/integration/test_challenge_*.py -q`（C8 起含 `test_challenge_runner.py`；HTTP 全流程在 `test_challenge_lifecycle.py`）
