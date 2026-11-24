"""Espelho sempre ativo em todos os bots (sem toggle)."""

from alembic import op

revision = "0016_mirror_always_on"
down_revision = "0015_nina1_platform_listen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Garante chave mirror.enabled=true sem apagar o resto do settings.
    op.execute(
        """
        UPDATE bots
        SET settings = jsonb_set(
            CASE
                WHEN jsonb_typeof(settings->'mirror') = 'object' THEN settings
                ELSE jsonb_set(COALESCE(settings, '{}'::jsonb), '{mirror}', '{}'::jsonb, true)
            END,
            '{mirror,enabled}',
            'true'::jsonb,
            true
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE bots
        SET settings = jsonb_set(
            COALESCE(settings, '{}'::jsonb),
            '{mirror,enabled}',
            'false'::jsonb,
            true
        )
        WHERE settings ? 'mirror'
        """
    )
