"""Adiciona relacionamentos opcionais ao schema legado."""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF to_regclass('envios') IS NOT NULL THEN
            ALTER TABLE envios ADD COLUMN bot_id UUID NULL;
            ALTER TABLE envios ADD COLUMN group_id UUID NULL;
            ALTER TABLE envios ADD COLUMN sub_id TEXT NULL;
            ALTER TABLE envios ADD CONSTRAINT fk_envios_bot FOREIGN KEY (bot_id) REFERENCES bots(id);
            ALTER TABLE envios ADD CONSTRAINT fk_envios_group FOREIGN KEY (group_id) REFERENCES groups(id);
          END IF;
          IF to_regclass('ofertas') IS NOT NULL THEN
            ALTER TABLE ofertas ADD COLUMN platform_account_id UUID NULL;
            ALTER TABLE ofertas ADD CONSTRAINT fk_ofertas_platform_account
              FOREIGN KEY (platform_account_id) REFERENCES platform_accounts(id);
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF to_regclass('envios') IS NOT NULL THEN
            ALTER TABLE envios DROP CONSTRAINT IF EXISTS fk_envios_bot;
            ALTER TABLE envios DROP CONSTRAINT IF EXISTS fk_envios_group;
            ALTER TABLE envios DROP COLUMN IF EXISTS bot_id;
            ALTER TABLE envios DROP COLUMN IF EXISTS group_id;
            ALTER TABLE envios DROP COLUMN IF EXISTS sub_id;
          END IF;
          IF to_regclass('ofertas') IS NOT NULL THEN
            ALTER TABLE ofertas DROP CONSTRAINT IF EXISTS fk_ofertas_platform_account;
            ALTER TABLE ofertas DROP COLUMN IF EXISTS platform_account_id;
          END IF;
        END $$;
        """
    )
