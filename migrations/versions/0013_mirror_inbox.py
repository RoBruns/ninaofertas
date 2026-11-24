"""Fila de mensagens espelhadas (origem WhatsApp → bot de envio)."""

from alembic import op

revision = "0013_mirror_inbox"
down_revision = "0012_magalu_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE mirror_inbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES tenants(id),
            bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
            listen_phone_id UUID NOT NULL REFERENCES phones(id) ON DELETE CASCADE,
            source_whatsapp_id TEXT NOT NULL,
            source_group_name TEXT,
            message_key TEXT NOT NULL,
            body_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            skip_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ,
            CONSTRAINT uq_mirror_inbox_bot_key UNIQUE (bot_id, message_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_mirror_inbox_pending ON mirror_inbox (status, created_at) "
        "WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mirror_inbox")
