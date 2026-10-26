"""行情与时钟的响应模型。"""

from typing import Literal

from pydantic import BaseModel


class QuoteOut(BaseModel):
    code: str
    name: str
    industry: str
    price_cents: int
    prev_close_cents: int
    open_cents: int
    high_cents: int
    low_cents: int
    volume: int
    change_bp: int
    limit_up_cents: int
    limit_down_cents: int
    circuit_breaker_active: bool
    watchlisted: bool


class NextEventOut(BaseModel):
    kind: Literal["open", "lunch", "reopen", "close"]
    minute: int
    at: str | None = None  # 预计到达的 UTC 时间（ISO 8601，Z）；暂停时为 null


class ClockOut(BaseModel):
    paused: bool
    tick: int
    trading_day: int
    clock_minute: int
    session: str
    skipped_ticks: int = 0
    clock_rules: Literal["v1", "v2"] = "v1"
    phase: Literal["pre_open", "morning", "lunch", "afternoon", "closed"] = "pre_open"
    trading: bool = False  # 此刻能否下单（与暂停无关）
    next_event: NextEventOut | None = None
    ms_per_minute: int | None = None  # 交易时段每游戏分钟的现实毫秒数
    next_tick_at: str | None = None  # 下一分钟 tick 的预计到达时刻；暂停或停留中为 null
    fast_forward_at: str | None = None  # v2 停留点（11:30 / 15:00）的自动快进时刻
    server_time: str | None = None  # 服务端生成响应的 UTC 时间，用于校正本机时钟偏差


class MarketOut(ClockOut):
    stocks: list[QuoteOut]
    total: int  # 过滤（q/watchlisted）后的总数，不受 limit/cursor 影响
    next_cursor: str | None = None  # None 表示已到末页（不分页时恒为 None）


class CandleOut(BaseModel):
    trading_day: int
    date: str
    open_cents: int
    high_cents: int
    low_cents: int
    close_cents: int
    volume: int


class BookLevelOut(BaseModel):
    price_cents: int
    volume: int


class OrderBookOut(BaseModel):
    bids: list[BookLevelOut]
    asks: list[BookLevelOut]


class StockMarketOut(QuoteOut):
    candles: list[CandleOut]
    order_book: OrderBookOut
    suspended: bool = False  # 复盘存档：当前阶段停牌（普通存档恒 False）


class IntradayPointOut(BaseModel):
    minute: int  # 当日分钟数（0-1439），即该 tick 完成后的游戏时钟
    tick: int  # 全局 tick 序号，与 WebSocket tick 消息的 tick 对齐
    price_cents: int
    volume: int  # 引擎 daily_volume（与市场列表 volume 同口径），不保证单调


class IntradayOut(BaseModel):
    code: str
    trading_day: int
    date: str
    clock_minute: int
    tick: int
    prev_close_cents: int
    open_cents: int
    points: list[IntradayPointOut]  # 按时间升序；开盘前为空；休市分钟无点
    exact: bool  # False 表示无法精确重放（如调试改过时钟），points 退化为仅当前点


class SummaryQuoteOut(BaseModel):
    code: str
    name: str
    close_cents: int
    change_bp: int
    limit: Literal["up", "down"] | None = None  # 收盘价等于涨停/跌停价


class SummaryTradesOut(BaseModel):
    count: int
    buy_count: int
    sell_count: int
    buy_amount_cents: int
    sell_amount_cents: int
    fee_cents: int
    realized_pnl_cents: int


class SummaryMarketOut(BaseModel):
    total: int
    up: int
    down: int
    flat: int
    limit_up: int
    limit_down: int
    avg_change_bp: int  # 全市场等权平均涨跌幅


class SummaryHoldingOut(BaseModel):
    code: str
    name: str
    quantity: int
    close_cents: int
    change_bp: int
    market_value_cents: int


class DaySummaryOut(BaseModel):
    """收盘小结（07 §1.4）。过去的日取自 candles / equity_snapshots；缺快照的字段为 null。"""

    trading_day: int
    date: str
    clock_rules: Literal["v1", "v2"]
    status: Literal["trading", "closed"]
    equity_cents: int | None = None
    prev_equity_cents: int | None = None
    day_pnl_cents: int | None = None
    day_pnl_bp: int | None = None
    cash_cents: int | None = None
    market_value_cents: int | None = None
    trades: SummaryTradesOut
    market: SummaryMarketOut
    top_gainers: list[SummaryQuoteOut]
    top_losers: list[SummaryQuoteOut]
    holdings: list[SummaryHoldingOut] | None = None  # 仅当前交易日；过去的日为 null
    next_open_at: str | None = None
