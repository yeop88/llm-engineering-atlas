"""v0.1.0 스키마 (모델 카탈로그, 실행 이력, 카탈로그 제외 목록)

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "embedding_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hf_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("release_date", sa.String(20), nullable=False),
        sa.Column("params", sa.String(50), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=True),
        sa.Column("mrl_dims", sa.JSON(), nullable=False),
        sa.Column("max_seq_len", sa.Integer(), nullable=True),
        sa.Column("license", sa.String(100), nullable=False),
        sa.Column("languages", sa.String(100), nullable=False),
        sa.Column("modalities", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("query_prompt", sa.String(100), nullable=False),
        sa.Column("document_prompt", sa.String(100), nullable=False),
        sa.Column("query_prefix", sa.Text(), nullable=False),
        sa.Column("document_prefix", sa.Text(), nullable=False),
        sa.Column("query_kwargs", sa.JSON(), nullable=False),
        sa.Column("document_kwargs", sa.JSON(), nullable=False),
        sa.Column("trust_remote_code", sa.Boolean(), nullable=False),
        sa.Column("load_kwargs", sa.JSON(), nullable=False),
        sa.Column("multimodal_load_kwargs", sa.JSON(), nullable=False),
        sa.Column("gated", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("hub_downloads", sa.Integer(), nullable=True),
        sa.Column("hub_likes", sa.Integer(), nullable=True),
        sa.Column("hub_last_modified", sa.String(40), nullable=False),
        sa.Column("hub_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_embedding_models_hf_id", "embedding_models", ["hf_id"], unique=True)

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("model_hf_ids", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_test_runs_kind", "test_runs", ["kind"])
    op.create_index("ix_test_runs_created_at", "test_runs", ["created_at"])

    op.create_table(
        "catalog_exclusions",
        sa.Column("hf_id", sa.String(200), primary_key=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("catalog_exclusions")
    op.drop_index("ix_test_runs_created_at", "test_runs")
    op.drop_index("ix_test_runs_kind", "test_runs")
    op.drop_table("test_runs")
    op.drop_index("ix_embedding_models_hf_id", "embedding_models")
    op.drop_table("embedding_models")
