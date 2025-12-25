"""remove obsolete phase1 tables

Revision ID: f7d4155836c3
Revises: f1c2d3e4f5a6
Create Date: 2025-12-25 10:49:55.078208

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7d4155836c3"
down_revision: Union[str, Sequence[str], None] = "f1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop obsolete Phase 1 tables."""
    # Drop in reverse dependency order
    op.drop_table("experience_pois")
    op.drop_table("base_assignments")
    op.drop_table("experiences")
    op.drop_table("pois")


def downgrade() -> None:
    """Recreate tables if downgrade is needed."""
    # Pois table
    op.create_table(
        "pois",
        sa.Column("poi_id", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("poi_id"),
    )

    # Experiences table
    op.create_table(
        "experiences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_item_id", sa.Integer(), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False),
        sa.Column("activity_type", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("place_mentions", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_item_id"],
            ["content_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_item_id", "summary", name="uq_exp_content_summary"
        ),
    )
    op.create_index(
        op.f("ix_experiences_content_item_id"),
        "experiences",
        ["content_item_id"],
        unique=False,
    )

    # Base assignments table
    op.create_table(
        "base_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base_name", sa.String(length=128), nullable=False),
        sa.Column("poi_id", sa.String(length=160), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["poi_id"],
            ["pois.poi_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("base_name", "poi_id", name="uq_base_poi"),
    )
    op.create_index(
        op.f("ix_base_assignments_base_name"),
        "base_assignments",
        ["base_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_base_assignments_poi_id"), "base_assignments", ["poi_id"], unique=False
    )

    # Experience pois table
    op.create_table(
        "experience_pois",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experience_id", sa.Integer(), nullable=False),
        sa.Column("poi_id", sa.String(length=160), nullable=False),
        sa.Column("mention_text", sa.String(length=256), nullable=False),
        sa.Column("link_confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experience_id"],
            ["experiences.id"],
        ),
        sa.ForeignKeyConstraint(
            ["poi_id"],
            ["pois.poi_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experience_id", "poi_id", "mention_text", name="uq_exp_poi_mention"
        ),
    )
    op.create_index(
        op.f("ix_experience_pois_experience_id"),
        "experience_pois",
        ["experience_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experience_pois_poi_id"), "experience_pois", ["poi_id"], unique=False
    )
