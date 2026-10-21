"""지식 그래프 · GraphRAG 맵(K5)의 내장 그래프 저장소: 노드 · 관계 테이블

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-21

그래프 DB 서버(Neo4j) 없이도 그래프를 만들고 이웃 확장 · 커뮤니티 탐지를 할 수 있게 앱 DB 에 노드 · 관계를 둔다.
Neo4j 를 연결하면 이 그래프를 그대로 옮겨 Text2Cypher 를 돌린다(원본은 여기). (graph, label, key) · (graph, src, dst, type) 를
유일하게 두어 같은 자료를 다시 적재해도 개체 · 관계가 늘지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kg_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("graph", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("props", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph", "label", "key", name="uq_kg_node"),
    )
    with op.batch_alter_table("kg_nodes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_kg_nodes_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_kg_nodes_graph"), ["graph"], unique=False)
        batch_op.create_index(batch_op.f("ix_kg_nodes_label"), ["label"], unique=False)
    op.create_table(
        "kg_edges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("graph", sa.String(length=50), nullable=False),
        sa.Column("src", sa.Integer(), nullable=False),
        sa.Column("dst", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("props", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["dst"], ["kg_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["src"], ["kg_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph", "src", "dst", "type", name="uq_kg_edge"),
    )
    with op.batch_alter_table("kg_edges", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_kg_edges_dst"), ["dst"], unique=False)
        batch_op.create_index(batch_op.f("ix_kg_edges_graph"), ["graph"], unique=False)
        batch_op.create_index(batch_op.f("ix_kg_edges_src"), ["src"], unique=False)
        batch_op.create_index(batch_op.f("ix_kg_edges_type"), ["type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("kg_edges", schema=None) as batch_op:
        for ix in ("ix_kg_edges_type", "ix_kg_edges_src", "ix_kg_edges_graph", "ix_kg_edges_dst"):
            batch_op.drop_index(batch_op.f(ix))
    op.drop_table("kg_edges")
    with op.batch_alter_table("kg_nodes", schema=None) as batch_op:
        for ix in ("ix_kg_nodes_label", "ix_kg_nodes_graph", "ix_kg_nodes_document_id"):
            batch_op.drop_index(batch_op.f(ix))
    op.drop_table("kg_nodes")
