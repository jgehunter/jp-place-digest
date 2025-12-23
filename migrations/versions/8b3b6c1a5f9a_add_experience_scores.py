from alembic import op
import sqlalchemy as sa

revision = "8b3b6c1a5f9a"
down_revision = "d2cbc0b5b6c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiences", sa.Column("recommendation_score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("experiences", sa.Column("evidence", sa.Text(), nullable=True))
    op.alter_column("experiences", "recommendation_score", server_default=None)


def downgrade() -> None:
    op.drop_column("experiences", "evidence")
    op.drop_column("experiences", "recommendation_score")
