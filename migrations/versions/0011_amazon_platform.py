"""Plataforma Amazon para etiqueta de associado."""

from alembic import op

revision = "0011_amazon_platform"
down_revision = "0010_task_boards"
branch_labels = None
depends_on = None

_CAPABILITIES = (
    '{"offers": true, "affiliate_link": true, '
    '"coupons": false, "commission_api": false}'
)


def upgrade() -> None:
    op.execute(
        "INSERT INTO platforms (slug, name, is_active, capabilities) "
        "VALUES ("
        "'amazon', 'Amazon', true, "
        f"'{_CAPABILITIES}'::jsonb"
        ") ON CONFLICT (slug) DO UPDATE "
        "SET name = EXCLUDED.name, "
        "capabilities = EXCLUDED.capabilities, "
        "is_active = true"
    )


def downgrade() -> None:
    op.execute("DELETE FROM platforms WHERE slug = 'amazon'")
