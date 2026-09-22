from __future__ import annotations

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID

from core.models import Base, Expense, Platform, Sale, User


EXPECTED_TABLES = {
    "ofertas",
    "envios",
    "users",
    "audit_logs",
    "platforms",
    "platform_accounts",
    "platform_credentials",
    "phones",
    "niches",
    "bots",
    "groups",
    "bot_groups",
    "bot_platform_accounts",
    "campaigns",
    "expense_categories",
    "expenses",
    "clicks",
    "sales",
    "group_joins",
    "automation_runs",
    "events",
    "alerts",
    "commands",
    "metric_snapshots",
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
