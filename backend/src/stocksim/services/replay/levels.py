"""关卡导入、列表与关卡包缓存（05 §3.3、§5.8）。

- 导入幂等：(slug, version) 已存在且 sha256 相同 → skipped；
  sha256 不同 → PackConflict（同一版本不可变）。
- 当前版本指向最高的已导入版本；关卡的 status（如 retired）导入时不改写。
- 运行时缓存按版本 ID 的 LRU（版本不可变）。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.core.config import Settings
from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.models import ReplayLevel, ReplayLevelVersion, ReplaySession, User
from stocksim.services.replay.pack import ReplayPack, pack_sha256, parse_pack

logger = logging.getLogger(__name__)
PACK_CACHE_SIZE = 32
DEFAULT_PACKS_DIR = Path(__file__).resolve().parents[4] / "replay" / "packs"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class PackConflict(ValueError):
    """同一 (slug, version) 的内容与已导入版本不同：版本不可变，拒绝导入。"""


@dataclass(frozen=True)
class ImportResult:
    slug: str
    version: int
    status: Literal["imported", "skipped"]


def import_pack(db: Session, raw: dict[str, Any]) -> ImportResult:
    """导入一个关卡包（不提交，由调用方 commit）。"""
    pack = parse_pack(raw)
    sha = pack_sha256(raw)
    now = utcnow()
    level = db.scalar(select(ReplayLevel).where(ReplayLevel.slug == pack.slug))
    if level is None:
        level = ReplayLevel(
            id=uuid.uuid4(),
            slug=pack.slug,
            title=pack.title,
            title_masked=pack.title_masked,
            teaser=pack.teaser,
            teaser_masked=pack.teaser_masked,
            tags=list(pack.tags),
            difficulty=pack.difficulty,
            kind=pack.kind,
            status="published",
            masked_allowed=pack.masked_allowed,
            play_days=pack.play_days,
            stock_count=len(pack.stocks),
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        db.add(level)
        db.flush()

    version = db.scalar(
        select(ReplayLevelVersion).where(
            ReplayLevelVersion.level_id == level.id, ReplayLevelVersion.version == pack.version
        )
    )
    if version is not None:
        if version.sha256 != sha:
            raise PackConflict(f"{pack.slug} v{pack.version} 已导入且内容不同（版本不可变）")
        status: Literal["imported", "skipped"] = "skipped"
    else:
        version = ReplayLevelVersion(
            id=uuid.uuid4(),
            level_id=level.id,
            version=pack.version,
            format_version=pack.format_version,
            sha256=sha,
            pack=raw,
            builder_version=str(pack.provenance.get("builder_version", "")),
            created_at=now,
        )
        db.add(version)
        db.flush()
        status = "imported"

    current = (
        db.get(ReplayLevelVersion, level.current_version_id) if level.current_version_id else None
    )
    if current is None or pack.version > current.version:
        level.current_version_id = version.id
        level.title = pack.title
        level.title_masked = pack.title_masked
        level.teaser = pack.teaser
        level.teaser_masked = pack.teaser_masked
        level.tags = list(pack.tags)
        level.difficulty = pack.difficulty
        level.kind = pack.kind
        level.masked_allowed = pack.masked_allowed
        level.play_days = pack.play_days
        level.stock_count = len(pack.stocks)
        level.updated_at = now
    db.flush()
    return ImportResult(slug=pack.slug, version=pack.version, status=status)


def packs_dir(settings: Settings) -> Path:
    return Path(settings.REPLAY_PACKS_DIR) if settings.REPLAY_PACKS_DIR else DEFAULT_PACKS_DIR


def import_directory(session_factory: Callable[[], Session], directory: Path) -> list[ImportResult]:
    """扫描 `<dir>/<slug>/*.json` 逐个导入。单个失败只记日志，不影响其它关卡（与种子导入一致）。"""
    if not directory.is_dir():
        logger.info("replay packs dir not found, skip import: %s", directory)
        return []
    results: list[ImportResult] = []
    for path in sorted(directory.glob("*/*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("replay pack unreadable: %s", path)
            continue
        with session_factory() as db:
            try:
                results.append(import_pack(db, raw))
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("replay pack import failed: %s", path)
    return results


def import_bundled_packs(
    session_factory: Callable[[], Session], settings: Settings
) -> list[ImportResult]:
    """lifespan 调用（seed_on_startup 之后）。"""
    if not settings.REPLAY_IMPORT_ON_STARTUP:
        return []
    return import_directory(session_factory, packs_dir(settings))


# ---------- 缓存 ----------

_cache: OrderedDict[uuid.UUID, ReplayPack] = OrderedDict()
_cache_lock = threading.Lock()


def get_pack(db: Session, version_id: uuid.UUID) -> ReplayPack:
    """按版本取解析后的关卡包（LRU，版本不可变）。"""
    with _cache_lock:
        hit = _cache.get(version_id)
        if hit is not None:
            _cache.move_to_end(version_id)
            return hit
    row = db.get(ReplayLevelVersion, version_id)
    if row is None:  # 不应发生：会话引用的版本由 RESTRICT 外键保护
        raise RuntimeError(f"replay level version missing: {version_id}")
    pack = ReplayPack.model_validate(row.pack)
    with _cache_lock:
        _cache[version_id] = pack
        _cache.move_to_end(version_id)
        while len(_cache) > PACK_CACHE_SIZE:
            _cache.popitem(last=False)
    return pack


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ---------- 列表与详情 ----------


def published_levels(db: Session) -> list[ReplayLevel]:
    return list(
        db.scalars(
            select(ReplayLevel)
            .where(ReplayLevel.status == "published")
            .order_by(ReplayLevel.sort_order, ReplayLevel.slug)
        )
    )


def get_published(db: Session, slug: str) -> ReplayLevel:
    level = db.scalar(select(ReplayLevel).where(ReplayLevel.slug == slug))
    if level is None or level.status != "published":
        raise AppError(ErrorCode.REPLAY_LEVEL_NOT_FOUND, {"slug": slug})
    return level


def current_version(db: Session, level: ReplayLevel) -> ReplayLevelVersion:
    if level.current_version_id is None:  # 不应发生：导入时同一事务写入
        raise RuntimeError(f"replay level {level.slug} has no version")
    row = db.get(ReplayLevelVersion, level.current_version_id)
    if row is None:
        raise RuntimeError(f"replay level {level.slug} version missing")
    return row


def my_best_by_level(db: Session, user: User) -> dict[uuid.UUID, dict[str, Any]]:
    """每关的会话统计：sessions / settled / best_points / best_excess_bp。"""
    rows = db.execute(
        select(ReplaySession, ReplayLevelVersion.level_id)
        .join(ReplayLevelVersion, ReplaySession.level_version_id == ReplayLevelVersion.id)
        .where(ReplaySession.user_id == user.id)
    ).all()
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for session, level_id in rows:
        best = out.setdefault(
            level_id,
            {"sessions": 0, "settled": 0, "best_points": None, "best_excess_bp": None},
        )
        best["sessions"] += 1
        if session.status == "settled":
            best["settled"] += 1
            best["best_points"] = max(best["best_points"] or 0, session.points_total)
            if session.excess_bp is not None:
                prev = best["best_excess_bp"]
                best["best_excess_bp"] = (
                    session.excess_bp if prev is None else max(prev, session.excess_bp)
                )
    return out


def level_out(level: ReplayLevel, version: int, my_best: dict[str, Any] | None) -> dict[str, Any]:
    """ReplayLevelOut：匿名关卡只给匿名标题与导语；实名关卡（masked_allowed=false）给真实标题。"""
    allowed = level.masked_allowed
    return {
        "slug": level.slug,
        "version": version,
        "title": level.title_masked if allowed else level.title,
        "teaser": level.teaser_masked if allowed else level.teaser,
        "title_real": None if allowed else level.title,
        "tags": list(level.tags or []),
        "difficulty": level.difficulty,
        "kind": level.kind,
        "play_days": level.play_days,
        "stock_count": level.stock_count,
        "masked_allowed": allowed,
        "my_best": my_best,
    }


def _encode_cursor(level: ReplayLevel) -> str:
    return f"{level.sort_order}|{level.slug}"


def _decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        order, slug = cursor.split("|", 1)
        return int(order), slug
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc


def list_levels(
    db: Session,
    user: User,
    *,
    tag: str | None = None,
    difficulty: int | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """GET /replay/levels：只列 published；按 (sort_order, slug) 键集分页。"""
    rows = published_levels(db)
    if tag:
        rows = [r for r in rows if tag in (r.tags or [])]
    if difficulty is not None:
        rows = [r for r in rows if r.difficulty == difficulty]
    if cursor:
        after = _decode_cursor(cursor)
        rows = [r for r in rows if (r.sort_order, r.slug) > after]
    limit = max(1, min(limit, MAX_LIMIT))
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit and page else None
    best = my_best_by_level(db, user)
    items = []
    for level in page:
        stats = best.get(level.id)
        items.append(level_out(level, current_version(db, level).version, stats))
    return {"items": items, "next_cursor": next_cursor}


__all__ = [
    "ImportResult",
    "PackConflict",
    "clear_cache",
    "get_pack",
    "get_published",
    "import_bundled_packs",
    "import_directory",
    "import_pack",
    "level_detail",
    "level_out",
    "list_levels",
    "packs_dir",
]


def level_detail(db: Session, user: User, slug: str) -> dict[str, Any]:
    """GET /replay/levels/{slug}：未发布或已退役 → REPLAY_LEVEL_NOT_FOUND。"""
    level = get_published(db, slug)
    best = my_best_by_level(db, user).get(level.id)
    return level_out(level, current_version(db, level).version, best)
