"""Add provider enrichment, run accounting, and reviewed aliases."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260825_01"
down_revision = "20260824_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "restaurant_enrichments",
        sa.Column(
            "restaurant_id",
            sa.Text(),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("provider_place_id", sa.Text()),
        sa.Column("match_status", sa.Text(), nullable=False),
        sa.Column("match_method", sa.Text()),
        sa.Column("match_score", sa.Double()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("provider_release", sa.Text()),
        sa.Column("primary_category", sa.Text()),
        sa.Column("category_hierarchy", postgresql.ARRAY(sa.Text())),
        sa.Column("alternate_categories", postgresql.ARRAY(sa.Text())),
        sa.Column("operating_status", sa.Text()),
        sa.Column("provider_confidence", sa.Double()),
        sa.Column("address", sa.Text()),
        sa.Column("phones", postgresql.ARRAY(sa.Text())),
        sa.Column("websites", postgresql.ARRAY(sa.Text())),
        sa.Column("attribution", postgresql.JSONB()),
        sa.CheckConstraint(
            "provider IN ('overture', 'google_places')",
            name="valid_enrichment_provider",
        ),
        sa.CheckConstraint(
            "match_status IN ('matched', 'unmatched', 'ambiguous')",
            name="valid_enrichment_match_status",
        ),
        sa.CheckConstraint(
            "operating_status IS NULL OR operating_status IN "
            "('open', 'temporarily_closed', 'permanently_closed')",
            name="valid_enrichment_operating_status",
        ),
        sa.CheckConstraint(
            "provider <> 'google_places' OR "
            "(provider_release IS NULL AND primary_category IS NULL AND "
            "category_hierarchy IS NULL AND alternate_categories IS NULL AND "
            "operating_status IS NULL AND provider_confidence IS NULL AND "
            "address IS NULL AND phones IS NULL AND websites IS NULL AND "
            "attribution IS NULL)",
            name="google_content_not_persisted",
        ),
    )
    op.create_index(
        "ix_restaurant_enrichments_provider_place",
        "restaurant_enrichments",
        ["provider", "provider_place_id"],
    )
    op.create_index(
        "ix_restaurant_enrichments_provider_checked",
        "restaurant_enrichments",
        ["provider", "last_checked_at"],
    )

    op.create_table(
        "enrichment_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unmatched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ambiguous_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.CheckConstraint(
            "provider IN ('overture', 'google_places')",
            name="valid_enrichment_run_provider",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_enrichment_run_status",
        ),
    )
    op.create_index(
        "ix_enrichment_runs_provider_started",
        "enrichment_runs",
        ["provider", "started_at"],
    )

    op.create_table(
        "restaurant_aliases",
        sa.Column(
            "alias_restaurant_id",
            sa.Text(),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "canonical_restaurant_id",
            sa.Text(),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "alias_restaurant_id <> canonical_restaurant_id",
            name="restaurant_alias_not_self",
        ),
    )
    op.create_index(
        "ix_restaurant_aliases_canonical",
        "restaurant_aliases",
        ["canonical_restaurant_id"],
    )
    op.execute(
        """
        CREATE FUNCTION redirect_restaurant_reference_alias()
        RETURNS trigger AS $$
        DECLARE
            resolved_restaurant_id text;
        BEGIN
            SELECT canonical_restaurant_id INTO resolved_restaurant_id
            FROM restaurant_aliases
            WHERE alias_restaurant_id = NEW.restaurant_id;
            IF resolved_restaurant_id IS NOT NULL THEN
                NEW.restaurant_id := resolved_restaurant_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER redirect_restaurant_reference_alias
        BEFORE INSERT OR UPDATE OF restaurant_id ON restaurant_references
        FOR EACH ROW EXECUTE FUNCTION redirect_restaurant_reference_alias()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER redirect_restaurant_reference_alias ON restaurant_references")
    op.execute("DROP FUNCTION redirect_restaurant_reference_alias()")
    op.drop_table("restaurant_aliases")
    op.drop_table("enrichment_runs")
    op.drop_table("restaurant_enrichments")
