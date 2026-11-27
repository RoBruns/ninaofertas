"""Tabelas operacionais Nina V3: cupons, VIP, monitor de preço."""

from __future__ import annotations

from alembic import op

revision = "0019_nina_v3_ops"
down_revision = "0018_platform_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS coupon_radar (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES tenants(id),
            code TEXT NOT NULL,
            store TEXT,
            title TEXT,
            url TEXT,
            status TEXT NOT NULL DEFAULT 'ativo',
            source_group_name TEXT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_coupon_radar_owner_status "
        "ON coupon_radar (owner_id, status)"
    )
    # matched_offer_id referencia ofertas (tabela legada, fora do Alembic).
    # Em banco novo a tabela pode ainda não existir — cria sem FK e amarra depois.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vip_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES tenants(id),
            contact_name TEXT NOT NULL,
            contact_phone TEXT,
            wish_product TEXT NOT NULL,
            max_price NUMERIC(14,2) NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            matched_offer_id INTEGER,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'ofertas'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'vip_requests_matched_offer_id_fkey'
            ) THEN
                ALTER TABLE vip_requests
                    ADD CONSTRAINT vip_requests_matched_offer_id_fkey
                    FOREIGN KEY (matched_offer_id) REFERENCES ofertas(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vip_requests_owner_status "
        "ON vip_requests (owner_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS price_monitors (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES tenants(id),
            url TEXT NOT NULL,
            title TEXT,
            image_url TEXT,
            target_price NUMERIC(14,2) NOT NULL,
            last_price NUMERIC(14,2),
            status TEXT NOT NULL DEFAULT 'monitorando',
            last_checked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_price_monitors_owner_status "
        "ON price_monitors (owner_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS price_monitors")
    op.execute("DROP TABLE IF EXISTS vip_requests")
    op.execute("DROP TABLE IF EXISTS coupon_radar")
