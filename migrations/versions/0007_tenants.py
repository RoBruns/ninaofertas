"""Contas acima dos usuários, sem reescrever os donos existentes."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _owner_foreign_keys(target: str) -> None:
    inspector = sa.inspect(op.get_bind())
    for table in inspector.get_table_names():
        for fk in inspector.get_foreign_keys(table):
            if fk["constrained_columns"] == ["owner_id"]:
                op.drop_constraint(fk["name"], table, type_="foreignkey")
                op.create_foreign_key(fk["name"], table, target, ["owner_id"], ["id"])


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column(
            "id", postgresql.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status"),
    )
    op.execute(
        "INSERT INTO tenants (id, name, is_internal) SELECT id, coalesce(name, email), true FROM users"
    )
    op.add_column("users", sa.Column("tenant_id", postgresql.UUID(), sa.ForeignKey("tenants.id")))
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.execute("UPDATE users SET tenant_id = id, is_platform_admin = (role = 'admin')")
    op.alter_column("users", "tenant_id", nullable=False)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    _owner_foreign_keys("tenants")
    for table in ("audit_logs", "events"):
        op.add_column(table, sa.Column("tenant_id", postgresql.UUID(), sa.ForeignKey("tenants.id")))
        op.create_index(
            f"ix_{table}_tenant_created", table, ["tenant_id", sa.text("created_at DESC")]
        )
    op.execute(
        "UPDATE audit_logs a SET tenant_id = u.tenant_id FROM users u WHERE a.user_id = u.id"
    )
    op.execute("UPDATE events e SET tenant_id = b.owner_id FROM bots b WHERE e.bot_id = b.id")
    op.create_index(
        "uq_phones_evolution_instance",
        "phones",
        ["evolution_instance"],
        unique=True,
        postgresql_where=sa.text("evolution_instance IS NOT NULL"),
    )
    op.execute(
        "UPDATE bots SET settings = jsonb_set(coalesce(settings, '{}'::jsonb), '{content}', coalesce(settings->'content', '{}'::jsonb) || '{\"recado_instagram\": true}'::jsonb)"
    )


def downgrade() -> None:
    # Contas criadas após S1 recebem um usuário representativo para restaurar as
    # FKs antigas. Na operação migrada o usuário de mesmo UUID já existe.
    op.execute("""INSERT INTO users (id, tenant_id, email, password_hash, name, role, is_active)
        SELECT t.id, t.id, 'downgrade-' || t.id::text || '@invalid.local', '!', t.name, 'viewer', false
        FROM tenants t WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = t.id)""")
    _owner_foreign_keys("users")
    op.execute("UPDATE bots SET settings = settings #- '{content,recado_instagram}'")
    op.execute("UPDATE bots SET settings = settings - 'content' WHERE settings->'content' = '{}'::jsonb")
    op.drop_index("uq_phones_evolution_instance", table_name="phones")
    for table in ("events", "audit_logs"):
        op.drop_index(f"ix_{table}_tenant_created", table_name=table)
        op.drop_column(table, "tenant_id")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_column("users", "is_platform_admin")
    op.drop_column("users", "tenant_id")
    op.drop_table("tenants")
