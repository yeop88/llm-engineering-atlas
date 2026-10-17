"""문서 검색(RAG): 컬렉션·문서·청크 세트·청크·벡터 인덱스, 모델 종류(임베딩/리랭커)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("embedding_models") as batch:
        batch.add_column(sa.Column("kind", sa.String(20), nullable=False, server_default="embedding"))
        batch.create_index("ix_embedding_models_kind", ["kind"])

    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("n_chars", sa.Integer(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_documents_collection_id", "documents", ["collection_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "chunk_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("n_chunks", sa.Integer(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("doc_ids", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chunk_sets_collection_id", "chunk_sets", ["collection_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chunk_set_id", sa.Integer(), sa.ForeignKey("chunk_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("tokens", sa.JSON(), nullable=False),
    )
    op.create_index("ix_chunks_chunk_set_id", "chunks", ["chunk_set_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    op.create_table(
        "vector_indexes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chunk_set_id", sa.Integer(), sa.ForeignKey("chunk_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_hf_id", sa.String(200), nullable=False),
        sa.Column("store", sa.String(20), nullable=False),
        sa.Column("store_collection", sa.String(100), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("truncate_dim", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("n_vectors", sa.Integer(), nullable=False),
        sa.Column("build_seconds", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vector_indexes_chunk_set_id", "vector_indexes", ["chunk_set_id"])


def downgrade() -> None:
    op.drop_table("vector_indexes")
    op.drop_table("chunks")
    op.drop_table("chunk_sets")
    op.drop_table("documents")
    op.drop_table("collections")
    with op.batch_alter_table("embedding_models") as batch:
        batch.drop_index("ix_embedding_models_kind")
        batch.drop_column("kind")
