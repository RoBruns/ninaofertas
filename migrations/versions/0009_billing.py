"""Planos, assinaturas manuais e livro-razão imutável de MRR."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0009_billing"
down_revision = "0008_phone_instance_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.Text(), nullable=False, server_default="BRL"),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("limits", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("interval IN ('month', 'year')", name="ck_plans_interval"),
        sa.CheckConstraint("price >= 0", name="ck_plans_price"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("plan_id", UUID(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True)),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("provider", sa.Text()),
        sa.Column("provider_ref", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'canceled', 'comp')",
            name="ck_subscriptions_status",
        ),
        sa.CheckConstraint("interval IN ('month', 'year')", name="ck_subscriptions_interval"),
        sa.CheckConstraint("price >= 0", name="ck_subscriptions_price"),
    )
    op.create_table(
        "subscription_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("subscription_id", UUID(), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("status_before", sa.Text()),
        sa.Column("status_after", sa.Text(), nullable=False),
        sa.Column("mrr_before", sa.Numeric(14, 2), nullable=False),
        sa.Column("mrr_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", UUID(), sa.ForeignKey("users.id")),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint(
            "type IN ('created', 'plan_changed', 'price_changed', 'status_changed', 'canceled', 'reactivated')",
            name="ck_subscription_events_type",
        ),
    )
    op.create_index(
        "ix_subscription_events_tenant_occurred",
        "subscription_events",
        ["tenant_id", "occurred_at"],
    )
    op.execute(
        "INSERT INTO plans (code, name, price, interval) VALUES ('beta', 'Beta', 0, 'month')"
    )
    # O livro-razão não permite reescrever nem apagar o histórico.
    op.execute("""CREATE FUNCTION billing_events_insert_only() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'subscription_events permite somente inserção'; END;
        $$ LANGUAGE plpgsql""")
    op.execute("""CREATE TRIGGER subscription_events_insert_only
        BEFORE UPDATE OR DELETE ON subscription_events
        FOR EACH ROW EXECUTE FUNCTION billing_events_insert_only()""")


def downgrade() -> None:
    op.drop_table("subscription_events")
    op.execute("DROP FUNCTION billing_events_insert_only()")
    op.drop_table("subscriptions")
    op.drop_table("plans")
