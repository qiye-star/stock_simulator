"""旧版（legacy）导出存档的请求体与严格结构校验模型。

字段名沿用 legacy/game.js 的 camelCase（sanitizeUserData / sanitizeSaveData 的结构）。
金额在旧版为“元”浮点数，这里接受 int/float（拒绝字符串），由服务层转换为整数分。
未知字段忽略（向前兼容），已知字段严格类型。
"""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

MAX_LEGACY_SAVES = 50  # legacy sanitize 与 game.js merge 的上限（单次文件内）
MAX_RECORDS = 100
MAX_CODES = 200

# legacy sanitizeSaveData：费率必须在 [0, 0.01]
_STRICT_NUM = StrictInt | StrictFloat


def _finite(value: float | int) -> float | int:
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise ValueError("must be finite")
    return value


Num = Annotated[_STRICT_NUM, AfterValidator(_finite)]
Code = Annotated[StrictStr, Field(pattern=r"^\d{6}$")]


class _Legacy(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LegacySettings(_Legacy):
    buyFee: Annotated[Num, Field(ge=0, le=0.01)] = 0.0003
    sellFee: Annotated[Num, Field(ge=0, le=0.01)] = 0.0013
    t0Mode: StrictBool = False
    tradeUnit: Literal[1, 100] = 1


class LegacyHolding(_Legacy):
    name: StrictStr = Field(default="", max_length=32)
    quantity: Annotated[StrictInt, Field(gt=0, le=1_000_000_000)]
    avgPrice: Annotated[Num, Field(ge=0)]
    totalCost: Annotated[Num, Field(ge=0)]


class LegacyRecord(_Legacy):
    time: Num | None = None
    code: Code
    name: StrictStr = Field(default="", max_length=32)
    type: Literal["buy", "sell"]
    price: Annotated[Num, Field(gt=0)]
    quantity: Annotated[StrictInt, Field(gt=0, le=1_000_000_000)]
    amount: Num
    pnl: Num = 0


class LegacyGameStats(_Legacy):
    tradeCount: Annotated[StrictInt, Field(ge=0)] = 0
    profitCount: Annotated[StrictInt, Field(ge=0)] = 0
    lossCount: Annotated[StrictInt, Field(ge=0)] = 0
    maxHoldings: Annotated[StrictInt, Field(ge=0)] = 0


class LegacySave(_Legacy):
    id: StrictStr | None = Field(default=None, max_length=64)
    name: StrictStr = Field(default="", max_length=20)
    createdAt: Num | None = None
    fund: Annotated[Num, Field(ge=0, le=1e10)]
    initialFund: Annotated[Num, Field(ge=0, le=1e10)] | None = None
    holdings: dict[Code, LegacyHolding] = Field(default_factory=dict, max_length=MAX_CODES)
    records: list[LegacyRecord] = Field(default_factory=list, max_length=MAX_RECORDS)
    watchlist: list[Code] = Field(default_factory=list, max_length=MAX_CODES)
    achievements: list[Annotated[StrictStr, Field(max_length=64)]] = Field(
        default_factory=list, max_length=500
    )
    settings: LegacySettings = Field(default_factory=LegacySettings)
    gameStats: LegacyGameStats | None = None


class LegacyUser(_Legacy):
    """旧版整包导出：一个用户 + 其存档列表。用户名与密码哈希仅校验形状，不导入。"""

    username: StrictStr = Field(min_length=2, max_length=20)
    passwordHash: StrictStr | None = Field(default=None, max_length=255)
    saves: list[LegacySave] = Field(default_factory=list, max_length=MAX_LEGACY_SAVES)


class ImportedSaveOut(BaseModel):
    save_id: str
    name: str
    cash_cents: int
    holdings: int
    trades: int
    watchlist: int
    achievements: int


class LegacyImportIn(BaseModel):
    """`content`：旧版导出文本（base64 + XOR），或明文 JSON。"""

    content: str


class LegacyImportOut(BaseModel):
    imported: list[ImportedSaveOut]
    skipped_achievements: int
