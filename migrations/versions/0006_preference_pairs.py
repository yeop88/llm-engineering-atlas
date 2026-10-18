"""8b 강화학습: 선호 쌍(좋은 답 / 나쁜 답) 기록

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preference_pairs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("chosen", sa.Text(), nullable=False),
        sa.Column("rejected", sa.Text(), nullable=False),
        sa.Column("chosen_reward", sa.Float(), nullable=True),
        sa.Column("rejected_reward", sa.Float(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("preference_pairs") as b:
        b.create_index("ix_preference_pairs_collection_id", ["collection_id"])


def downgrade() -> None:
    with op.batch_alter_table("preference_pairs") as b:
        b.drop_index("ix_preference_pairs_collection_id")
    op.drop_table("preference_pairs")
