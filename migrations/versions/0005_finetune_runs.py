"""임베딩 모델 파인튜닝 실행 기록

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finetune_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("base_model_id", sa.Integer(), sa.ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("base_hf_id", sa.String(200), nullable=False),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("output_model_id", sa.Integer(), sa.ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("data_stats", sa.JSON(), nullable=False),
        sa.Column("log", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("finetune_runs")
