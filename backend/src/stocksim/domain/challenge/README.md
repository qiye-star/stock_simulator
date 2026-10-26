# domain/challenge（每日挑战纯函数）

每日挑战的常量、公共时间线（真实时间 ↔ 交易 tick）、剧本贪心挑回合、seed 派生与承诺、计分与排名。纯函数，不依赖数据库与系统时钟。

| 模块 | 作用 |
|---|---|
| `constants.py` | 挑战全部可调常量 |
| `timeline.py` | 公共时间线：tt(now)、到达时刻、相位、分钟推进步数 |
| `script.py` | 重大事件 → 回合（贪心）；停顿点可下单判定 |
| `commit.py` | HMAC 派生 seed；sha256 承诺与校验 |
| `scoring.py` | 同伴分、基线分、交易同伴差 |
| `ranking.py` | 竞赛排名、奖励积分表、ISO 周键 |

详细契约见 `docs/10.26-plan/03-每日挑战.md` 与 [CLAUDE.md](CLAUDE.md)。
