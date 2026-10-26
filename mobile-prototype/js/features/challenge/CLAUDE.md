# js/features/challenge/ — 每日挑战（⑦ C）

对应 `docs/10.26-plan/03-每日挑战.md` §10（REST / schemas / 错误码 / WS）与 `08-手机端.md` §5.7；画板 Play / Leaderboard / Predict。只做手机端，不改 `frontend/` `backend/`。

## 文件
| 文件 | 职责 |
| --- | --- |
| `model.js` | `SS.challengeModel`（纯函数，`tests/` 在 vm 里加载）：`skewOf`、`countdown`、`formatDuration`、`timeline`（阶段/回合/倒计时）、`roundBar`、`primaryAction`（08 §5.7 按钮表）、`boardRows`/`boardHeaders`、`resultStats`、`answerLines`/`resultLines`、`crowdText`、承诺解析 `parseCommitmentInput`、`digestMatches`、`seedMatches` |
| `mock.js` | `SS.mockFeatures.challenge`：今日（running，第 2 轮可答，未参加）与昨日（settled，可复盘）；作答/参加只在内存里 |
| `store.js` | `SS.store` 上的挑战方法，mock 与 real 两套同名（`SS.assertSameKeys`）；`resetChallenge()` 共用。real 经 `guarded()`（404/405/501 → `FEATURE_UNAVAILABLE`） |
| `flow.js` | `SS.challengeFlow`：`refresh()`（today + 运行中的回合卡 → `challenge:update`）、`enter(id)`、`leave()`、`needsRefresh(tl, lastAt, now)`（到点节流 3 秒） |
| `verify.js` | `SS.challengeVerify.run(reveal)`：`crypto.subtle` 计算承诺原文的 sha256，结果 `ok / fail / unavailable / invalid` |
| `ui.js` | `SS.challengeUi`：回合条、答案/结果摘要、得分行、排行表头与行、公平性卡、`bindVerify` |
| `play-card.js` | `SS.challengeCard`：玩法页挑战卡（`mount`）、挑战存档的行情横幅（`mountBanner`） |
| `challenge-page.js` | `SS.pages.challenge`（`#/challenge`）：状态卡、参加、当前回合（复用预测卡）、本场各轮、往期 |
| `board-page.js` | `SS.pages.challengeBoard`（`#/challenge/board?scope=&board=`）：今日/本周/总榜，我的行，游标加载，公平性 |
| `review-page.js` | `SS.pages.challengeReview`（`#/challenge/:id/review`）：成绩、各轮、公开的 seed 与承诺、校验 |
| `index.js` | `SS.features.challenge = { routes, init }`：挂 `play`（order 10）与 `market.banner`（order 10）；订阅 `ws:challenge`、`save`；挑战存档时 `tradeBar.setOverlay("challenge")`（优先级 30） |

