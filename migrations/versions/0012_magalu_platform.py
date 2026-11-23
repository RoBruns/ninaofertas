"""Plataforma Magalu para conta do Magazine Você."""

from alembic import op

revision = "0012_magalu_platform"
down_revision = "0011_amazon_platform"
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
        "'magalu', 'Magalu', true, "
        f"'{_CAPABILITIES}'::jsonb"
        ") ON CONFLICT (slug) DO UPDATE "
        "SET name = EXCLUDED.name, "
        "capabilities = EXCLUDED.capabilities, "
        "is_active = true"
    )


def downgrade() -> None:
    op.execute("DELETE FROM platforms WHERE slug = 'magalu'")
