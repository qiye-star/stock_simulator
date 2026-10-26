# replay_ingest/ — 模式 E 离线数据管道（给 agent）

抓取 AKShare 真实 A 股数据 -> 原始文件落盘 -> 构建关卡包 JSON。**离线工具，运行时服务不得导入本包。**
实施依据：`docs/10.26-plan/05-真实复盘.md` §2、§3。当前完成 E1.1–E1.3 与 E5.1（`collect`/`daily` 定时抓存）；`sentiment`（E6）未实现。

## 边界与不变量
- 只有 `client.py` 允许导入 akshare，且在 `AkshareClient.__init__` 里延迟导入；其余模块只用标准库。`test_purity.py` 用 AST 与子进程双重检查。
- `collect.py` 只用标准库，经 `Gateway` 访问网络（限速、重试、熔断、fetch_log 全部沿用）；运行时服务不得导入本包（抓存容器与运行时镜像分离，见 docs/deployment.md §6b）。
- 不 import `stocksim` 的 models/services/api/db/domain 等任何其它子包（唯一的数据耦合：CLI 读 `data/industries.json` 校验行业标签，找不到则跳过，可用 `REPLAY_INDUSTRIES_FILE` 覆盖）。
- 构建器 `build.py` 不联网、输出逐字节确定：键排序、紧凑分隔符、列表顺序固定；`built_at` 不取墙钟（默认取所读原始文件的最大 `fetched_at`，或 `--built-at`）。
- 金额整数分；价格全程 `Fraction`，只在最后 `round_half_up`（half away from zero，与 `domain/money.py` 同口径，这里自带一份）。
- 复权只用不复权 + 后复权（不用前复权）；以第 0 日前一交易日 T0 为锚，开局价 = 真实价。**因子取分段常数**，不逐日使用 `hfq/raw`（见下“复权实测”）。
- 原始数据不进 git：根目录 `REPLAY_DATA_DIR`，默认 `backend/.replay-data/`（已在 `.gitignore`、`.dockerignore`）。
- 退出码：0 成功；1 业务失败；2 熔断（连续 10 个失败调用）。重试 = 首次 + 3 次退避（2/4/8s + 0–1s 抖动）。

## 文件地图
- `client.py` `AkClient` 协议、`AkshareClient`、`RateLimiter`（按主机最小间隔）、`RetryPolicy`、`Gateway`（限速+重试+熔断+fetch_log）
- `rawstore.py` 原子写、JSONL 追加、读时跳过坏行、路径约定 · `reader.py` 构建时记录读过的文件
- `fetch.py` 按规格增量抓取与落盘（K 线续抓、公告按季度分片、公司动态/新闻联播按日）
- `spec.py` 规格校验、`compute_window` · `adjust.py` 复权 · `bars.py` 日 K -> bar（停牌补齐、flags、越限校验）
- `limits.py` 涨跌幅分段规则与 flags · `rules.py` 公告过滤/归类、新闻联播关键词
- `slots.py` 时间归属 · `events.py` 事件收集/编号/影响 · `redact.py` 脱敏 · `questions.py` 档位与答案
- `build.py` 总装 · `verify.py` 校验与归属抽查
- `collect.py` 定时抓存：`Collector`（电报每 120s 的 全部+重点、个股新闻每 10s 轮转一只、20:30 补抓 `daily`）、`load_universe`（股票池，排除 999999）、去重与归一化
- `cli.py`/`__main__.py` 子命令 `calendar fetch fetch-kline build verify collect daily`

## AKShare 实测列名（akshare 1.19.3，2026-10-26 联网核对）
- `tool_trade_date_hist_sina()`：`trade_date`（`datetime.date`）。
- `stock_zh_a_hist(period="daily")`（不复权 / `hfq`）：日期(date) 股票代码 开盘 收盘 最高 最低 成交量(**手**, int) 成交额(元, float) 振幅 涨跌幅 涨跌额 换手率。
- `stock_zh_index_daily_em(symbol="sh000300")`：英文列 `date open close high low volume amount`（稳定）；`index_zh_a_hist` 在本网络下 `RemoteDisconnected`，仅作备选。
- `stock_zh_a_disclosure_report_cninfo`：代码 简称 公告标题 公告时间 公告链接。**公告时间实测只有日期（`2023-08-30`），没有 `00:00:00` 后缀**；解析同时兼容两种。
- `stock_gsrl_gsdt_em(date)`：序号 代码 简称 事件类型 具体事项 交易日(date)。
- `news_cctv(date)`：`date`(YYYYMMDD) `title` `content`；耗时约 16s/次；周末也有数据。
- `stock_info_global_cls(symbol="全部"|"重点")`：标题 内容 发布日期(date) 发布时间(time)；只返回最新 20 条；**标题可能为空串**（2026-10-26 实测 20 条中 10 条标题为空）。两次调用的数据源相同，“重点”只是按内部等级过滤，输出里没有等级列，所以用键对齐打 `imp` 标记。
- `stock_news_em(symbol)`：关键词 新闻标题 新闻内容 发布时间(字符串 `YYYY-MM-DD HH:MM:SS`) 文章来源 新闻链接；实际只返回最新 10 条；走 `requests`，因此 `HTTP(S)_PROXY` 生效。

