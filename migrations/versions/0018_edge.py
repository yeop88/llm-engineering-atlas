"""온디바이스 · 엣지 맵: 기기 등록 · 기기가 올린 기록(미뤄 둔 요청 · 피드백 · 개인정보 검사)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-21

기기마다 받은 팩 · 판 · 마지막 동기화를 남겨 낡은 자료로 답하는 기기를 찾고, 오프라인 동안 쌓인 요청 · 기록은 연결될 때 올려
서버가 처리하면서 개인정보를 다시 검사한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edge_devices",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("profile", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("pack", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sync", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "edge_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="received"),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("violations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("edge_events", schema=None) as b:
        for col in ("device_id", "kind", "created_at"):
            b.create_index(b.f(f"ix_edge_events_{col}"), [col], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("edge_events", schema=None) as b:
        for col in ("created_at", "kind", "device_id"):
            b.drop_index(b.f(f"ix_edge_events_{col}"))
    op.drop_table("edge_events")
    op.drop_table("edge_devices")
