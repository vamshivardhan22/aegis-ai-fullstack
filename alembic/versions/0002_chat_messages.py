"""Add persisted per-user chat history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_chat_messages"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create chat history table and access-pattern indexes."""
    bind = op.get_bind()
    if "chat_messages" in inspect(bind).get_table_names():
        return
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_user_created", "chat_messages", ["user_id", "created_at"])
    op.create_index("ix_chat_messages_project_created", "chat_messages", ["project_id", "created_at"])


def downgrade() -> None:
    """Remove persisted chat history."""
    bind = op.get_bind()
    if "chat_messages" not in inspect(bind).get_table_names():
        return
    op.drop_index("ix_chat_messages_project_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_user_created", table_name="chat_messages")
    op.drop_table("chat_messages")
