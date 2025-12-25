from alembic import op
import sqlalchemy as sa

revision = "c3f8b0ad3a2c"
down_revision = ("8b3b6c1a5f9a", "a381f72a2a01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiences", sa.Column("location_hint", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("experiences", "location_hint")
