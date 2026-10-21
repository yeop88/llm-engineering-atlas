"""엔터프라이즈 플랫폼 맵: 테넌트 컬렉션 · 프롬프트 버전 · 기능 플래그 · 테넌트 예산

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-21

테넌트 격리는 검색 단계(restrict)가 이 표를 보고, 프롬프트 · 플래그는 서비스 답변이 요청마다 읽는다(바꾸면 배포 없이 동작이 바뀜).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pf_tenant_collections",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("tenant", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("collection_id"),
    )
    with op.batch_alter_table("pf_tenant_collections", schema=None) as b:
        b.create_index(b.f("ix_pf_tenant_collections_tenant"), ["tenant"], unique=False)
    op.create_table(
        "pf_prompts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_pf_prompt"),
    )
    with op.batch_alter_table("pf_prompts", schema=None) as b:
        b.create_index(b.f("ix_pf_prompts_name"), ["name"], unique=False)
    op.create_table(
        "pf_flags",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("default", sa.JSON(), nullable=True),
        sa.Column("rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("history", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "pf_budgets",
        sa.Column("tenant", sa.String(length=60), nullable=False),
        sa.Column("monthly_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("alert_pct", sa.Float(), nullable=False, server_default="80"),
        sa.Column("alerted", sa.String(length=7), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("tenant"),
    )


def downgrade() -> None:
    op.drop_table("pf_budgets")
    op.drop_table("pf_flags")
    with op.batch_alter_table("pf_prompts", schema=None) as b:
        b.drop_index(b.f("ix_pf_prompts_name"))
    op.drop_table("pf_prompts")
    with op.batch_alter_table("pf_tenant_collections", schema=None) as b:
        b.drop_index(b.f("ix_pf_tenant_collections_tenant"))
    op.drop_table("pf_tenant_collections")
