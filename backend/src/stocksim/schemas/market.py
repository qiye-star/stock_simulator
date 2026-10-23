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
