"""Contas acima dos usuários, sem reescrever os donos existentes."""

import os

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
    op.execute("UPDATE users SET tenant_id = id")
    op.get_bind().execute(
        sa.text("""UPDATE users SET is_platform_admin = true WHERE id = coalesce(
            (SELECT id FROM users WHERE lower(email::text) = lower(:email)
             ORDER BY created_at, id LIMIT 1),
            (SELECT id FROM users WHERE role = 'admin' AND is_active
             ORDER BY created_at, id LIMIT 1)
        )"""),
        {"email": os.getenv("ADMIN_EMAIL") or None},
    )
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
    # Comparar com o UUID canônico evita casts de valores inválidos no histórico.
    op.execute("""UPDATE audit_logs a SET tenant_id = t.id FROM tenants t
        WHERE a.tenant_id IS NULL AND a.after ? 'owner_id'
        AND lower(a.after->>'owner_id') = t.id::text""")
    op.execute("UPDATE events e SET tenant_id = b.owner_id FROM bots b WHERE e.bot_id = b.id")
    for entity_types, table in (
        ("'platform_account', 'account'", "platform_accounts"),
        ("'group'", "groups"),
        ("'phone'", "phones"),
    ):
        op.execute(f"""UPDATE events e SET tenant_id = entity.owner_id FROM {table} entity
            WHERE e.tenant_id IS NULL AND e.entity_type IN ({entity_types})
            AND lower(e.entity_id) = entity.id::text""")
    for table, name, columns in (
        ("expenses", "uq_expenses_source_external", ["owner_id", "source", "external_id"]),
        ("sales", "uq_sales_platform_external", ["owner_id", "platform_id", "external_id"]),
    ):
        op.drop_constraint(name, table, type_="unique")
        op.create_unique_constraint(name, table, columns)
    op.create_index(
        "uq_phones_evolution_instance",
        "phones",
        ["evolution_instance"],
        unique=True,
        postgresql_where=sa.text("evolution_instance IS NOT NULL"),
    )
    op.execute(
        "UPDATE bots SET settings = jsonb_set(coalesce(settings, '{}'::jsonb), '{content}', (CASE WHEN jsonb_typeof(settings->'content') = 'object' THEN settings->'content' ELSE '{}'::jsonb END) || '{\"recado_instagram\": true}'::jsonb)"
    )


def downgrade() -> None:
    for table, name, columns in (
        ("expenses", "uq_expenses_source_external", ["source", "external_id"]),
        ("sales", "uq_sales_platform_external", ["platform_id", "external_id"]),
    ):
        op.drop_constraint(name, table, type_="unique")
        op.create_unique_constraint(name, table, columns)
    # Contas criadas após S1 recebem um usuário representativo para restaurar as
    # FKs antigas. Na operação migrada o usuário de mesmo UUID já existe.
    op.execute("""INSERT INTO users (id, tenant_id, email, password_hash, name, role, is_active)
        SELECT t.id, t.id, 'downgrade-' || t.id::text || '@invalid.local', '!', t.name, 'viewer', false
        FROM tenants t WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = t.id)""")
    _owner_foreign_keys("users")
    op.execute("UPDATE bots SET settings = settings #- '{content,recado_instagram}'")
    op.execute(
        "UPDATE bots SET settings = settings - 'content' WHERE settings->'content' = '{}'::jsonb"
    )
    op.drop_index("uq_phones_evolution_instance", table_name="phones")
    for table in ("events", "audit_logs"):
        op.drop_index(f"ix_{table}_tenant_created", table_name=table)
        op.drop_column(table, "tenant_id")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_column("users", "is_platform_admin")
    op.drop_column("users", "tenant_id")
    op.drop_table("tenants")
