"""규제 대응 · 컴플라이언스 맵: 사람 판단 기록(위험 등급 · 처리 근거 등록 · 영향 평가 · 사람 검토 요청)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-21

자동 분류는 제안만 하고 확정 · 승인은 사람이 한다 — 그 판단을 누가 언제 했는지 남기는 표. 정기 감사(RC8)가 통제별 증적으로 읽는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="local"),
        sa.Column("reviewed_by", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("compliance_records", schema=None) as batch_op:
        for col in ("kind", "subject", "status", "created_at"):
            batch_op.create_index(batch_op.f(f"ix_compliance_records_{col}"), [col], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("compliance_records", schema=None) as batch_op:
        for col in ("created_at", "status", "subject", "kind"):
            batch_op.drop_index(batch_op.f(f"ix_compliance_records_{col}"))
    op.drop_table("compliance_records")
