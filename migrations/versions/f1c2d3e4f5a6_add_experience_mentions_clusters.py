"""add experience mentions and clusters

Revision ID: f1c2d3e4f5a6
Revises: c3f8b0ad3a2c
Create Date: 2025-12-25 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "c3f8b0ad3a2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "experience_mentions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_item_id", sa.Integer(), nullable=False),
        sa.Column("entity_name", sa.String(length=256), nullable=False),
        sa.Column("entity_type", sa.String(length=48), nullable=False),
        sa.Column("experience_text", sa.Text(), nullable=False),
        sa.Column(
            "recommendation_score",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("location_hint", sa.Text(), nullable=False),
        sa.Column("location_confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("evidence_spans", sa.Text(), nullable=True),
        sa.Column("negative_or_caution", sa.Text(), nullable=True),
        sa.Column("canonicalization_hint", sa.Text(), nullable=True),
        sa.Column("assigned_base", sa.String(length=128), nullable=False),
        sa.Column(
            "assigned_base_confidence",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_item_id",
            "entity_name",
            "experience_text",
            name="uq_mention_content_entity_text",
        ),
    )
    op.create_index(
        op.f("ix_experience_mentions_content_item_id"),
        "experience_mentions",
        ["content_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experience_mentions_assigned_base"),
        "experience_mentions",
        ["assigned_base"],
        unique=False,
    )

    op.create_table(
        "experience_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base_name", sa.String(length=128), nullable=False),
        sa.Column("canonical_name", sa.String(length=256), nullable=False),
        sa.Column("entity_type", sa.String(length=48), nullable=False),
        sa.Column("normalized_key", sa.String(length=256), nullable=False),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagement_sum", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recency_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "base_name",
            "normalized_key",
            "entity_type",
            name="uq_cluster_base_key_type",
        ),
    )
    op.create_index(
        op.f("ix_experience_clusters_base_name"),
        "experience_clusters",
        ["base_name"],
        unique=False,
    )

    op.create_table(
        "experience_cluster_mentions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("mention_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["experience_clusters.id"]),
        sa.ForeignKeyConstraint(["mention_id"], ["experience_mentions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", "mention_id", name="uq_cluster_mention"),
    )
    op.create_index(
        op.f("ix_experience_cluster_mentions_cluster_id"),
        "experience_cluster_mentions",
        ["cluster_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experience_cluster_mentions_mention_id"),
        "experience_cluster_mentions",
        ["mention_id"],
        unique=False,
    )

    op.alter_column("experience_mentions", "recommendation_score", server_default=None)
    op.alter_column("experience_mentions", "location_confidence", server_default=None)
    op.alter_column(
        "experience_mentions", "assigned_base_confidence", server_default=None
    )
    op.alter_column("experience_clusters", "support_count", server_default=None)
    op.alter_column("experience_clusters", "engagement_sum", server_default=None)
    op.alter_column("experience_clusters", "recency_score", server_default=None)
    op.alter_column("experience_clusters", "confidence", server_default=None)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_experience_cluster_mentions_mention_id"),
        table_name="experience_cluster_mentions",
    )
    op.drop_index(
        op.f("ix_experience_cluster_mentions_cluster_id"),
        table_name="experience_cluster_mentions",
    )
    op.drop_table("experience_cluster_mentions")
    op.drop_index(
        op.f("ix_experience_clusters_base_name"),
        table_name="experience_clusters",
    )
    op.drop_table("experience_clusters")
    op.drop_index(
        op.f("ix_experience_mentions_assigned_base"),
        table_name="experience_mentions",
    )
    op.drop_index(
        op.f("ix_experience_mentions_content_item_id"),
        table_name="experience_mentions",
    )
    op.drop_table("experience_mentions")
