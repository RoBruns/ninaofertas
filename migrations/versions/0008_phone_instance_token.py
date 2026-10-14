"""Token cifrado da instância e número opcional até conectar o WhatsApp."""

from alembic import op
import sqlalchemy as sa

revision = "0008_phone_instance_token"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("phones", sa.Column("instance_token_ciphertext", sa.LargeBinary(), nullable=True))
    op.add_column("phones", sa.Column("instance_token_fingerprint", sa.Text(), nullable=True))
    op.add_column("phones", sa.Column("instance_token_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("phones", "number", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # O contrato anterior exigia número; preserve telefones ainda não conectados.
    op.execute("UPDATE phones SET number = 'pending-' || id::text WHERE number IS NULL")
    op.alter_column("phones", "number", existing_type=sa.Text(), nullable=False)
    op.drop_column("phones", "instance_token_updated_at")
    op.drop_column("phones", "instance_token_fingerprint")
    op.drop_column("phones", "instance_token_ciphertext")
