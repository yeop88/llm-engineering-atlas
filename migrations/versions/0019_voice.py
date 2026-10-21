"""실시간 음성 상담 맵: 통화 기록(턴 · 추천과 채택 · 사건 · 요약)

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-21

턴마다 전사 · 운율 · 감정 · 단계별 지연을 남겨 지연 예산 · 이관 · 채택률을 통화 기록으로 잰다. 전사는 기본으로 개인정보를 가려 저장한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_calls",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("as_session_id", sa.String(length=32), nullable=True),
        sa.Column("mode", sa.String(length=10), nullable=False, server_default="auto"),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="live"),
        sa.Column("turns", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("suggestions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("events", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("memory", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("voice_calls", schema=None) as b:
        b.create_index(b.f("ix_voice_calls_status"), ["status"], unique=False)
        b.create_index(b.f("ix_voice_calls_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("voice_calls", schema=None) as b:
        b.drop_index(b.f("ix_voice_calls_created_at"))
        b.drop_index(b.f("ix_voice_calls_status"))
    op.drop_table("voice_calls")
