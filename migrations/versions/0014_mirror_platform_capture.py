"""Captura neutra do espelho + telefone de escuta da plataforma."""

from alembic import op

revision = "0014_mirror_platform_capture"
down_revision = "0013_mirror_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE phones ADD COLUMN IF NOT EXISTS "
        "is_platform_listen BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_phones_one_platform_listen "
        "ON phones ((true)) WHERE is_platform_listen"
    )
    op.execute(
        """
        CREATE TABLE mirror_captures (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            listen_phone_id UUID NOT NULL REFERENCES phones(id) ON DELETE CASCADE,
            source_whatsapp_id TEXT NOT NULL,
            source_group_name TEXT,
            message_key TEXT NOT NULL,
            body_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'routed',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_mirror_captures_phone_key UNIQUE (listen_phone_id, message_key)
        )
        """
    )
    op.execute(
        "ALTER TABLE mirror_inbox ADD COLUMN IF NOT EXISTS "
        "capture_id UUID REFERENCES mirror_captures(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mirror_inbox_capture "
        "ON mirror_inbox (capture_id) WHERE capture_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mirror_inbox_capture")
    op.execute("ALTER TABLE mirror_inbox DROP COLUMN IF EXISTS capture_id")
    op.execute("DROP TABLE IF EXISTS mirror_captures")
    op.execute("DROP INDEX IF EXISTS uq_phones_one_platform_listen")
    op.execute("ALTER TABLE phones DROP COLUMN IF EXISTS is_platform_listen")
