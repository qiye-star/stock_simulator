"""save events mode

给 saves 增加 events_enabled（事件模式开关，创建后不可改）与 events_ruleset（规则集版本，关闭为 0）。
存量存档迁移后为关闭（events_enabled=0，events_ruleset=0）。

注意：不使用 batch 模式。batch 在 SQLite 上会重建 saves 表（DROP TABLE），而迁移引擎开启了
foreign_keys=ON，重建会按 ON DELETE CASCADE 级联删除交易、持仓等子表数据。SQLite 直接用
ALTER TABLE ADD/DROP COLUMN，列级 CHECK 随列一起创建/删除（与 361472202775 相同的写法）。

Revision ID: a26942b8c903
Revises: 361472202775
Create Date: 2026-10-26 11:42:16.322768

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a26942b8c903"
down_revision: Union[str, Sequence[str], None] = "361472202775"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CK_SAVES_EVENTS_RULESET = "ck_saves_events_ruleset_non_negative"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    """Upgrade schema."""
    if _is_sqlite():
        op.execute("ALTER TABLE saves ADD COLUMN events_enabled BOOLEAN NOT NULL DEFAULT 0")
        op.execute(
            "ALTER TABLE saves ADD COLUMN events_ruleset INTEGER NOT NULL DEFAULT 0 "
            f"CONSTRAINT {CK_SAVES_EVENTS_RULESET} CHECK (events_ruleset >= 0)"
        )
        return

    op.add_column(
        "saves",
        sa.Column("events_enabled", sa.Boolean(), server_default="0", nullable=False),
    )
    op.add_column(
        "saves",
        sa.Column("events_ruleset", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(CK_SAVES_EVENTS_RULESET, "saves", "events_ruleset >= 0")


def downgrade() -> None:
    """Downgrade schema."""
    if _is_sqlite():
        op.execute("ALTER TABLE saves DROP COLUMN events_ruleset")
        op.execute("ALTER TABLE saves DROP COLUMN events_enabled")
        return

    op.drop_constraint(CK_SAVES_EVENTS_RULESET, "saves", type_="check")
    op.drop_column("saves", "events_ruleset")
    op.drop_column("saves", "events_enabled")
