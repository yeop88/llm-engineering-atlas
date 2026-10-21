"""대화 · 메모리 맵(C4)의 고객 프로필 테이블

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-21

보유 제품 · 지난 문의 요약을 고객 키별로 둔다. 대화 메모리(C3)는 대화 기록에서 매번 다시 계산하므로 테이블이 없고,
여러 대화에 걸쳐 남아야 하는 것만 여기에 둔다. 보관 기간(PROFILE_RETENTION_DAYS)이 지나면 updated_at 으로 지운다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_profiles_updated_at"), ["updated_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_profiles_updated_at"))
    op.drop_table("profiles")