## 约定
- **时间只经 `SS.challengeModel`**：`state.challenge.skew = server_time − 本机时间`（每次拉 ChallengeOut 时更新）；倒计时用 `countdown(iso, skew, now)`，阶段文案用 `timeline`。页面不自行判断阶段。
- **状态**：`state.challenge = { today, skew, cards: {挑战id: ChallengeRoundCardOut[]}, live, loaded, error }`。`error` 为错误码（`FEATURE_UNAVAILABLE` 表示后端没有挑战接口）。切存档时 `resetChallenge()`。
- **广播**：`challenge:update`（本功能内部，refresh 之后发出）；`ws:challenge` 只触发 refresh。
- **挑战存档**：真实版 `enterChallenge` 记 `ss.returnSaveId` 为参加前的存档并 `switchSave(save_id)`；`leaveChallenge` 切回（失效则第一个普通存档）。挑战存档不在 `GET /saves` 列表里，`switchSave` 会按 id 直接取 `GET /saves/{id}`。报名总会建存档：`eligible=false` 只表示不计入排名（账号未满 `CHALLENGE_MIN_ACCOUNT_AGE_HOURS`），仍切到挑战存档，toast 如实说明。
- **快放段（burst / final）**：后端在这两段给 `next_change_at = null`（停顿与结算时刻保密，03 §5 #8）。`timeline` 返回 `fast: true`，`big` = “快放中” / “最后一段”，`hint` = “停顿时间保密”或“最迟 HH:mm 结算”（`settle_expected_at` 为上界）；**不倒计时**。`refreshDue` 对快放段每 5 秒轮询一次（同后端 `CHALLENGE_HOLD_POLL_MS`），WS 断开时也能发现停顿与结算。hold 段仍按 `next_change_at` 倒计时。
- **状态栏覆盖**（`index.js`）：挑战存档内无论挑战状态如何都覆盖动作按钮（挑战中不能暂停或调速）：运行中为“全服暂停 / 快放中 / 最后一段” + `hint`，动作“挑战”；已结算或未同步为“挑战已结算 / 挑战存档”，动作“回到我的存档”（`leave`）。
- **作答**：当前回合卡复用 `SS.predictionCard.render(card, draft, opts)` 与 `bind(root, card, draft, st, { onSubmit })`，`opts.skip=false`（挑战没有“这张不答”），不弹层、不出单人卡与情报卡。草稿按 `挑战id:回合` 存在页面内存里。
- **赛后校验**：`SS.challengeVerify.run(reveal)`：`window.isSecureContext` 为 false 或无 `crypto.subtle` → `unavailable`，界面如实说明；不假装通过。判定 = sha256(承诺原文) 与 `seed_commitment` 一致 **且** 承诺原文里的 seed 等于 `market_seed`。
- **颜色**：排名、积分、回合进度用 `--accent`；收益率用 `up/down`（行情数据）；其它只用 tokens。
- **错误文案**：`CHALLENGE_*` 在 `js/lib/store.js` 与 `store.real.js` 的 `ERROR_TEXT`；页面对 `CHALLENGE_ROUND_CLOSED`、`CHALLENGE_ANSWER_LIMIT`、`CHALLENGE_NOT_ENTERED`、`CHALLENGE_NOT_SETTLED`、`CHALLENGE_ENTRY_CLOSED` 有专门提示。
- 文件内所有用户数据（昵称、称号、事件标题）经 `SS.html` 转义。

## mock
- 今日 `TODAY_ID`：running、phase hold、第 2 轮 open、未参加；参加后 `my_entry` 出现，可作答，提交后显示“已提交 · 第 N 次作答”。
- 昨日 `DAY_ID`：settled，四轮已判定，有成绩与排行（日榜 20 人含并列）；`reveal` 与 `review` 可用，**承诺哈希是对承诺原文真实计算的 sha256**（`printf %s '<承诺原文>' | sha256sum`）。改承诺原文必须重算，`tests/challenge-model.test.mjs` 用 `node:crypto` 校验。
- 今日的日榜与公开 seed 返回 `CHALLENGE_NOT_SETTLED`，页面据此默认切到本周。

## 真实后端联调（⑦ 收尾）
- 已在隔离后端（`CHALLENGE_SCHEDULE=compact`、`ENABLE_DEBUG_API=true`，sqlite 在 scratchpad）上走通：玩法卡参加 → 进入挑战存档 → 快放（“快放中”不倒计时）→ 停顿（`hold`，倒计时到 `next_change_at`）→ 作答（dir / rank / rumor，提交“已提交 · 第 N 次作答”）→ 日榜未结算提示并默认切本周 → `debug/challenges/{id}/shift` 快进结算 → 复盘 → 种子校验 `✓ 种子与开局指纹一致` → 状态栏“挑战已结算”→“回到我的存档”。
- 挑战存档内“游戏速度 / 行情暂停”隐藏，自动交易页“挑战中不可用”。
- **运行中的名次不可得**：后端没有实时排名（`ChallengeEntryOut.result` 与日榜都要结算后才有；日榜未结算返回 409 `CHALLENGE_NOT_SETTLED`）。卡片与挑战页在运行中只显示“排名结算后公布”，名次只在结算后显示。
- 与后端字段的对齐：`LeaderboardItemOut` / `ChallengeRoundCardOut` / `RevealOut` / `ReviewOut` 按 `schemas/challenges.py` 读取；`export` 的 `challenge` 块（只含 `challenge_id`、`challenge_date`）手机端目前不读取。
- 未覆盖：后端尚未上线的其它玩法（预测结算、预测市场、真实复盘）返回 404，页面按各自降级显示“即将开放”。
