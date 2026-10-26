"""B 的 CardPolicy 注册（02 §1.3、03 §1.6）：挑战存档（玩家与 master）不出卡、不发积分、不给情报。

main.create_app 在 B 的钩子注册之后调用 `register()`。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from stocksim.models import Save
from stocksim.models.save import CHALLENGE_MODES
from stocksim.services import predictions as predictions_service


def card_policy(db: Session, save: Save) -> predictions_service.CardPolicy | None:
    if save.mode in CHALLENGE_MODES:
        return predictions_service.CardPolicy(
            enabled=False, points_reason=None, intel_allowed=False
        )
    return None


def register() -> None:
    predictions_service.register_card_policy(card_policy)
