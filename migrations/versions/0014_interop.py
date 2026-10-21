"""에이전트 상호운용 맵: 위임 작업(A2A) · 도구 호출 감사 기록

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-21

위임 작업은 몇 분~몇 시간 걸려 서버가 다시 떠도 남아야 하고(IO4), 도구 호출 · 위임은 추적 id 로 이어 신뢰 경계를 넘은 결과를
표시해야 한다(IO6). idem_key 로 같은 위임 요청이 두 번 와도 작업은 하나.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interop_tasks",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("peer", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("skill", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted"),
        sa.Column("idem_key", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("trace_key", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("input", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("output", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("interop_tasks", schema=None) as b:
        for col in ("direction", "status", "idem_key", "trace_key", "created_at"):
            b.create_index(b.f(f"ix_interop_tasks_{col}"), [col], unique=False)
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trace_key", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("client", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("target", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("scope", sa.String(length=10), nullable=False, server_default="read"),
        sa.Column("args", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="ok"),
        sa.Column("untrusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tool_calls", schema=None) as b:
        for col in ("trace_key", "channel", "status", "created_at"):
            b.create_index(b.f(f"ix_tool_calls_{col}"), [col], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tool_calls", schema=None) as b:
        for col in ("created_at", "status", "channel", "trace_key"):
            b.drop_index(b.f(f"ix_tool_calls_{col}"))
    op.drop_table("tool_calls")
    with op.batch_alter_table("interop_tasks", schema=None) as b:
        for col in ("created_at", "trace_key", "idem_key", "status", "direction"):
            b.drop_index(b.f(f"ix_interop_tasks_{col}"))
    op.drop_table("interop_tasks")
