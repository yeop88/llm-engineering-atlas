"""의미 기반 응용: 저장된 분류기 · 이상 탐지기

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_hf_id", sa.String(200), nullable=False),
        sa.Column("truncate_dim", sa.Integer(), nullable=True),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("n_train", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_app_models_kind", "app_models", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_app_models_kind", "app_models")
    op.drop_table("app_models")
