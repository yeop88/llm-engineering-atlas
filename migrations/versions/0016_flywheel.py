"""데이터 플라이휠 맵: 서비스 버전(게이트 · 단계적 배포)과 사람 검토 기록

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-21

버전마다 게이트 결과 · 배포 비율 · 되돌린 기록을 남겨 요청 기록의 signals.version 과 잇고, 사람 검토는 평가 · 학습 분배와
누수로 막힌 것까지 남긴다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fw_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="candidate"),
        sa.Column("gate", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("rollout", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("fw_versions", schema=None) as b:
        for col in ("collection_id", "status", "created_at"):
            b.create_index(b.f(f"ix_fw_versions_{col}"), [col], unique=False)
    op.create_table(
        "fw_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=10), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("destination", sa.String(length=10), nullable=False, server_default="ignore"),
        sa.Column("gold_doc_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("corrected", sa.Text(), nullable=False, server_default=""),
        sa.Column("routed", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reviewer", sa.String(length=100), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("fw_reviews", schema=None) as b:
        for col in ("trace_id", "created_at"):
            b.create_index(b.f(f"ix_fw_reviews_{col}"), [col], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("fw_reviews", schema=None) as b:
        for col in ("created_at", "trace_id"):
            b.drop_index(b.f(f"ix_fw_reviews_{col}"))
    op.drop_table("fw_reviews")
    with op.batch_alter_table("fw_versions", schema=None) as b:
        for col in ("created_at", "status", "collection_id"):
            b.drop_index(b.f(f"ix_fw_versions_{col}"))
    op.drop_table("fw_versions")
