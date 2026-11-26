"""Configuração de plataforma (allowlist do espelho no banco)."""

from __future__ import annotations

from alembic import op

revision = "0018_platform_settings"
down_revision = "0017_mirror_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_settings (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_settings")
