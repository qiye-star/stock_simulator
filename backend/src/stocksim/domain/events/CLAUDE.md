# domain/events（事件行情纯函数包）— 给 agent 的说明

契约与算法依据：`docs/10.26-plan/01-事件行情.md`（§1 对外契约、§4–§6）。本包零 I/O，遵守 `../CLAUDE.md` 与 `test_purity.py`。

## 边界
- 与引擎的唯一接触点是 `market_engine.advance(..., drift=)`；`market_engine` 不得 import 本包。
- 不读文件：调用方 `json.load` 三份数据（`supply_chain` / `stock_exposure` / `news_templates`）加 `industries`、`stock_pool`，交给 `build_ruleset(...)`。
- 事件不落库，全是 `(seed, ruleset, day)` 的纯函数；漂移只依赖 `(seed, ruleset, 交易 tick, stock_idx)`，可重放。
- 随机只走 `rng.rand_below`，命名空间与 k 段见 `constants.py` 文档字符串；新增随机用途必须另划 k 并更新 `test_events_rng_layout.py`。
- `GameEvent` 的 `magnitude_ppm / knots / expectation / channel / rumor.truth / impacts` 不得原样经 API 外发（01 §1.8）。

## tick 单位
所有“以 tick 计”的常量按参考时钟（20 tick/交易日）定义，经 `timing.scale_ticks / scale_bounds` 按 `EventRuleset.ticks_per_day` 换算（20 时恒等）。`ticks_per_day` 由规则集的 `clock_rules` 经 `domain.clock.timebase` 决定（v1=20，v2=242）；v2 专用取值为 `MAG_SCALE_PPM[2]`、`MAJOR_OFFSET_V2`/`MINOR_OFFSET_V2`（合法偏移集，避开 11:30 与 15:00）、`BULL_BIAS_DRIFT_CAP_PPM[2]`，各分支用字典取值，不在代码中写 `if clock_rules == 2`（`timing.publish_offsets` 的 v1/v2 分支除外）。
`major_period_days(tpd)`：约 240 tick 即一个时钟日（20→12 日，242→1 日）。每日小快讯条数（2–5）与回看/前瞻天数仍以“交易日”计，未随 tpd 缩放。

## 文件
- `constants.py` 全部可调常量（调参只改这里）· `timing.py` tick 换算
- `types.py` `EventRuleset / GameEvent / NodeImpact / NewsItem / RumorInfo / SaveParams / Template…`
- `ruleset.py` `build_ruleset(...)`
- `graph.py` `build_out_edges / build_transmission / save_params / stock_beta_ppm`
- `propagation.py` `propagate(...)`（分层传导）· `path.py` 形状曲线 `*_knots / eval_path / max_step`
- `generate.py` `generate_day(seed, day, ruleset, params)`、`major_days`、`day_slots`
- `plan.py` `build_day_plan`、`plan_window`、`news_window`、`news_between / news_at / news_id`
- `news.py` `render_title / render_news_title` · `reveal.py` `rumor_hint / rumor_status / event_phase`

## 不变量
- 金额无关；比例一律 ppm 整数；每个“事件×股票”对只舍入一次，逐 tick 差分精确相加。
- 单 tick 上限：事件源步长 `IMPULSE_CAP_PPM`，单股漂移之和 `DRIFT_CAP_PPM`（bull_bias 另有更小上限）；保证不触发熔断。
- 发布后改常量或三份数据会改变已开启存档的走势：须提升 `EVENT_RULESET_VERSION` 并冻结旧版（01 §6.6）。开发期可自由改。
- 同日两条重大事件（周期只有 1 日时）发布 tick 必须错开。

## 验证
`cd backend && uv run pytest tests/unit/domain -q -k events`；调参验收：`python3 scripts/event_sim_report.py --seeds 20 --days 300`。
