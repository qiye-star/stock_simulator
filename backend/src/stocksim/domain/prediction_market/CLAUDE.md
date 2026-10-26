# domain/prediction_market（预测市场纯函数）— 给 agent 的说明

契约与算法依据：`docs/10.26-plan/04-预测市场.md`（§3 合约、§4 LMSR、§5.5 限额、§11.1 测试、§12 步骤 1–3）。本包零 I/O，遵守 `../CLAUDE.md` 与 `test_purity.py`。

## 边界
- 只做定价、取整、合约生成、结算判定、限额判定。不读写数据库、不取墙钟；频率限制、账号年龄、超前锁定、滑点、状态迁移都在服务层。
- 只市场“回合事件”：调用方用 `contracts_for_challenge(..., round_event_ids=...)` 过滤；`contracts_for_event` 不做回合过滤。
- 出题口径（窗口、档位边界）只调 `domain.predictions`（`DIRECTION_WINDOW_DAYS`、`bucket_edges_bp`、`Structure`），不得在此重算。判定用 `domain.scoring.bucket_of`。

## 数值规则（硬约束）
- LMSR 账本量全部用 `decimal`，在 `LMSR_CTX`（prec=50，半偶舍入）内计算，每个公开函数自己进入 `localcontext`。**禁止 float**：`math.exp/log` 依赖平台 libm，会让 ceil/floor 在整数边界翻转。
- 买入花费：先 `quantize(1e-12)` 再向上取整，至少 1 积分；卖出回款：先量化再向下取整，可为 0（服务层拒绝 0）。
- `prices_ppm` 用最大余数法，和恰为 1_000_000；平分取小下标。ppm 取整可让尾部选项摆动 1 ppm，所以单调性只在 ±1 ppm 内成立（展示用，成交只看整数积分）。
- `b_milli`、`q` 为整数；`b = b_milli/1000`。不在交易中动态调 b（破坏路径无关与亏损上界）。
- 合约 spec 只含公开字段（kind、scope、源行业/股票、sentiment、首次出现 tick）。不得读取 `magnitude_ppm/knots/expectation/impacts/rumor.truth` 来决定 spec；真值只在 `resolve_rumor` / `resolve_bucket` 的输入里出现。

## tick 换算
- 所有 tick 经 `domain.clock.timebase(clock_rules)` 取 `first_tt(day)` / `day_of`；`MIN_OPEN_TICKS`、`RUMOR_CLOSE_LEAD_TICKS` 按 `clock_rules` 字典取值。挑战固定 v2（242 tick/日），v1 对照仅用于测试。
- bucket：`open=f`，`close=first_tt(to_day)`（最后交易日开盘即停，盲盘），`resolve=first_tt(to_day+1)`；`f = min(news.trading_tick)`，窗口锚定 `day_of(f)`，不锚定发布日。
- rumor：`cap = min(r, last_tt+1)`，`close = cap − lead`，`resolve = cap`；不因揭晓晚于挑战而过滤。

## 文件
- `constants.py` 全部可调常量（份额/兑付、SUBSIDY_TIERS、限额、MIN_OPEN、先验）。`BUCKET_PRIOR_PPM` 由 `scripts/pm_prior_report.py` 统计写入，`--check` 校验一致。
- `types.py` `ContractSpec / Quote / LimitState`
- `lmsr.py` `cost_points / prices_ppm / buy_cost / sell_proceeds / max_shares_for_budget / quote / b_for_subsidy / max_loss_points / subsidy_for`
- `contracts.py` `ContractContext / contracts_for_event / contracts_for_challenge / resolve_rumor / resolve_bucket / bucket_prior`
- `limits.py` `check_trade`（越限抛 `DomainError`，码见模块内 `PM_*` 常量）、`market_cap_points`

## 不变量（测试守护，见 tests/unit/domain/test_pm_*.py）
- 价格和为 1_000_000；买 i 后 p_i 不降、其余不升（±1 ppm）。
- 往返：卖出回款 ≤ 同笔买入花费；拆单：整笔花费 ≤ 拆分之和；闭环净收益 ≤ 0。
- 补贴上界：`S + Σ买 − Σ卖 − 100·(q_i − q0_i) ≥ 0` 对所有 i、每一步成立；`max_loss_points(b, q0) ≤ S`。
- 金值表（`GOLDEN_EXPECTED`、§4.4 表格、全套 102、往返 217/216）是跨平台可复现性的契约，不得为过测试而改。
- `max_shares_for_budget` 精确：`buy_cost(n) ≤ B < buy_cost(n+1)` 或 `n == cap`。

## 注意
- 尾部选项（概率趋于 0）的买入花费会落到下限 1 积分；单笔 ≤ 200 份，服务层的频率与单场额度限制必须存在，否则可批量低价买入尾部份额（补贴上界仍成立）。
- `subsidy_for` 只决定 S；S 写入市场行的 `subsidy_points` 后不再变化。

## 验证
`cd backend && uv run pytest tests/unit/domain/test_pm_lmsr.py tests/unit/domain/test_pm_contracts.py tests/unit/domain/test_pm_limits.py tests/unit/domain/test_purity.py -q`
