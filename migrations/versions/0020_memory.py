"""장기 메모리 맵: 기억(시점 기록) · 기억 사이 연결

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-22

기억은 덮어쓰지 않고 언제부터 · 언제까지 맞았는지를 남긴다. 연결은 하나를 찾으면 이어진 기억도 함께 꺼내려고 둔다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mem_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="fact"),
        sa.Column("key", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("tier", sa.String(length=10), nullable=False, server_default="recall"),
        sa.Column("vector", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("keywords", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("happened_at", sa.DateTime(), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_access_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("mem_items", schema=None) as b:
        for col in ("owner", "key", "valid_to"):
            b.create_index(b.f(f"ix_mem_items_{col}"), [col], unique=False)
    op.create_table(
        "mem_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("a", sa.Integer(), nullable=False),
        sa.Column("b", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="similar"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("mem_links", schema=None) as b:
        b.create_index(b.f("ix_mem_links_a"), ["a"], unique=False)
        b.create_index(b.f("ix_mem_links_b"), ["b"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("mem_links", schema=None) as b:
        b.drop_index(b.f("ix_mem_links_b"))
        b.drop_index(b.f("ix_mem_links_a"))
    op.drop_table("mem_links")
    with op.batch_alter_table("mem_items", schema=None) as b:
        for col in ("valid_to", "key", "owner"):
            b.drop_index(b.f(f"ix_mem_items_{col}"))
    op.drop_table("mem_items")
