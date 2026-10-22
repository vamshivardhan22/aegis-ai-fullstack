"""Bootstrap the schema defined by the initial Aegis SQLAlchemy models.

This is the baseline migration for fresh installations. Subsequent schema changes
must use explicit Alembic revisions; do not modify this revision after release.
"""
from alembic import op

from src.database.base import Base
from src.database import models  # noqa: F401

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the initial metadata schema."""
    bind = op.get_bind()
    tables = [table for table in Base.metadata.sorted_tables if table.name != "chat_messages"]\n    Base.metadata.create_all(bind=bind, tables=tables)


def downgrade() -> None:
    """Drop the initial metadata schema."""
    bind = op.get_bind()
    tables = [table for table in reversed(Base.metadata.sorted_tables) if table.name != "chat_messages"]\n    Base.metadata.drop_all(bind=bind, tables=tables)
