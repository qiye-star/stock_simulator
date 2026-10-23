"""行情与时钟的响应模型。"""

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


class ClockOut(BaseModel):
    paused: bool
    tick: int
    trading_day: int
    clock_minute: int
    session: str
    skipped_ticks: int = 0


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
