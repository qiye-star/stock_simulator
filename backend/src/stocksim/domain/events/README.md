# domain/events（事件行情）

游戏内事件（公告、新闻、政策、突发、传闻）的确定性生成，以及沿产业链传导到个股的每 tick 漂移。
全部是纯函数：同样的 `(seed, 规则集, 交易日)` 永远得到同样的事件与漂移，事件本身不落库。

## 数据流

```
data/*.json --(调用方 json.load)--> build_ruleset --> EventRuleset
seed + ruleset --> save_params --> SaveParams（按存档抖动）
generate_day(seed, day, ruleset, params) --> GameEvent（含传导结果 impacts 与快讯 news）
build_day_plan(day, 窗口内事件, ruleset, params) --> 20 个 {stock_idx: drift_ppm}
market_engine.advance(state, seed, tick, minute, drift=plan[offset])
```

## 用法示例

```python
from stocksim.domain.events import (
    build_ruleset,
    save_params,
    generate_day,
    build_day_plan,
    plan_window,
)

ruleset = build_ruleset(
    supply_chain=..., exposure=..., templates=..., industries=..., stock_pool=...
)
params = save_params(seed, ruleset)
window = [e for d in plan_window(day) for e in generate_day(seed, d, ruleset, params)]
plan = build_day_plan(day, window, ruleset, params)
drift = plan[trading_tick % ruleset.ticks_per_day]
```

服务层需要自己缓存 `generate_day` 与 `build_day_plan`（按 `(seed, 版本, 日)`），本包不保存状态。
调参与验收见 `scripts/event_sim_report.py`；设计依据见 `docs/10.26-plan/01-事件行情.md`。
