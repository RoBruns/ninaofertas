"""Chumba is_platform_listen no telefone com rótulo Nina 1."""

from alembic import op

revision = "0015_nina1_platform_listen"
down_revision = "0014_mirror_platform_capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE phones SET is_platform_listen = false")
    op.execute(
        """
        UPDATE phones
        SET is_platform_listen = true
        WHERE id = (
            SELECT id FROM phones
            WHERE lower(trim(label)) = 'nina 1'
            ORDER BY created_at
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    op.execute("UPDATE phones SET is_platform_listen = false")
