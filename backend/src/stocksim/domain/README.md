# 领域层（domain）

纯 Python 的游戏规则与行情引擎：撮合、涨跌停、T+1、手续费、自动交易、成就判定，以及确定性的行情生成。
不依赖数据库、网络或系统时钟，同样的输入永远得到同样的输出，因此可以被单元测试充分覆盖。

## 快速开始
```bash
cd backend
uv run pytest tests/unit/domain -q
```

## 目录

| 路径 | 作用 |
|---|---|
| `money.py` | 整数分的四舍五入、手续费、元与分转换 |
| `rng.py` | 确定性 splitmix64 随机数（行情的唯一随机源） |
| `clock.py` | 交易时段、游戏分钟推进、跳过时间 |
| `rules.py` | 涨跌停、熔断、T+1、交易数量校验 |
| `market_engine.py` | 行情初始化、逐 tick 推进、五档盘口 |
| `matching.py` | 单笔订单撮合（手动与自动共用） |
| `types.py` | 账户、持仓、行情快照、订单与成交记录的数据结构 |
| `errors.py` | `DomainError` 与错误码常量 |
| `events/` | 事件行情：事件生成、产业链传导、每 tick 漂移计划、快讯文案（纯函数） |
| `challenge/` | 每日挑战纯函数：常量、公共时间线、剧本贪心挑回合、seed 承诺、计分与排名（见 `challenge/CLAUDE.md`） |
| `prediction_market/` | 预测市场纯函数：LMSR 定价取整（decimal）、回合事件合约与结算判定、下单限额（见 `prediction_market/CLAUDE.md`） |
| `auto_trade/` | 自动交易的条件判断与执行 |
| `achievements/` | 成就目录、统计与判定 |

## 接口
公共函数清单见 [CLAUDE.md](CLAUDE.md) 中的 API 表。服务层（services）通过这些函数读写状态，
本层不保存任何状态；状态（行情、持仓、成交）由服务层持久化。

## 设计要点
- 金额全部是整数分，费率是 `Decimal`。
- 行情使用计数器式随机数，`(seed, tick)` 唯一决定结果，便于回放与对拍。
- 限价单按市价成交（修复了 legacy 按限价成交的问题），不成交时明确报错。
- 成就统计只依赖成交记录中的快照字段，不依赖当前行情。

- 真实复盘的纯函数 `replay.py`：阶段位置、事件可见性、按关卡包缩放的显示价、阶段报价与标志位、收益率（05 §5.4）。
