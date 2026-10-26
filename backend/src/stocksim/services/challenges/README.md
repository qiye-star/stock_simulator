# services/challenges（每日挑战服务层）

模式 C 的服务层：每天一场挑战，全服共用一份 master 行情（无主存档），每位报名者的玩家存档只镜像 master 的时间与行情来源。

| 模块 | 作用 |
|---|---|
| `generate.py` | 派生 seed、按剧本质量筛选、建 master 与挑战行、作废 |
| `sync.py` | 按公共时间线推进 master（停顿点出题、题目判定点判定）、玩家镜像、下单前同步 |
| `runner.py` | 触发：`run_due` 六步（生成、开始、推进、关闭钩子、结算、清理）与懒触发节流 `maybe_run_due` |
| `shift.py` | 调试用时间平移（`POST /debug/challenges/{id}/shift`） |
| `entries.py` | 报名（每人每场一份玩家存档，不占普通存档上限） |
| `rounds.py` | 回合出题、作答、判定与计分 |
| `settle.py` | 结算：终局权益、交易分、总分、合格者排名、奖励入账、置 settled |
| `boards.py` | 日榜、周榜、总榜（只含公开字段） |
| `clock.py` | 由回合行重建公共时间线（缓存） |
| `registry.py` | 挑战、master、报名、回合的查询 |
| `hooks.py` | 生成、作废、回合打开/关闭、题目判定、结算的扩展点 |
| `policy.py` | 对预测卡服务声明挑战存档不出卡 |
| `timeutil.py` / `config.py` | 时间（UTC+8 固定偏移）与配置入口 |
| `views.py` | 对外 dict 的唯一出口（REST 与 WS 共用）：挑战、回合卡、报名、复盘、reveal（结算或作废后公开 seed） |

对 D 的契约函数（03 §1.7）在 `registry.py`，与 `ChallengeInfo` 一起。

规则与口径见 `docs/10.26-plan/03-每日挑战.md`；实现约束见 [CLAUDE.md](CLAUDE.md)。
