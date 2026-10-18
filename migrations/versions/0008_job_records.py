"""백그라운드 작업 기록 (재시작해도 상태 · 결과 유지)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("job_records") as b:
        b.create_index("ix_job_records_kind", ["kind"])
        b.create_index("ix_job_records_created_at", ["created_at"])


def downgrade() -> None:
    with op.batch_alter_table("job_records") as b:
        b.drop_index("ix_job_records_created_at")
        b.drop_index("ix_job_records_kind")
    op.drop_table("job_records")
