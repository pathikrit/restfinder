"""Normalize all-uppercase restaurant display names."""

from alembic import op
import sqlalchemy as sa

from restfinder.names import display_name

revision = "20260824_03"
down_revision = "20260824_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM restaurants")).all()
    updates = [
        {"id": identifier, "name": formatted}
        for identifier, name in rows
        if (formatted := display_name(name)) != name
    ]
    statement = sa.text("UPDATE restaurants SET name = :name WHERE id = :id")
    for start in range(0, len(updates), 1_000):
        connection.execute(statement, updates[start : start + 1_000])


def downgrade() -> None:
    # Source capitalization is not recoverable after normalization.
    pass
