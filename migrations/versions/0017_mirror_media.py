"""Mídia do espelho: flag e caminho local da foto capturada."""

from __future__ import annotations

from alembic import op

revision = "0017_mirror_media"
down_revision = "0016_mirror_always_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mirror_captures ADD COLUMN IF NOT EXISTS "
        "has_media BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE mirror_captures ADD COLUMN IF NOT EXISTS media_path TEXT"
    )
    op.execute(
        "ALTER TABLE mirror_inbox ADD COLUMN IF NOT EXISTS "
        "has_media BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE mirror_inbox ADD COLUMN IF NOT EXISTS media_path TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE mirror_inbox DROP COLUMN IF EXISTS media_path")
    op.execute("ALTER TABLE mirror_inbox DROP COLUMN IF EXISTS has_media")
    op.execute("ALTER TABLE mirror_captures DROP COLUMN IF EXISTS media_path")
    op.execute("ALTER TABLE mirror_captures DROP COLUMN IF EXISTS has_media")
