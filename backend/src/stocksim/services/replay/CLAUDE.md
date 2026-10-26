# services/replay/ — 真实复盘服务（模式 E，给 agent）

实施依据：`docs/10.26-plan/05-真实复盘.md` §5。本包被 `services/market.py`、`trading.py`、`stocks.py`、`saves.py` 等**函数内延迟导入**，不得被顶层导入（会循环）。

## 文件
- `pack.py` 关卡包模型（pydantic，`extra="forbid"`，字段与 replay_ingest 构建器输出一致）与 `check_pack` 跨字段校验；`pack_sha256` 对原始 JSON 的规范化形式计算。
- `levels.py` 导入（`import_pack` 幂等、同版本内容变化拒绝）、启动导入 `import_bundled_packs`、`get_pack`（按版本 LRU，32 条）、列表与详情（防剧透的 `level_out`）、`my_best_by_level`。
- `state.py` 只读上下文 `Ctx`（会话 + 解析后的包 + 游戏日 + 阶段 + 匿名标志）；`build_state` 产出与 `decode_state` 同形的行情状态（含 `_replay` 元信息与每只股票的 `limit_pct_bp`、`replay_flags`）；`stock_info`；假日历 `fake_date`（2001-01-01 起连续工作日）与 `date_label`（匿名 `T±k`）。
- `views.py` 个股详情（K 线只到已过的日；open 阶段当日只有开盘点）、分时（open 一点，close 之后两点）、基准指数（只到当前已收盘日）。
- `feed.py` 事件流。**`to_feed_item` 是唯一的 A 快讯适配点**，字段与 `schemas/events.NewsOut` 同名。`visible_at` 用 domain 的 `event_visible` 过滤，并去掉 `hide_in_masked`、回看期超过 10 日的非重要事件。游标为事件序号（新的在前）。
- `predictions.py` 题目视图（`question_out`，答案仅在计分后以 `result` 给出）、作答校验（`build_answer`）、计分（`score_question` / `score_due`，只调用 `domain/scoring`）、积分换算（匿名 ×1.0、实名 ×0.5）。
- `sessions.py` 建会话（`create_session`）、推进（`advance`，`_advance_once` 在 `run_in_transaction` 内循环）、结算（`_settle`）、结束（`finish`）、作答（`answer`）、列表与视图（`session_view`）。
- `reveal.py` 揭示页（未结算 → `REPLAY_REVEAL_LOCKED`）。
- `cli.py` 手动导入：`python -m stocksim.services.replay.cli import <文件或目录>`。

## 不变量
- **防剧透**：所有读取都经 `state.py` / `feed.py` / `views.py` 的阶段过滤（`domain.replay.event_visible`、`visible_quote`），关卡包（含答案、真实代码）只在服务端。揭示页之前的任何响应都不得含真实代码、真实名称或真实日期（匿名下）。
- **推进**：`save.trading_day = 游戏日`、`save.clock_minute ∈ {540,570,900,960}`、`save.tick = day*4 + 阶段序号`；离开收盘阶段写当日权益快照；`expected_tick` 不符 → `stale=true` 且不推进。结算后 `clock_minute=960`，`trading_day=play-1`，`tick=play*4`。
- **结算**：剩余题计分（未答记 0 分、标记 `skipped`）；`final_equity` 按最后可见价估值；`excess_bp = return_bp − benchmark_return_bp`；与推进同一事务。
- **积分**：幂等键 `replay:{user_hex}:{level_hex}:{qid}`，`ref=replay:{save_hex}:{qid}`；只有 `is_first_attempt` 入账；`credit` 只 flush，提交由 `run_in_transaction` 负责。
- **导入**：`(slug, version)` 的 sha256 相同跳过，不同拒绝；当前版本指向最高版本；`status`（retired）导入时不改写。
- 会话上限按 `MAX_REPLAY_SESSIONS_PER_USER` 计（含已结算），与普通存档分开。

## 验证
`cd backend && uv run pytest tests/integration/test_replay_*.py tests/unit/domain/test_replay.py -q`
