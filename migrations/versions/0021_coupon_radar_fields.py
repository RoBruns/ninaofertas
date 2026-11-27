"""Campos extras do radar de cupons (parity pega-oferta)."""

from __future__ import annotations

from alembic import op

revision = "0021_coupon_radar_fields"
down_revision = "0020_feed_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE coupon_radar
            ADD COLUMN IF NOT EXISTS min_value NUMERIC(14,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS validity TEXT,
            ADD COLUMN IF NOT EXISTS report_count INTEGER NOT NULL DEFAULT 0
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE coupon_radar
            DROP COLUMN IF EXISTS min_value,
            DROP COLUMN IF EXISTS validity,
            DROP COLUMN IF EXISTS report_count
        """
    )
