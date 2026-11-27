"""Fontes de coleta (Promobit/RSS) por tenant — Nina V3."""

from __future__ import annotations

from alembic import op

revision = "0020_feed_sources"
down_revision = "0019_nina_v3_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES tenants(id),
            slug TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            url TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT false,
            last_collected_at TIMESTAMPTZ,
            last_error TEXT,
            total_collected INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, slug)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_feed_sources_owner_enabled "
        "ON feed_sources (owner_id, enabled)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feed_sources")
