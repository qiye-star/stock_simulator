"""生成旧版导出样例：legacy/crypto.js 的 XOR + Base64 编码（与 encrypt() 等价）。

用法（在 backend/ 下）：uv run python tests/fixtures/make_legacy_export.py
输出 tests/fixtures/legacy_export.txt；测试会校验该文件与 legacy_sample.json 一致。
"""

import base64
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

KEY = "stock-simulator-2024"
HERE = Path(__file__).resolve().parent


def encode_legacy(text: str, key: str = KEY) -> str:
    xored = "".join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(text))
    return base64.b64encode(xored.encode("utf-8")).decode("ascii")


def _yuan(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_sample() -> dict:
    """一个旧版用户，含一个存档：买入 100 股、卖出 50 股，手续费按 legacy 费率计算。"""
    buy_price, buy_qty = Decimal("1500.5"), 100
    buy_gross = buy_price * buy_qty  # 150050 元
    buy_fee = (buy_gross * Decimal("0.0003")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sell_price, sell_qty = Decimal("1600"), 50
    sell_gross = sell_price * sell_qty  # 80000 元
    sell_fee = (sell_gross * Decimal("0.0013")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sell_pnl = (sell_price - buy_price) * sell_qty - sell_fee
    fund = Decimal("1000000") - (buy_gross + buy_fee) + (sell_gross - sell_fee)
    return {
        "username": "legacy_bob",
        "passwordHash": "pbkdf2-sha256-100k$00112233445566778899aabbccddeeff$" + "ab" * 32,
        "createdAt": 1700000000000,
        "tutorialCompleted": True,
        "theme": "light",
        "refreshRate": 3000,
        "lang": "zh-CN",
        "achievements": [],
        "saves": [
            {
                "id": "9c1f0c4e-1111-4222-8333-444455556666",
                "name": "旧存档一",
                "createdAt": 1700000000000,
                "fund": _yuan(fund),
                "initialFund": 1000000,
                "holdings": {
                    "600519": {
                        "name": "贵州茅台",
                        "quantity": 50,
                        "avgPrice": 1500.5,
                        "totalCost": _yuan(buy_price * 50),
                    }
                },
                "records": [
                    {
                        "time": 1700000300000,
                        "code": "600519",
                        "name": "贵州茅台",
                        "type": "sell",
                        "price": 1600,
                        "quantity": sell_qty,
                        "amount": _yuan(sell_gross - sell_fee),
                        "pnl": _yuan(sell_pnl),
                    },
                    {
                        "time": 1700000200000,
                        "code": "600519",
                        "name": "贵州茅台",
                        "type": "buy",
                        "price": 1500.5,
                        "quantity": buy_qty,
                        "amount": _yuan(-(buy_gross + buy_fee)),
                        "pnl": 0,
                    },
                ],
                "watchlist": ["600036"],
                "achievements": ["first_trade", "first_profit", "not_a_real_achievement"],
                "settings": {"buyFee": 0.0003, "sellFee": 0.0013, "t0Mode": False, "tradeUnit": 1},
                "dayTrades": {"600519": {"buy": 0, "sell": 0}},
                "gameStats": {
                    "tradeCount": 1,
                    "profitCount": 1,
                    "lossCount": 0,
                    "maxHoldings": 1,
                    "sectorsTraded": {},
                    "dayTrades": 0,
                },
                "autoTrade": {"enabled": False, "paused": False, "configs": [], "stats": {}},
            }
        ],
    }


if __name__ == "__main__":
    sample = build_sample()
    (HERE / "legacy_sample.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "legacy_export.txt").write_text(
        encode_legacy(json.dumps(sample, ensure_ascii=False)) + "\n", encoding="ascii"
    )
    print("written", HERE)
