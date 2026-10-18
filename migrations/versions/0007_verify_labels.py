"""답변 근거 검증 보정: 사람이 판정한 문장 라벨

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verify_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("sources", sa.Text(), nullable=False),
        sa.Column("label", sa.Boolean(), nullable=False),
        sa.Column("labeler", sa.String(20), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("verify_labels") as b:
        b.create_index("ix_verify_labels_collection_id", ["collection_id"])


def downgrade() -> None:
    with op.batch_alter_table("verify_labels") as b:
        b.drop_index("ix_verify_labels_collection_id")
    op.drop_table("verify_labels")
