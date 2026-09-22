"""Baseline do schema legado e extensões obrigatórias."""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Não cria, renomeia ou altera ofertas/envios: apenas adota o estado atual.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public")


def downgrade() -> None:
    # Extensões são globais ao banco e podem ter outros consumidores. Removê-las
    # num downgrade da aplicação seria destrutivo.
    pass
