"""장기 실행 맵: 업무(lr_runs)와 단계 체크포인트(lr_steps)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21

며칠짜리 업무는 서버가 다시 떠도 이어 가야 해 상태 · 단계별 결과를 DB 에 둔다. 단계의 idem_key 는 발송처럼 되돌릴 수 없는 행동을
재시도 · 이어 하기에서 두 번 하지 않게 한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lr_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("template", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"),
        sa.Column("plan", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("log", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("verdict", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lr_runs", schema=None) as b:
        b.create_index(b.f("ix_lr_runs_status"), ["status"], unique=False)
        b.create_index(b.f("ix_lr_runs_created_at"), ["created_at"], unique=False)
    op.create_table(
        "lr_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("deps", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("output", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("idem_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("approved_by", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["lr_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lr_steps", schema=None) as b:
        b.create_index(b.f("ix_lr_steps_run_id"), ["run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("lr_steps", schema=None) as b:
        b.drop_index(b.f("ix_lr_steps_run_id"))
    op.drop_table("lr_steps")
    with op.batch_alter_table("lr_runs", schema=None) as b:
        b.drop_index(b.f("ix_lr_runs_created_at"))
        b.drop_index(b.f("ix_lr_runs_status"))
    op.drop_table("lr_runs")
