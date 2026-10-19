"""검증 라벨에 질문 관련성 판정 추가 (근거 일치 판정과 따로)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19

사람 판정 28개가 '근거에 있는가'가 아니라 '질문에 답하는가'를 기준으로 매겨졌다는 것이 드러나, 두 판정을 따로 받는다.
label(근거 일치)은 판정하지 않을 수도 있으므로 비울 수 있게 바꾼다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("verify_labels") as b:
        b.add_column(sa.Column("relevant", sa.Boolean(), nullable=True))
        b.alter_column("label", existing_type=sa.Boolean(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("verify_labels") as b:
        b.alter_column("label", existing_type=sa.Boolean(), nullable=False)
        b.drop_column("relevant")
