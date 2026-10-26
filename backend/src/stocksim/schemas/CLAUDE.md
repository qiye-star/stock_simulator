# schemas/ — 请求与响应模型（给 agent）

## 边界
- 只描述 HTTP 形状。业务校验（用户名字符集、密码长度、不可重复、交易单位等）在 `services/` 或 domain 抛 AppError/DomainError。

## 不变量
- 金额字段名以 `_cents` 结尾，类型为 int。
- 枚举型输入用 `Literal`，与 CHECK 约束一致。
- 下单数量与限价用 `StrictInt`，避免 bool/字符串被静默转换。
- 费率输出为去掉尾零的字符串（见 `SaveOut._rate_text`）。
- 响应模型用 `from_attributes=True` 从 ORM 对象构造；绝不返回 `password_hash`。
- 每个资源一个文件，其他 agent 的模型放在各自的新文件中。

## 文件地图
- `auth.py` RegisterIn、LoginIn、PasswordChangeIn。`user.py` UserOut、MePatch。
- `stocks.py` StockOut。`saves.py` SaveCreateIn、SaveUpdateIn、SaveOut。
- `market.py` QuoteOut、ClockOut、MarketOut（含 total、next_cursor）、StockMarketOut（日 K 与五档）、IntradayOut（当日分时）。
- `orders.py` OrderIn、TradeOut、OrderOut、TradePageOut。`portfolio.py` HoldingOut、PortfolioOut（含 prev_equity/day_pnl）、EquityPointOut、EquityCurveOut。
- `achievements.py` AchievementDefOut、SaveAchievementOut。

## 验证
`uv run pytest tests/integration/test_saves.py tests/integration/test_market.py tests/integration/test_orders.py tests/integration/test_portfolio.py -q`
- `auto_trade.py` 条件单请求/响应（百分比用 float，如 2.5 表示 2.5%，服务层转为 ×100 整数）、运行状态、事件分页。
- `legacy.py` 旧版导出的严格结构模型（已知字段严格类型，未知字段忽略）与导入请求/响应。`debug.py` 调试请求体。

## 预测卡 / 积分 / 情报（02 §10.2）
- `predictions.py`：题目公开形态（`BucketQuestionOut`/`RankQuestionOut`/`BinaryQuestionOut`，按 `kind` 判别）、`PredictionCardOut`、答案入参（`PredictionAnswerIn`，`BucketAnswerIn.probs` 为 StrictInt、`extra=forbid`）、`PredictionAnswerOut {card, clock}`、设置。合法性（合计、候选、长度）在 domain.validate_answers。
- `points.py`：`PointsOut`、`LedgerPageOut`、`PredictionStatsOut`、`TitlesOut`、`TitlePutIn`。`intel.py`：`EdgeRevealIn`、`RumorHintIn`（event_id 正则）、`IntelStateOut`、`IntelPurchaseOut`。EdgeRevealOut / RumorHintOut / EventOut 复用 `events.py`。

## 每日挑战（03 §10.2）
- `challenges.py`：`ChallengeOut`（结算前不含 end_tt/ends_at/seed/salt/commitment_input；`settle_expected_at` 为上界）、`ChallengeRoundOut`（`hold_at`/`event_id` 未到停顿为 null）、`ChallengeEntryOut`、`EntryResultOut`、`ChallengeRoundCardOut`（`event` 为 A 的 `EventOut`，`questions`/`my_answers`/`results` 复用 02 的模型；`results` 元素为 `ChallengeQuestionResultOut`，在 02 的 `QuestionResultOut` 上增加 `peer`、`used`）、`CrowdOut`、`LeaderboardItemOut`、`LeaderboardOut`、`RevealOut`、`ReviewOut`、列表 `ChallengeListOut`、`ChallengeRoundListOut`。
- 请求体：`ChallengeAnswerIn {answers: PredictionAnswersIn}`（extra=forbid，无 resume）；调试 `DebugChallengeEnsureIn`（JSON 键 `date`，字段名 `day`）、`DebugChallengeShiftIn {seconds: 1..86400}`。
- seed 等大整数在 JSON 中为十进制字符串（`RevealOut.market_seed: str`）。

## 真实复盘（模式 E，05 §5.8）
- `replay.py`：`ReplayLevelOut`、`ReplayLevelPageOut`、`ReplaySessionOut`（`level` 为 `ReplayLevelRefOut`，`settled` 为 `ReplaySettledOut` 或 null）、`ReplaySessionPageOut`、`ReplayFeedItemOut`（与 A 的 `NewsOut` 同名字段，`sentiment`/`subtype` 恒为 null）、`ReplayFeedPageOut`、`AdvanceOut`、`ReplayQuestionOut`（`result` 仅计分后）、`ReplayQuestionPageOut`、`ReplayBenchmarkOut`、`RevealOut`（`RevealStockOut` 含真实代码、`RevealEventOut` 在 feed 字段上增加 `impact`、`sentiment`）。
- 请求体：`ReplaySessionCreateIn {level_slug, masked=true, name?}`、`AdvanceIn {to, expected_tick, skip_pending}`、`AnswerIn {probs?, order?}`。
- 关卡包的 pydantic 模型不在 schemas（它不是 API），在 `services/replay/pack.py`。

## 预测市场（04 §9.2）
- `prediction_markets.py`：`PmMarketOut`（rumor 且 open 时 close/resolve 时点为 null）、`PmMarketPageOut`、`PmMarketDetailOut`、`PmQuoteOut`、`PmTradeIn`（extra=forbid；shares 1..200、outcome 0..7）、`PmTradeResultOut`、`PmHistoryOut`、`PmTapePageOut`（匿名）、`PmPositionPageOut`、`PmSettlementPageOut`、调试 `PmDebugVoidIn` / `PmDebugSyncOut`。字段与服务层字典逐一对应；业务校验在 services。
