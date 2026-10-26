"""每日挑战集成测试的夹具（C3–C5）：独立临时库（Alembic 迁移到 head）、compact 调度、可控时钟。

时钟：monkeypatch `stocksim.services.challenges.timeutil.now`，挑战与行情分发统一经它取时间。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.orm import Session

from stocksim.core.config import Settings
from stocksim.main import create_app
from stocksim.models import User
from stocksim.services import auth as auth_service
from stocksim.services.challenges import timeutil

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_SECRET = "test-secret-key-0123456789abcdef"
CHALLENGE_SEED_KEY = "test-challenge-seed-key"
# compact 调度下 2026-10-26 01:00 UTC（北京 09:00）为整 5 秒边界：开局 = now + 5 s
CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)
CHALLENGE_DAY = "2026-10-26"
PASSWORD = "secret1"


@dataclass
class FakeClock:
    value: datetime


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clock = FakeClock(CHALLENGE_NOW)
    monkeypatch.setattr(timeutil, "now", lambda: clock.value)
    return clock


def migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy.url"] = url
    command.upgrade(cfg, "head")


def challenge_settings_for(directory: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "DATABASE_URL": f"sqlite:///{directory / 'challenge.db'}",
        "SECRET_KEY": TEST_SECRET,
        "COOKIE_SECURE": False,
        "CHALLENGE_SCHEDULE": "compact",
        "CHALLENGE_MIN_ACCOUNT_AGE_HOURS": 0,
        "ENABLE_DEBUG_API": True,
        "CHALLENGE_SEED_KEY": CHALLENGE_SEED_KEY,
        # 预测市场后台 Hub/sweeper 默认关闭，用例直接调用生命周期函数；WS 用例显式开启
        "PM_BACKGROUND_ENABLED": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def build_app(directory: Path, **overrides: object) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    settings = challenge_settings_for(directory, **overrides)
    migrate(settings.DATABASE_URL)
    return create_app(settings)


@pytest.fixture
def challenge_app_factory(tmp_path: Path) -> Callable[..., FastAPI]:
    """按名字建一个独立的已迁移应用（同一用例可建多个互不影响的库）。"""

    def make(name: str = "main", **overrides: object) -> FastAPI:
        return build_app(tmp_path / name, **overrides)

    return make


@pytest.fixture
def challenge_app(challenge_app_factory: Callable[..., FastAPI]) -> FastAPI:
    return challenge_app_factory("main")


@pytest.fixture
def db(challenge_app: FastAPI) -> Iterator[Session]:
    session: Session = challenge_app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_user(db: Session) -> Callable[[str], User]:
    """注册用户并把账号创建时间设为很早（合格门槛只看创建时间）。"""

    def make(username: str) -> User:
        user = auth_service.register(db, username, PASSWORD)
        user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        db.commit()
        return user

    return make


class ChallengePlay:
    """驱动一场挑战的服务层脚本（C6/C7 测试用）：报名、逐回合作答与交易、结算。

    作答与交易只走服务层（rounds.answer_round、trading.place_order_detailed）。
    时间由 fake_clock 控制。
    """

    def __init__(self, db: Session, fake_clock: FakeClock) -> None:
        self.db = db
        self.fake_clock = fake_clock

    def join(self, ch, users) -> list:
        from stocksim.services.challenges import entries

        self.fake_clock.value = _aware(ch.starts_at)
        return [entries.join(self.db, ch, user, self.fake_clock.value)[0] for user in users]

    def play_rounds(self, ch, rows, *, trade_every: int = 2) -> None:
        """逐回合：停顿后作答（idx 决定答案形状），每 trade_every 人买入一手第一只股票。"""
        from stocksim.models import Save
        from stocksim.services import trading as trading_service
        from stocksim.services.challenges import registry, rounds, sync
        from stocksim.services.stocks import stock_pool

        code = stock_pool()[0].code
        for k in range(1, 5):
            hold = registry.round_by_index(self.db, ch, k).hold_at
            t = _aware(hold) + timedelta(seconds=1)
            self.fake_clock.value = t
            sync.advance_master(self.db, ch, t)
            rnd = registry.round_by_index(self.db, ch, k)
            master = registry.market_save_for(self.db, ch)
            for idx, entry in enumerate(rows):
                rounds.answer_round(
                    self.db,
                    ch,
                    master,
                    entry,
                    k,
                    answers_for(rnd.questions or [], idx),
                    now=t,
                    round_row=rnd,
                )
                if idx % trade_every == 0:
                    save = self.db.get(Save, entry.save_id)
                    trading_service.place_order_detailed(
                        self.db,
                        save,
                        entry.user_id,
                        code=code,
                        side="buy",
                        quantity=100,
                    )
            self.db.commit()

    def settle(self, ch) -> bool:
        from stocksim.services.challenges import settle

        t = _aware(ch.ends_at) + timedelta(seconds=1)
        self.fake_clock.value = t
        return settle.settle_if_due(self.db, ch, t)


def answers_for(questions: list[dict], idx: int) -> dict:
    """按 idx 生成与众不同的作答：bucket/binary 为按档数的加权分布（合计 100），
    rank 为候选轮转后的前三。"""
    out: dict = {}
    for q in questions:
        if q["kind"] in ("bucket", "binary"):
            k = len(q["edges_bp"]) + 1 if q["kind"] == "bucket" else 2
            out[q["qid"]] = {"probs": _probs(k, idx)}
        elif q["kind"] == "rank":
            cands = list(q["candidates"])
            r = idx % len(cands)
            out[q["qid"]] = {"order": (cands[r:] + cands[:r])[:3]}
    return out


def _probs(k: int, idx: int) -> list[int]:
    weights = [1 + ((j + idx) % k) for j in range(k)]
    total = sum(weights)
    probs = [w * 100 // total for w in weights]
    probs[-1] += 100 - sum(probs)
    return probs


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@pytest.fixture
def challenge_play(db: Session, fake_clock: FakeClock) -> ChallengePlay:
    return ChallengePlay(db, fake_clock)
