"""clock rules v2

给 saves 增加 clock_rules（存量存档为 v1）、给 users 增加 clock_speed（默认 normal）。

注意：不使用 batch 模式。batch 在 SQLite 上会重建表（DROP TABLE），而迁移引擎开启了
foreign_keys=ON，重建 users / saves 会按 ON DELETE CASCADE 级联删除存档与交易等子表数据。
SQLite 直接用 ALTER TABLE ADD/DROP COLUMN（列级 CHECK 随列删除）；其它方言用标准 DDL。

Revision ID: 361472202775
Revises: f1c260b097ed
Create Date: 2026-10-26 11:03:41.774433

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "361472202775"
down_revision: Union[str, Sequence[str], None] = "f1c260b097ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CK_SAVES_CLOCK_RULES = "ck_saves_clock_rules_valid"
CK_USERS_CLOCK_SPEED = "ck_users_clock_speed_valid"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    """Upgrade schema."""
    if _is_sqlite():
        # 已有存档 DEFAULT 1 即 v1（迁移前的全部行为）；新建存档由 ORM 默认 v2
        op.execute(
            "ALTER TABLE saves ADD COLUMN clock_rules INTEGER NOT NULL DEFAULT 1 "
            f"CONSTRAINT {CK_SAVES_CLOCK_RULES} CHECK (clock_rules IN (1, 2))"
        )
        op.execute(
            "ALTER TABLE users ADD COLUMN clock_speed VARCHAR(8) NOT NULL DEFAULT 'normal' "
            f"CONSTRAINT {CK_USERS_CLOCK_SPEED} CHECK (clock_speed IN ('fast','normal','slow'))"
        )
        return

    op.add_column(
        "saves", sa.Column("clock_rules", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_check_constraint(CK_SAVES_CLOCK_RULES, "saves", "clock_rules IN (1, 2)")
    op.add_column(
        "users",
        sa.Column("clock_speed", sa.String(length=8), server_default="normal", nullable=False),
    )
    op.create_check_constraint(
        CK_USERS_CLOCK_SPEED, "users", "clock_speed IN ('fast','normal','slow')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    if _is_sqlite():
        op.execute("ALTER TABLE users DROP COLUMN clock_speed")
        op.execute("ALTER TABLE saves DROP COLUMN clock_rules")
        return

    op.drop_constraint(CK_USERS_CLOCK_SPEED, "users", type_="check")
    op.drop_column("users", "clock_speed")
    op.drop_constraint(CK_SAVES_CLOCK_RULES, "saves", type_="check")
    op.drop_column("saves", "clock_rules")
