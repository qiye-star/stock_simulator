# 脚本（scripts）

项目级辅助脚本，与后端运行环境无关。

| 脚本 | 用途 |
|---|---|
| `convert_stockdata.py` | 把 legacy 的股票数据转换为后端使用的 JSON |
| `convert_supply_chain.py` | 01a 产业链草稿（markdown 边表）→ `data/supply_chain.json`，可 `--check` / `--to-md` |
| `build_stock_exposure.py` | 生成 `data/stock_exposure.json`（龙头与暴露度），合并 `stock_exposure_overrides.json` |
| `news/` | 事件快讯文案离线流水线，生成 `data/news_templates.json` |
| `event_sim_report.py` | 事件行情仿真调参报告（01 §12.3 指标） |
| `e2e_smoke.py` | 端到端 HTTP 冒烟：注册、建存档、行情、买入、T+1 拦截、持仓、自选、自动交易条件单、导出，以及 v2 时钟一交易日循环（仅标准库） ；事件行情 `s_events`（v2 事件存档：产业链结构、快讯、事件详情、关闭存档 409）；预测卡 `s_predictions`；每日挑战 `s_challenge`（仅 `E2E_CHALLENGE=1`，需 compact 环境，见 `CLAUDE.md`）|
| `pm_prior_report.py` | 预测市场分档公开基率先验（v2 仿真统计，`--check` 与 `BUCKET_PRIOR_PPM` 一致性校验） |
| `pm_abuse_report.py` | 预测市场风控报表（04 §5.5）：读库输出可疑账户 CSV（往返、对倒配对、小号集中、胜率异常）；`--sample` 构造作弊样本自检。只报告不处罚 |
| `clock_v2_sim_report.py` | 时钟 v2 波动标定报告（全量股票池、真实引擎，07 §4.3 指标；`--check` 越界非零退出） |

```bash
python3 scripts/convert_stockdata.py
python3 scripts/convert_supply_chain.py --check
python3 scripts/news/build_templates.py --check
python3 scripts/event_sim_report.py --seeds 20 --days 300

# 先启动后端（需迁移到最新）：
#   cd backend && uv run alembic upgrade head
#   cd backend && ENABLE_DEBUG_API=true uv run uvicorn --factory stocksim.main:create_app --port 18000
BASE_URL=http://localhost:18000 python3 scripts/e2e_smoke.py
```

`e2e_smoke.py` 逐步打印 PASS/FAIL，任一失败以非零码退出。若开局不在交易时段，会调用 `debug/time`（需要 `ENABLE_DEBUG_API=true`）。`BASE_URL` 默认 `http://localhost:18000`。

每日挑战段需服务端以 compact 环境启动，并打开开关：

```bash
DATABASE_URL=sqlite:////tmp/e2e.db CHALLENGE_SCHEDULE=compact CHALLENGE_MIN_ACCOUNT_AGE_HOURS=0 \
  ENABLE_DEBUG_API=true CHALLENGE_SEED_KEY=e2e-key uv run uvicorn --factory stocksim.main:create_app --port 18100
BASE_URL=http://localhost:18100 E2E_CHALLENGE=1 python3 scripts/e2e_smoke.py
```

未设 `E2E_CHALLENGE=1` 时挑战段打印 `SKIP` 且不计入结果。
