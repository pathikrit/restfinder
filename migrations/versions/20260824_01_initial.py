"""Create restaurants and restaurant references."""

from alembic import op
import sqlalchemy as sa

revision = "20260824_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cuisine", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("latitude", sa.Double()),
        sa.Column("longitude", sa.Double()),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_permanently_closed", sa.Boolean()),
        sa.Column("permanent_closure_checked_at", sa.DateTime(timezone=True)),
        sa.Column("is_chain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="valid_latitude"),
        sa.CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="valid_longitude"),
    )
    op.create_index("ix_restaurants_source_last_seen", "restaurants", ["source", "last_seen"])
    op.create_index("ix_restaurants_is_chain", "restaurants", ["is_chain"])

    op.create_table(
        "restaurant_references",
        sa.Column(
            "restaurant_id",
            sa.Text(),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("reference", sa.Text(), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_restaurant_references_reference", "restaurant_references", ["reference"])


def downgrade() -> None:
    op.drop_table("restaurant_references")
    op.drop_table("restaurants")