## 复权实测（偏离计划 §2.7 处）
- 东财后复权价的逐日因子 `hfq_close/raw_close` **带噪声**：相邻日变化中位数 10–20bp、P99 50–140bp，同日开盘与收盘的隐含因子也不等；`688981`（无分红）则恒为 0。计划里“逐日 f(t)”会让复权日收益带噪声并误报除权。
- 做法：`adjust.detect_ex_days` 只在“因子**上跳** >=120bp 且前后各 5 日中位数之差 >=100bp”时换段（分红/送转/配股都使 hfq/raw 变大，下跳只能是噪声；真实样本：中信 2023-08-25 +191bp、平安银行 2023-06-14 +250bp、东财 2023-04-18 +2039bp、宁德 2023-04-26 +8109bp、茅台 2023-06-30 +152bp 均命中，688981 无误报），每段取中位数。非除权日的复权涨跌幅 = 真实涨跌幅。约 1% 以下的小额分红会漏检（留下 <=1% 台阶）；`build` 把检测到的除权日列为 WARN，作者须对照公告核对。
- 除权日参考价由因子估计，封板容差放宽到 ±30bp、越限校验放宽到 +60bp（普通日仍为 ±1 分、+10bp）。
- 联网端到端实测（临时规格：中信/东财/华泰，d0=2023-08-28）：`fetch`、`build`、`verify` 全部通过；2023-08-28 三只券商均被标为开盘封涨停（flags 含 2），与真实情况一致。

## 定时抓存（E5.1，collect.py）
- 落盘行保留 AKShare 原列名（标题/内容/发布日期/发布时间），构建器 `events.py` 按这些列名读取 cls；另加 `key`、`imp`、`ts_utc`。内容截到 500 字。
- 去重键统一由 `rawstore.cls_key` 计算（抓存与构建器共用）；个股新闻去重键 `sha1(新闻链接)`，按代码与发布月分文件。内存中的去重集合有上限 2000，启动时从本月与上月文件回填。
- 相邻两次电报 `全部` 无重叠 -> `_state/collect_log.jsonl` 写 `gap_suspected`。
- 补抓（`daily`，20:30 北京时间）复用 `Fetcher`，`force=True`，按条执行并与快讯交错，不阻塞 120 秒节奏；完成后 cursor 记 `daily_done`，同一天重启不重跑。
- 环境变量 `REPLAY_COLLECT_UNIVERSE`（`pool` 或逗号分隔代码，默认 pool）、`REPLAY_POOL_FILE`（默认 `stocksim/data/stock_pool.json`）。
- 退出码：`--once` 有失败项返回 1；`--loop` 只在熔断时以 2 结束；SIGTERM 在本轮结束后退出。

## 常见任务
- 新关卡：写 `backend/replay/specs/<slug>.json`（E1.4）-> `fetch --spec` -> `build --spec --out replay/packs/<slug>/v<N>.json --version N` -> `verify --pack`；内容变化必须 `--version` +1，`build` 拒绝覆盖内容不同的已有文件。
- 改了构建逻辑：`UPDATE_GOLDEN=1 uv run pytest tests/ingest -k golden`，人工检查 diff 后提交 `tests/fixtures/replay/pack_min.json`。
- 改了落盘格式：同步 `tests/fixtures/replay/make_replay_fixture.py` 并重新生成夹具。

## 验证
```
cd backend && uv run pytest tests/ingest -q
uv run ruff check src/stocksim/replay_ingest tests/ingest tests/fixtures/replay
uv run --group ingest python -m stocksim.replay_ingest --help
uv export --frozen --no-dev --no-emit-project | grep -ci akshare   # 应为 0
```
