from __future__ import annotations

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID

from core.models import Base, Expense, Platform, Sale, User


EXPECTED_TABLES = {
    "alerts",
    "audit_logs",
    "automation_runs",
    "bot_config_backups",
    "bot_groups",
    "bot_platform_accounts",
    "bots",
    "campaigns",
    "clicks",
    "commands",
    "envios",
    "events",
    "expense_categories",
    "expenses",
    "group_joins",
    "groups",
    "metric_snapshots",
    "mirror_captures",
    "mirror_inbox",
    "niches",
    "ofertas",
    "phones",
    "plans",
    "platform_accounts",
    "platform_credentials",
    "platform_settings",
    "platforms",
    "sales",
    "subscription_events",
    "subscriptions",
    "task_boards",
    "task_card_labels",
    "task_cards",
    "task_checklist_items",
    "task_checklists",
    "task_comments",
    "task_labels",
    "task_lists",
    "tenants",
    "users",
}


def test_models_cobrem_todas_as_tabelas() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_tipos_normativos() -> None:
    assert isinstance(User.__table__.c.id.type, UUID)
    assert isinstance(User.__table__.c.email.type, CITEXT)
    assert isinstance(Platform.__table__.c.capabilities.type, JSONB)
    assert isinstance(Expense.__table__.c.amount.type, Numeric)
    assert (Expense.__table__.c.amount.type.precision, Expense.__table__.c.amount.type.scale) == (
        14,
        2,
    )
    assert (
        Sale.__table__.c.commission_rate.type.precision,
        Sale.__table__.c.commission_rate.type.scale,
    ) == (7, 4)
    assert Sale.__table__.c.ordered_at.type.timezone is True
