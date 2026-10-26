# replay_ingest

模式 E「真实复盘」的**离线数据管道**：从 AKShare 抓真实 A 股数据落盘，再构建成关卡包 JSON。运行时服务不依赖它。设计见 [docs/10.26-plan/05-真实复盘.md](../../../../docs/10.26-plan/05-真实复盘.md)。

## 用法

依赖放在隔离的 `ingest` 依赖组，运行时镜像不含 akshare：

```bash
cd backend
uv run --group ingest python -m stocksim.replay_ingest --help
uv run --group ingest python -m stocksim.replay_ingest calendar                       # 交易日历
uv run --group ingest python -m stocksim.replay_ingest fetch --spec replay/specs/<slug>.json
uv run --group ingest python -m stocksim.replay_ingest fetch-kline --codes 600030,000776 --start 20230501 --end 20231020
uv run python -m stocksim.replay_ingest build --spec replay/specs/<slug>.json \
    --out replay/packs/<slug>/v1.json --version 1                                    # 不联网
uv run python -m stocksim.replay_ingest verify --pack replay/packs/<slug>/v1.json    # 不联网
```

| 子命令 | 作用 |
| --- | --- |
| `calendar` | 抓交易日历 |
| `fetch` | 按规格补齐 K 线（不复权 + 后复权）、基准指数、巨潮公告、公司动态、新闻联播；增量，`--force` 重抓 |
| `fetch-kline` | 单独抓日 K |
| `build` | 规格 + 原始数据 -> 关卡包；同样输入逐字节相同；拒绝覆盖内容不同的已有文件（`--overwrite` 例外） |
| `verify` | 校验包结构、涨跌幅、答案复算、匿名泄露，输出脱敏残留与 `pre_open` 公告归属抽查统计 |
| `collect --once` / `collect --loop [--interval 120]` | 定时抓存财联社电报（全部+重点）与东财个股新闻（每 10 秒轮转一只）；`--loop` 常驻，并在北京时间 20:30 补抓当日公告、新闻联播、公司动态 |
| `daily` | 单次运行当日补抓（容器里由 `collect --loop` 自动完成，也可用于手动补跑） |

退出码：0 成功，1 业务失败，2 熔断。尚未实现：`annotate-sentiment`（E6）。

定时抓存的容器运行方式见 [docs/deployment.md](../../../../docs/deployment.md) §6b（`docker compose --profile collector up -d --build replay-collector`）。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `REPLAY_DATA_DIR` | `backend/.replay-data` | 原始数据根目录（也可用 `--data-dir`） |
| `REPLAY_RATE_<HOST>_MS` | eastmoney 1500、cninfo 3000、cctv 30000、sina 1000 | 同一主机两次调用的最小间隔 |
| `REPLAY_INDUSTRIES_FILE` | `src/stocksim/data/industries.json` | 行业标签清单，用于校验规格 |
| `REPLAY_COLLECT_UNIVERSE` | `pool` | 抓存范围：`pool` 为股票池真实代码（排除 999999），或逗号分隔的 6 位代码 |
| `REPLAY_POOL_FILE` | `src/stocksim/data/stock_pool.json` | 股票池文件（只为 `collect`/`daily` 读取） |
| `HTTP_PROXY` / `HTTPS_PROXY` | — | `requests` 自动读取（东财新闻与财联社经它访问） |

## 原始数据目录

```
$REPLAY_DATA_DIR/
  calendar/trade_dates.json        {"fn","args","fetched_at","akshare_version","rows":["2023-08-25",...]}
  kline/none|hfq/<code>.jsonl      {"d","o","h","l","c","v_lot","amt"}  价格为十进制字符串，成交量单位手
  index/<symbol>.jsonl             {"d","o","h","l","c","v","amt"}
  cninfo/<code>/<yyyy>Q<q>.json    整段文件（含请求参数），一季度一个
  gsrl/<yyyy>/<date>.json          按日；当日无数据 rows 为 []
  cctv/<yyyy>/<date>.json          按日
  cls/<yyyy-mm>/<date>.jsonl       抓存产生（按发布日期分文件）：标题 内容 发布日期 发布时间 + key, imp, ts_utc；构建器可读
  em_news/<code>/<yyyy-mm>.jsonl   抓存产生（按发布月）：关键词 新闻标题 新闻内容 发布时间 文章来源 新闻链接 + key, ts_utc
  _state/fetch_log.jsonl           每次请求一行：ts_utc, fn, args, ok, rows, ms, error（常驻抓存约每天 1.4MB）
  _state/collect_cursor.json       抓存游标：em_index、cls_prev_keys、daily_done
  _state/collect_log.jsonl         event: gap_suspected（电报相邻两次无重叠）
```

写入均为原子（先 `*.tmp` 再 `os.replace`），JSONL 读时跳过坏行。

## 构建器做了什么

- 复权：`adj_x(t) = raw_x(t) · F(t)/F(T0)`，T0 为第 0 日前一交易日；`F` 由 `hfq_close/raw_close` 得到但**取分段常数**（东财后复权因子逐日有噪声，仅在检测到除权跳变时换段，检测到的除权日会作为 WARN 列出供人工核对）；停牌日补齐为前收；`lim_bp` 与 `flags` 用原始价判定；`|c/prev-1| <= lim+10bp` 不满足则构建失败。
- 事件：手写 + 巨潮（过滤例行公告并按标题归类）+ 东财公司动态 + 新闻联播（关键词命中）+ cls；按上海时间归属 `(day_idx, slot)`；每条算相对基准的 `ar_1d_bp`/`ar_5d_bp`。
- 匿名：别名代码 `990001` 起、行业别名（`券商A`）、每只股票固定的价格缩放（第 0 日前收落在 10–50 元）、真名/真代码/年份日期脱敏，残留写入 `redaction_report` 供人工确认。
- 题目：`edges_bp: "auto"` 档位、答案与排序题相关度。

测试与夹具见 `backend/tests/ingest/`、`backend/tests/fixtures/replay/`。
