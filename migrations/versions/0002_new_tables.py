"""Cria as tabelas administrativas e seus índices."""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


DDL = r"""
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, name TEXT, role TEXT NOT NULL DEFAULT 'admin',
  is_active BOOLEAN NOT NULL DEFAULT TRUE, last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY, user_id UUID REFERENCES users(id), entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL, action TEXT NOT NULL, before JSONB, after JSONB, ip INET,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_logs_entity_created_at ON audit_logs (entity_type, entity_id, created_at DESC);
CREATE TABLE platforms (
  id SERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, capabilities JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE platform_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  platform_id INT NOT NULL REFERENCES platforms(id), label TEXT NOT NULL, external_id TEXT,
  status TEXT NOT NULL DEFAULT 'active', config JSONB NOT NULL DEFAULT '{}'::jsonb, notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_platform_accounts_owner_platform_label UNIQUE (owner_id, platform_id, label)
);
CREATE TABLE platform_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES platform_accounts(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, ciphertext BYTEA NOT NULL, key_version INT NOT NULL DEFAULT 1,
  fingerprint TEXT, status TEXT NOT NULL DEFAULT 'unknown', expires_at TIMESTAMPTZ,
  last_rotated_at TIMESTAMPTZ, last_used_at TIMESTAMPTZ, last_success_at TIMESTAMPTZ,
  last_error TEXT, last_error_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_platform_credentials_account_kind UNIQUE (account_id, kind)
);
CREATE TABLE phones (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  label TEXT NOT NULL, number TEXT NOT NULL, evolution_instance TEXT,
  status TEXT NOT NULL DEFAULT 'unknown', last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_phones_owner_number UNIQUE (owner_id, number)
);
CREATE TABLE niches (
  id SERIAL PRIMARY KEY, owner_id UUID NOT NULL REFERENCES users(id), slug TEXT NOT NULL,
  name TEXT NOT NULL, CONSTRAINT uq_niches_owner_slug UNIQUE (owner_id, slug)
);
CREATE TABLE bots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, slug TEXT NOT NULL, niche_id INT REFERENCES niches(id),
  phone_id UUID REFERENCES phones(id), status TEXT NOT NULL DEFAULT 'paused',
  settings JSONB NOT NULL DEFAULT '{}'::jsonb, message_template TEXT,
  last_run_at TIMESTAMPTZ, last_success_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_bots_owner_slug UNIQUE (owner_id, slug)
);
CREATE TABLE groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  phone_id UUID REFERENCES phones(id), whatsapp_id TEXT NOT NULL, name TEXT, participants INT,
  is_announce BOOLEAN, bot_is_admin BOOLEAN, status TEXT NOT NULL DEFAULT 'active',
  discovered_at TIMESTAMPTZ, last_synced_at TIMESTAMPTZ,
  CONSTRAINT uq_groups_phone_whatsapp UNIQUE (phone_id, whatsapp_id)
);
CREATE TABLE bot_groups (
  bot_id UUID REFERENCES bots(id) ON DELETE CASCADE,
  group_id UUID REFERENCES groups(id) ON DELETE CASCADE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY (bot_id, group_id)
);
CREATE TABLE bot_platform_accounts (
  bot_id UUID REFERENCES bots(id) ON DELETE CASCADE,
  account_id UUID REFERENCES platform_accounts(id) ON DELETE CASCADE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY (bot_id, account_id)
);
CREATE TABLE campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, channel TEXT, external_id TEXT, bot_id UUID REFERENCES bots(id),
  niche_id INT REFERENCES niches(id), objective TEXT, status TEXT NOT NULL DEFAULT 'active',
  started_at DATE, ended_at DATE
);
CREATE TABLE expense_categories (
  id SERIAL PRIMARY KEY, owner_id UUID NOT NULL REFERENCES users(id), slug TEXT NOT NULL,
  name TEXT NOT NULL, CONSTRAINT uq_expense_categories_owner_slug UNIQUE (owner_id, slug)
);
CREATE TABLE expenses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  description TEXT NOT NULL, amount NUMERIC(14,2) NOT NULL,
  currency TEXT NOT NULL DEFAULT 'BRL', incurred_on DATE NOT NULL,
  category_id INT REFERENCES expense_categories(id), platform_id INT REFERENCES platforms(id),
  campaign_id UUID REFERENCES campaigns(id), bot_id UUID REFERENCES bots(id),
  niche_id INT REFERENCES niches(id), source TEXT NOT NULL DEFAULT 'manual', external_id TEXT,
  notes TEXT, created_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_expenses_amount_nonnegative CHECK (amount >= 0),
  CONSTRAINT uq_expenses_source_external UNIQUE (source, external_id)
);
CREATE INDEX ix_expenses_owner_incurred_on ON expenses (owner_id, incurred_on DESC);
CREATE TABLE clicks (
  id BIGSERIAL PRIMARY KEY, sub_id TEXT NOT NULL, bot_id UUID REFERENCES bots(id),
  group_id UUID REFERENCES groups(id), oferta_id INT,
  clicked_at TIMESTAMPTZ NOT NULL DEFAULT now(), user_agent TEXT, ip_hash TEXT
);
CREATE TABLE sales (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  account_id UUID REFERENCES platform_accounts(id), platform_id INT NOT NULL REFERENCES platforms(id),
  external_id TEXT NOT NULL, sub_id TEXT, bot_id UUID REFERENCES bots(id),
  group_id UUID REFERENCES groups(id), oferta_id INT, product_name TEXT,
  quantity INT NOT NULL DEFAULT 1, gross_amount NUMERIC(14,2) NOT NULL,
  commission NUMERIC(14,2) NOT NULL DEFAULT 0, commission_rate NUMERIC(7,4),
  status TEXT NOT NULL DEFAULT 'pending', buyer_hash TEXT, ordered_at TIMESTAMPTZ NOT NULL,
  confirmed_at TIMESTAMPTZ, source TEXT NOT NULL, raw JSONB,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_sales_platform_external UNIQUE (platform_id, external_id)
);
CREATE INDEX ix_sales_owner_ordered_at ON sales (owner_id, ordered_at DESC);
CREATE INDEX ix_sales_bot_ordered_at ON sales (bot_id, ordered_at DESC);
CREATE TABLE group_joins (
  id BIGSERIAL PRIMARY KEY, group_id UUID REFERENCES groups(id), bot_id UUID REFERENCES bots(id),
  campaign_id UUID REFERENCES campaigns(id), joined_at TIMESTAMPTZ NOT NULL,
  member_hash TEXT, source TEXT
);
CREATE TABLE automation_runs (
  id BIGSERIAL PRIMARY KEY, bot_id UUID REFERENCES bots(id), kind TEXT NOT NULL,
  status TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
  duration_ms INT, offers_found INT, offers_sent INT, error TEXT, detail JSONB
);
CREATE INDEX ix_automation_runs_bot_started_at ON automation_runs (bot_id, started_at DESC);
CREATE TABLE events (
  id BIGSERIAL PRIMARY KEY, bot_id UUID REFERENCES bots(id), entity_type TEXT, entity_id TEXT,
  level TEXT NOT NULL, type TEXT NOT NULL, message TEXT NOT NULL, detail JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_events_level_created_at ON events (level, created_at DESC);
CREATE TABLE alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_id UUID NOT NULL REFERENCES users(id),
  type TEXT NOT NULL, severity TEXT NOT NULL, entity_type TEXT, entity_id TEXT, title TEXT NOT NULL,
  detail TEXT, status TEXT NOT NULL DEFAULT 'open', first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), resolved_at TIMESTAMPTZ, dedup_key TEXT NOT NULL,
  CONSTRAINT uq_alerts_owner_dedup_status UNIQUE (owner_id, dedup_key, status) DEFERRABLE
);
CREATE TABLE commands (
  id BIGSERIAL PRIMARY KEY, bot_id UUID REFERENCES bots(id), type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb, status TEXT NOT NULL DEFAULT 'pending',
  requested_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  picked_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, result TEXT
);
CREATE INDEX ix_commands_pending ON commands (status, created_at) WHERE status = 'pending';
CREATE TABLE metric_snapshots (
  id BIGSERIAL PRIMARY KEY, owner_id UUID NOT NULL REFERENCES users(id), day DATE NOT NULL,
  bot_id UUID REFERENCES bots(id), group_id UUID REFERENCES groups(id),
  platform_id INT REFERENCES platforms(id), account_id UUID REFERENCES platform_accounts(id),
  campaign_id UUID REFERENCES campaigns(id), sends INT, clicks INT, orders INT, buyers INT, joins INT,
  revenue NUMERIC(14,2), commission NUMERIC(14,2), spend NUMERIC(14,2),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_metric_snapshots_dimensions UNIQUE
    (owner_id, day, bot_id, group_id, platform_id, account_id, campaign_id)
);
DO $$ BEGIN
  IF to_regclass('ofertas') IS NOT NULL THEN
    ALTER TABLE clicks ADD CONSTRAINT fk_clicks_oferta FOREIGN KEY (oferta_id) REFERENCES ofertas(id);
    ALTER TABLE sales ADD CONSTRAINT fk_sales_oferta FOREIGN KEY (oferta_id) REFERENCES ofertas(id);
  END IF;
END $$;
"""

TABLES = (
    "metric_snapshots",
    "commands",
    "alerts",
    "events",
    "automation_runs",
    "group_joins",
    "sales",
    "clicks",
    "expenses",
    "expense_categories",
    "campaigns",
    "bot_platform_accounts",
    "bot_groups",
    "groups",
    "bots",
    "niches",
    "phones",
    "platform_credentials",
    "platform_accounts",
    "platforms",
    "audit_logs",
    "users",
)


def upgrade() -> None:
    schema_ddl, legacy_fk_body = DDL.rsplit("DO $$ BEGIN", 1)
    for statement in schema_ddl.split(";\n"):
        if statement.strip():
            op.execute(statement)
    op.execute("DO $$ BEGIN" + legacy_fk_body)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}"')
