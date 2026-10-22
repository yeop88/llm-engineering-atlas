"""옴니채널 맵: 채널 주소 → 고객 · 고객 세션 · 채널을 가리지 않는 메시지

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-22

같은 고객이면 채널을 바꿔도 한 세션으로 잇고, 웹훅이 다시 보낸 같은 메시지는 (채널, 외부 id) 로 한 번만 처리한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "omni_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer", sa.String(length=100), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("address", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("omni_identities", schema=None) as b:
        b.create_index(b.f("ix_omni_identities_customer"), ["customer"], unique=False)
        b.create_index(b.f("ix_omni_identities_address"), ["address"], unique=False)
    op.create_table(
        "omni_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("customer", sa.String(length=100), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("channels", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("memory", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("handoffs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("omni_sessions", schema=None) as b:
        b.create_index(b.f("ix_omni_sessions_customer"), ["customer"], unique=False)
    op.create_table(
        "omni_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False, server_default="in"),
        sa.Column("external_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="text"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="received"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_to", sa.Integer(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("omni_messages", schema=None) as b:
        for col in ("session_id", "external_id", "at"):
            b.create_index(b.f(f"ix_omni_messages_{col}"), [col], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("omni_messages", schema=None) as b:
        for col in ("at", "external_id", "session_id"):
            b.drop_index(b.f(f"ix_omni_messages_{col}"))
    op.drop_table("omni_messages")
    with op.batch_alter_table("omni_sessions", schema=None) as b:
        b.drop_index(b.f("ix_omni_sessions_customer"))
    op.drop_table("omni_sessions")
    with op.batch_alter_table("omni_identities", schema=None) as b:
        b.drop_index(b.f("ix_omni_identities_address"))
        b.drop_index(b.f("ix_omni_identities_customer"))
    op.drop_table("omni_identities")
