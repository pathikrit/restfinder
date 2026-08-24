"""Add curated restaurant type."""

from alembic import op
import sqlalchemy as sa

revision = "20260824_02"
down_revision = "20260824_01"
branch_labels = None
depends_on = None

RESTAURANT_TYPES = (
    "Restaurant",
    "Bars",
    "Coffee Shops",
    "Dessert",
    "Fast Food",
    "Hidden / Speakeasy",
)


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("type", sa.Text(), nullable=True))
    allowed = ", ".join(f"'{value}'" for value in RESTAURANT_TYPES)
    op.create_check_constraint(
        "valid_restaurant_type",
        "restaurants",
        f"type IS NULL OR type IN ({allowed})",
    )


def downgrade() -> None:
    op.drop_constraint("valid_restaurant_type", "restaurants", type_="check")
    op.drop_column("restaurants", "type")
