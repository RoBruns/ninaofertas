"""Bots de teste e histórico de configuração."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bots", sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column("bots", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column(
        "bots",
        sa.Column(
            "test_source_bot_id", postgresql.UUID(), sa.ForeignKey("bots.id", ondelete="SET NULL")
        ),
    )
    op.create_table(
        "bot_config_backups",
        sa.Column(
            "id", postgresql.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("owner_id", postgresql.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "bot_id",
            postgresql.UUID(),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("message_template", sa.Text()),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "source_bot_id", postgresql.UUID(), sa.ForeignKey("bots.id", ondelete="SET NULL")
        ),
        sa.Column("created_by", postgresql.UUID(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_bot_config_backups_bot_created",
        "bot_config_backups",
        ["bot_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("bot_config_backups")
    op.drop_column("bots", "test_source_bot_id")
    op.drop_column("bots", "archived_at")
    op.drop_column("bots", "is_test")
