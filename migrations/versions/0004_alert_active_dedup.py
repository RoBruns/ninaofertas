"""Garante apenas um alerta ativo por dono e chave de deduplicacao."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_alerts_owner_dedup_status", "alerts", type_="unique")
    # A constraint antiga permitia um open e um acknowledged para a mesma
    # chave. Preserve o mais recente e encerre qualquer duplicata preexistente
    # antes de instalar a garantia correta.
    op.execute(
        """
        WITH ranked AS (
          SELECT id,
                 row_number() OVER (
                   PARTITION BY owner_id, dedup_key
                   ORDER BY last_seen_at DESC, first_seen_at DESC, id
                 ) AS position
          FROM alerts
          WHERE status IN ('open', 'acknowledged')
        )
        UPDATE alerts
        SET status = 'resolved', resolved_at = COALESCE(resolved_at, now())
        FROM ranked
        WHERE alerts.id = ranked.id AND ranked.position > 1
        """
    )
    op.create_index(
        "uq_alerts_owner_dedup_active",
        "alerts",
        ["owner_id", "dedup_key"],
        unique=True,
        postgresql_where=text("status IN ('open', 'acknowledged')"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_owner_dedup_active", table_name="alerts")
    op.create_unique_constraint(
        "uq_alerts_owner_dedup_status",
        "alerts",
        ["owner_id", "dedup_key", "status"],
        deferrable=True,
    )
