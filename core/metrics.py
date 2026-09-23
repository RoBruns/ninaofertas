"""Agregacoes financeiras e operacionais do dashboard.

Este modulo e a fonte unica das formulas de metricas. As consultas retornam
apenas agregados do Postgres; linhas de eventos nunca sao materializadas em
Python.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, case, func, inspect, or_, select
from sqlalchemy.orm import Session

from core.models import (
    Bot,
    Campaign,
    Click,
    Envio,
    Expense,
    ExpenseCategory,
    Group,
    GroupJoin,
    Niche,
    Platform,
    PlatformAccount,
    Sale,
)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
CONFIRMED_STATUSES = ("confirmed", "paid")
MONEY = Decimal("0.01")
RATIO = Decimal("0.0001")

MetricName = Literal[
    "revenue",
    "commission",
    "commission_pending",
    "orders",
    "buyers",
    "spend",
    "traffic_spend",
    "profit",
    "roi",
    "roas",
    "cost_per_sale",
    "cost_per_buyer",
    "cost_per_join",
    "group_joins",
    "sends",
    "clicks",
    "conversion",
]
Granularity = Literal["day", "week", "month"]
Dimension = Literal["platform", "account", "bot", "group", "campaign", "niche"]

MONEY_METRICS = {
    "revenue",
    "commission",
    "commission_pending",
    "spend",
    "traffic_spend",
    "profit",
    "cost_per_sale",
    "cost_per_buyer",
    "cost_per_join",
}
RATIO_METRICS = {"roi", "roas", "conversion"}


@dataclass(frozen=True)
class MetricFilters:
    from_date: date
    to_date: date
    bot_id: UUID | None = None
    platform_id: int | None = None
    account_id: UUID | None = None
    group_id: UUID | None = None
    campaign_id: UUID | None = None
    niche_id: int | None = None
    phone_id: UUID | None = None

    @property
    def start_utc(self) -> datetime:
        local = datetime.combine(self.from_date, time.min, SAO_PAULO)
        return local.astimezone(timezone.utc)

    @property
    def end_utc(self) -> datetime:
        local = datetime.combine(self.to_date + timedelta(days=1), time.min, SAO_PAULO)
        return local.astimezone(timezone.utc)

    @property
    def previous(self) -> MetricFilters:
        days = (self.to_date - self.from_date).days + 1
        previous_to = self.from_date - timedelta(days=1)
        return MetricFilters(
            from_date=previous_to - timedelta(days=days - 1),
            to_date=previous_to,
            **{
                field.name: getattr(self, field.name)
                for field in fields(self)
                if field.name not in {"from_date", "to_date"}
            },
        )


@dataclass
class MetricValues:
    revenue: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    commission_pending: Decimal = Decimal("0")
    orders: int = 0
    buyers: int | None = None
    spend: Decimal = Decimal("0")
    traffic_spend: Decimal = Decimal("0")
    profit: Decimal = Decimal("0")
    roi: Decimal | None = None
    roas: Decimal | None = None
    cost_per_sale: Decimal | None = None
    cost_per_buyer: Decimal | None = None
    cost_per_join: Decimal | None = None
    group_joins: int = 0
    sends: int | None = 0
    clicks: int | None = None
    conversion: Decimal | None = None
    campaign_spend: Decimal = Decimal("0")

    def public(self) -> dict[str, Decimal | int | None]:
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != "campaign_spend"
        }


@dataclass
class MetricsResult:
    values: MetricValues
    warnings: list[str]


def safe_divide(numerator: Decimal | int, denominator: Decimal | int) -> Decimal | None:
    """Divide sem converter para float e sem fabricar zero para base ausente."""
    denominator_decimal = Decimal(denominator)
    if denominator_decimal == 0:
        return None
    return Decimal(numerator) / denominator_decimal


def change_percentage(
    current: Decimal | int | None, previous: Decimal | int | None
) -> Decimal | None:
    if current is None or previous is None or Decimal(previous) == 0:
        return None
    return ((Decimal(current) - Decimal(previous)) / abs(Decimal(previous))) * Decimal("100")


def rounded(value: Decimal | int | None, metric: str) -> Decimal | int | None:
    if value is None or isinstance(value, int):
        return value
    quantum = MONEY if metric in MONEY_METRICS else RATIO
    return value.quantize(quantum)


def _warning_ignored(filter_name: str, source: str) -> str:
    return f"Filtro {filter_name} nao se aplica a {source}; parcela calculada sem esse filtro"


def _append_ignored(
    filters: MetricFilters,
    source: str,
    supported: set[str],
    warnings: list[str],
) -> None:
    for name in (
        "bot_id",
        "platform_id",
        "account_id",
        "group_id",
        "campaign_id",
        "niche_id",
        "phone_id",
    ):
        if getattr(filters, name) is not None and name not in supported:
            warnings.append(_warning_ignored(name, source))


def _deduplicate(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _sales_conditions(owner_id: UUID, filters: MetricFilters) -> tuple[list[Any], list[str]]:
    conditions: list[Any] = [
        Sale.owner_id == owner_id,
        Sale.ordered_at >= filters.start_utc,
        Sale.ordered_at < filters.end_utc,
    ]
    warnings: list[str] = []
    supported = {"bot_id", "platform_id", "account_id", "group_id", "niche_id", "phone_id"}
    _append_ignored(filters, "vendas", supported, warnings)
    direct = {
        "bot_id": Sale.bot_id,
        "platform_id": Sale.platform_id,
        "account_id": Sale.account_id,
        "group_id": Sale.group_id,
    }
    for name, column in direct.items():
        value = getattr(filters, name)
        if value is not None:
            conditions.append(column == value)
    if filters.niche_id is not None:
        conditions.append(
            Sale.bot_id.in_(
                select(Bot.id).where(Bot.owner_id == owner_id, Bot.niche_id == filters.niche_id)
            )
        )
    if filters.phone_id is not None:
        conditions.append(
            Sale.bot_id.in_(
                select(Bot.id).where(Bot.owner_id == owner_id, Bot.phone_id == filters.phone_id)
            )
        )
    return conditions, warnings


def _expense_conditions(owner_id: UUID, filters: MetricFilters) -> tuple[list[Any], list[str]]:
    conditions: list[Any] = [
        Expense.owner_id == owner_id,
        Expense.incurred_on >= filters.from_date,
        Expense.incurred_on <= filters.to_date,
    ]
    warnings: list[str] = []
    supported = {"bot_id", "platform_id", "campaign_id", "niche_id", "phone_id"}
    _append_ignored(filters, "despesas", supported, warnings)
    for name, column in {
        "bot_id": Expense.bot_id,
        "platform_id": Expense.platform_id,
        "campaign_id": Expense.campaign_id,
        "niche_id": Expense.niche_id,
    }.items():
        value = getattr(filters, name)
        if value is not None:
            conditions.append(column == value)
    if filters.phone_id is not None:
        conditions.append(
            Expense.bot_id.in_(
                select(Bot.id).where(Bot.owner_id == owner_id, Bot.phone_id == filters.phone_id)
            )
        )
    return conditions, warnings


def _event_conditions(
    model: type[Click] | type[GroupJoin] | type[Envio],
    owner_id: UUID,
    filters: MetricFilters,
    source: str,
) -> tuple[list[Any], list[str]]:
    is_send = model is Envio
    timestamp = (
        Envio.enviado_em
        if is_send
        else (Click.clicked_at if model is Click else GroupJoin.joined_at)
    )
    if is_send:
        start = datetime.combine(filters.from_date, time.min)
        end = datetime.combine(filters.to_date + timedelta(days=1), time.min)
    else:
        start, end = filters.start_utc, filters.end_utc
    conditions: list[Any] = [timestamp >= start, timestamp < end]
    bot_column = model.bot_id
    group_column = model.group_id
    campaign_column = GroupJoin.campaign_id if model is GroupJoin else None
    ownership = [bot_column.in_(select(Bot.id).where(Bot.owner_id == owner_id))]
    ownership.append(group_column.in_(select(Group.id).where(Group.owner_id == owner_id)))
    if campaign_column is not None:
        ownership.append(
            campaign_column.in_(select(Campaign.id).where(Campaign.owner_id == owner_id))
        )
    conditions.append(or_(*ownership))
    supported = {"bot_id", "group_id", "niche_id", "phone_id"}
    if campaign_column is not None:
        supported.add("campaign_id")
    warnings: list[str] = []
    _append_ignored(filters, source, supported, warnings)
    if filters.bot_id is not None:
        conditions.append(bot_column == filters.bot_id)
    if filters.group_id is not None:
        conditions.append(group_column == filters.group_id)
    if filters.campaign_id is not None and campaign_column is not None:
        conditions.append(campaign_column == filters.campaign_id)
    if filters.niche_id is not None:
        conditions.append(
            bot_column.in_(
                select(Bot.id).where(Bot.owner_id == owner_id, Bot.niche_id == filters.niche_id)
            )
        )
    if filters.phone_id is not None:
        bot_match = bot_column.in_(
            select(Bot.id).where(Bot.owner_id == owner_id, Bot.phone_id == filters.phone_id)
        )
        group_match = group_column.in_(
            select(Group.id).where(Group.owner_id == owner_id, Group.phone_id == filters.phone_id)
        )
        conditions.append(or_(bot_match, group_match))
    return conditions, warnings


def _has_legacy_sends(session: Session) -> bool:
    bind = session.get_bind()
    return inspect(bind).has_table("envios")


def _finish(values: MetricValues) -> MetricValues:
    values.profit = values.commission - values.spend
    values.roi = safe_divide(values.profit, values.spend)
    values.roas = safe_divide(values.revenue, values.traffic_spend)
    values.cost_per_sale = safe_divide(values.spend, values.orders)
    values.cost_per_buyer = (
        None if values.buyers is None else safe_divide(values.spend, values.buyers)
    )
    values.cost_per_join = safe_divide(values.campaign_spend, values.group_joins)
    values.conversion = None if values.clicks is None else safe_divide(values.orders, values.clicks)
    return values


def calculate_metrics(
    session: Session,
    owner_id: UUID,
    filters: MetricFilters,
    *,
    include_data_warnings: bool = True,
) -> MetricsResult:
    """Calcula todas as formulas com uma consulta agregada por fonte."""
    if filters.from_date > filters.to_date:
        raise ValueError("from_date deve ser anterior ou igual a to_date")
    warnings: list[str] = []

    sale_conditions, source_warnings = _sales_conditions(owner_id, filters)
    warnings.extend(source_warnings)
    sale_row = session.execute(
        select(
            func.coalesce(
                func.sum(case((Sale.status.in_(CONFIRMED_STATUSES), Sale.gross_amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((Sale.status.in_(CONFIRMED_STATUSES), Sale.commission), else_=0)),
                0,
            ),
            func.coalesce(func.sum(case((Sale.status == "pending", Sale.commission), else_=0)), 0),
            func.count(case((Sale.status.in_(CONFIRMED_STATUSES), 1))),
            func.count(
                func.distinct(
                    case(
                        (
                            and_(Sale.status.in_(CONFIRMED_STATUSES), Sale.buyer_hash.is_not(None)),
                            Sale.buyer_hash,
                        )
                    )
                )
            ),
            func.count(
                case(
                    (
                        and_(
                            Sale.status.in_(CONFIRMED_STATUSES),
                            Sale.buyer_hash.is_(None),
                        ),
                        1,
                    )
                )
            ),
        ).where(*sale_conditions)
    ).one()

    expense_conditions, source_warnings = _expense_conditions(owner_id, filters)
    warnings.extend(source_warnings)
    expense_row = session.execute(
        select(
            func.coalesce(func.sum(Expense.amount), 0),
            func.coalesce(
                func.sum(case((ExpenseCategory.slug == "trafego", Expense.amount), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Expense.campaign_id.is_not(None), Expense.amount), else_=0)), 0
            ),
        )
        .select_from(Expense)
        .outerjoin(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(*expense_conditions)
    ).one()

    join_conditions, source_warnings = _event_conditions(
        GroupJoin, owner_id, filters, "entradas em grupos"
    )
    warnings.extend(source_warnings)
    group_joins = int(
        session.scalar(select(func.count()).select_from(GroupJoin).where(*join_conditions)) or 0
    )

    click_conditions, source_warnings = _event_conditions(Click, owner_id, filters, "cliques")
    warnings.extend(source_warnings)
    click_count = int(
        session.scalar(select(func.count()).select_from(Click).where(*click_conditions)) or 0
    )

    sends: int | None
    if _has_legacy_sends(session):
        send_conditions, source_warnings = _event_conditions(Envio, owner_id, filters, "envios")
        warnings.extend(source_warnings)
        send_conditions.append(Envio.status == "sucesso")
        sends = int(
            session.scalar(select(func.count()).select_from(Envio).where(*send_conditions)) or 0
        )
    else:
        sends = None
        if include_data_warnings:
            warnings.append("Tabela legada de envios indisponivel; sends sem dados")

    buyers_count = int(sale_row[4] or 0)
    values = _finish(
        MetricValues(
            revenue=Decimal(sale_row[0]),
            commission=Decimal(sale_row[1]),
            commission_pending=Decimal(sale_row[2]),
            orders=int(sale_row[3] or 0),
            buyers=buyers_count or None,
            spend=Decimal(expense_row[0]),
            traffic_spend=Decimal(expense_row[1]),
            campaign_spend=Decimal(expense_row[2]),
            group_joins=group_joins,
            sends=sends,
            clicks=click_count or None,
        )
    )
    if include_data_warnings and values.buyers is None:
        warnings.append("Vendas sem buyer_hash no periodo; buyers e cost_per_buyer sem dados")
    elif include_data_warnings and int(sale_row[5] or 0) > 0:
        warnings.append("Algumas vendas nao possuem buyer_hash; buyers pode estar incompleto")
    if include_data_warnings and values.clicks is None:
        warnings.append("Sem dados de cliques no periodo; clicks e conversion sem dados")
    return MetricsResult(values=values, warnings=_deduplicate(warnings))


def calculate_spend_by_category(
    session: Session, owner_id: UUID, filters: MetricFilters
) -> tuple[dict[str, Decimal], list[str]]:
    conditions, warnings = _expense_conditions(owner_id, filters)
    rows = session.execute(
        select(
            func.coalesce(ExpenseCategory.slug, "sem_categoria"),
            func.coalesce(func.sum(Expense.amount), 0),
        )
        .select_from(Expense)
        .outerjoin(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(*conditions)
        .group_by(ExpenseCategory.slug)
    )
    return {str(slug): Decimal(amount) for slug, amount in rows}, _deduplicate(warnings)


def metric_value(values: MetricValues, metric: MetricName) -> Decimal | int | None:
    return rounded(getattr(values, metric), metric)


def _bucket(column: Any, granularity: Granularity, *, utc: bool = True) -> Any:
    local_column = func.timezone("America/Sao_Paulo", column) if utc else column
    return func.date_trunc(granularity, local_column).cast(Date)


def timeseries(
    session: Session,
    owner_id: UUID,
    filters: MetricFilters,
    metric: MetricName,
    granularity: Granularity,
) -> tuple[list[tuple[date, Decimal | int | None]], list[str]]:
    """Agrupa a metrica solicitada no Postgres e aplica a formula por bucket."""
    required: dict[str, set[str]] = {
        "revenue": {"sales"},
        "commission": {"sales"},
        "commission_pending": {"sales"},
        "orders": {"sales"},
        "buyers": {"sales"},
        "spend": {"expenses"},
        "traffic_spend": {"expenses"},
        "profit": {"sales", "expenses"},
        "roi": {"sales", "expenses"},
        "roas": {"sales", "expenses"},
        "cost_per_sale": {"sales", "expenses"},
        "cost_per_buyer": {"sales", "expenses"},
        "cost_per_join": {"expenses", "joins"},
        "group_joins": {"joins"},
        "sends": {"sends"},
        "clicks": {"clicks"},
        "conversion": {"sales", "clicks"},
    }
    buckets: dict[date, MetricValues] = {}
    warnings: list[str] = []

    def target(day: date) -> MetricValues:
        return buckets.setdefault(day, MetricValues())

    if "sales" in required[metric]:
        conditions, current_warnings = _sales_conditions(owner_id, filters)
        warnings.extend(current_warnings)
        day = _bucket(Sale.ordered_at, granularity)
        for row in session.execute(
            select(
                day,
                func.coalesce(
                    func.sum(
                        case((Sale.status.in_(CONFIRMED_STATUSES), Sale.gross_amount), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Sale.status.in_(CONFIRMED_STATUSES), Sale.commission), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Sale.status == "pending", Sale.commission), else_=0)), 0
                ),
                func.count(case((Sale.status.in_(CONFIRMED_STATUSES), 1))),
                func.count(
                    func.distinct(
                        case(
                            (
                                and_(
                                    Sale.status.in_(CONFIRMED_STATUSES),
                                    Sale.buyer_hash.is_not(None),
                                ),
                                Sale.buyer_hash,
                            )
                        )
                    )
                ),
            )
            .where(*conditions)
            .group_by(day)
        ):
            item = target(row[0])
            item.revenue = Decimal(row[1])
            item.commission = Decimal(row[2])
            item.commission_pending = Decimal(row[3])
            item.orders = int(row[4])
            item.buyers = int(row[5]) or None

    if "expenses" in required[metric]:
        conditions, current_warnings = _expense_conditions(owner_id, filters)
        warnings.extend(current_warnings)
        day = _bucket(Expense.incurred_on, granularity, utc=False)
        for row in session.execute(
            select(
                day,
                func.coalesce(func.sum(Expense.amount), 0),
                func.coalesce(
                    func.sum(case((ExpenseCategory.slug == "trafego", Expense.amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Expense.campaign_id.is_not(None), Expense.amount), else_=0)), 0
                ),
            )
            .select_from(Expense)
            .outerjoin(ExpenseCategory)
            .where(*conditions)
            .group_by(day)
        ):
            item = target(row[0])
            item.spend = Decimal(row[1])
            item.traffic_spend = Decimal(row[2])
            item.campaign_spend = Decimal(row[3])

    event_specs = (("joins", GroupJoin, "entradas em grupos"), ("clicks", Click, "cliques"))
    for key, model, label in event_specs:
        if key not in required[metric]:
            continue
        conditions, current_warnings = _event_conditions(model, owner_id, filters, label)
        warnings.extend(current_warnings)
        timestamp = GroupJoin.joined_at if model is GroupJoin else Click.clicked_at
        day = _bucket(timestamp, granularity)
        for bucket_day, count in session.execute(
            select(day, func.count()).select_from(model).where(*conditions).group_by(day)
        ):
            item = target(bucket_day)
            if model is GroupJoin:
                item.group_joins = int(count)
            else:
                item.clicks = int(count)

    if "sends" in required[metric]:
        if _has_legacy_sends(session):
            conditions, current_warnings = _event_conditions(Envio, owner_id, filters, "envios")
            warnings.extend(current_warnings)
            conditions.append(Envio.status == "sucesso")
            day = _bucket(Envio.enviado_em, granularity, utc=False)
            for bucket_day, count in session.execute(
                select(day, func.count()).select_from(Envio).where(*conditions).group_by(day)
            ):
                target(bucket_day).sends = int(count)
        else:
            warnings.append("Tabela legada de envios indisponivel; sends sem dados")

    points: list[tuple[date, Decimal | int | None]] = []
    for day, values in sorted(buckets.items()):
        _finish(values)
        points.append((day, metric_value(values, metric)))
    if metric in {"buyers", "cost_per_buyer"} and not any(value is not None for _, value in points):
        warnings.append("Vendas sem buyer_hash no periodo; buyers e cost_per_buyer sem dados")
    if metric in {"clicks", "conversion"} and not any(value is not None for _, value in points):
        warnings.append("Sem dados de cliques no periodo; clicks e conversion sem dados")
    return points, _deduplicate(warnings)


def dimension_entities(
    session: Session,
    owner_id: UUID,
    dimension: Dimension,
    filters: MetricFilters,
) -> list[tuple[int | UUID, str]]:
    if dimension == "platform":
        owned_platforms = (
            select(PlatformAccount.platform_id.label("id"))
            .where(PlatformAccount.owner_id == owner_id)
            .union(
                select(Sale.platform_id.label("id")).where(Sale.owner_id == owner_id),
                select(Expense.platform_id.label("id")).where(
                    Expense.owner_id == owner_id, Expense.platform_id.is_not(None)
                ),
            )
            .subquery()
        )
        statement = select(Platform.id, Platform.name).join(
            owned_platforms, owned_platforms.c.id == Platform.id
        )
        if filters.platform_id is not None:
            statement = statement.where(Platform.id == filters.platform_id)
        return list(session.execute(statement))
    model_and_name: dict[str, tuple[Any, Any]] = {
        "account": (PlatformAccount, PlatformAccount.label),
        "bot": (Bot, Bot.name),
        "group": (Group, func.coalesce(Group.name, Group.whatsapp_id)),
        "campaign": (Campaign, Campaign.name),
        "niche": (Niche, Niche.name),
    }
    model, name = model_and_name[dimension]
    statement = select(model.id, name).where(model.owner_id == owner_id)
    selected_id = getattr(filters, f"{dimension}_id")
    if selected_id is not None:
        statement = statement.where(model.id == selected_id)
    return list(session.execute(statement))


def grouped_metrics(
    session: Session,
    owner_id: UUID,
    filters: MetricFilters,
    dimension: Dimension,
) -> tuple[list[tuple[int | UUID, str, MetricValues]], list[str]]:
    """Calcula breakdown com uma consulta ``GROUP BY`` por fonte de eventos."""
    entities = dimension_entities(session, owner_id, dimension, filters)
    values_by_id = {entity_id: MetricValues() for entity_id, _name in entities}
    warnings: list[str] = []

    sale_group = {
        "platform": Sale.platform_id,
        "account": Sale.account_id,
        "bot": Sale.bot_id,
        "group": Sale.group_id,
    }.get(dimension)
    sale_conditions, current_warnings = _sales_conditions(owner_id, filters)
    warnings.extend(current_warnings)
    sale_statement = None
    if dimension == "niche":
        sale_group = Bot.niche_id
        sale_statement = select_from_sales = (
            select(
                sale_group,
                func.coalesce(
                    func.sum(
                        case((Sale.status.in_(CONFIRMED_STATUSES), Sale.gross_amount), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Sale.status.in_(CONFIRMED_STATUSES), Sale.commission), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Sale.status == "pending", Sale.commission), else_=0)), 0
                ),
                func.count(case((Sale.status.in_(CONFIRMED_STATUSES), 1))),
                func.count(
                    func.distinct(
                        case(
                            (
                                and_(
                                    Sale.status.in_(CONFIRMED_STATUSES),
                                    Sale.buyer_hash.is_not(None),
                                ),
                                Sale.buyer_hash,
                            )
                        )
                    )
                ),
            )
            .select_from(Sale)
            .outerjoin(Bot, Bot.id == Sale.bot_id)
        )
    elif sale_group is not None:
        sale_statement = select_from_sales = select(
            sale_group,
            func.coalesce(
                func.sum(case((Sale.status.in_(CONFIRMED_STATUSES), Sale.gross_amount), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Sale.status.in_(CONFIRMED_STATUSES), Sale.commission), else_=0)), 0
            ),
            func.coalesce(func.sum(case((Sale.status == "pending", Sale.commission), else_=0)), 0),
            func.count(case((Sale.status.in_(CONFIRMED_STATUSES), 1))),
            func.count(
                func.distinct(
                    case(
                        (
                            and_(Sale.status.in_(CONFIRMED_STATUSES), Sale.buyer_hash.is_not(None)),
                            Sale.buyer_hash,
                        )
                    )
                )
            ),
        ).select_from(Sale)
    else:
        warnings.append(_warning_ignored(f"{dimension}_id", "vendas"))
        row = session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case((Sale.status.in_(CONFIRMED_STATUSES), Sale.gross_amount), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Sale.status.in_(CONFIRMED_STATUSES), Sale.commission), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Sale.status == "pending", Sale.commission), else_=0)), 0
                ),
                func.count(case((Sale.status.in_(CONFIRMED_STATUSES), 1))),
                func.count(
                    func.distinct(
                        case(
                            (
                                and_(
                                    Sale.status.in_(CONFIRMED_STATUSES),
                                    Sale.buyer_hash.is_not(None),
                                ),
                                Sale.buyer_hash,
                            )
                        )
                    )
                ),
            ).where(*sale_conditions)
        ).one()
        for item in values_by_id.values():
            item.revenue = Decimal(row[0])
            item.commission = Decimal(row[1])
            item.commission_pending = Decimal(row[2])
            item.orders = int(row[3])
            item.buyers = int(row[4]) or None
    if sale_statement is not None and sale_group is not None:
        for row in session.execute(select_from_sales.where(*sale_conditions).group_by(sale_group)):
            if row[0] not in values_by_id:
                continue
            item = values_by_id[row[0]]
            item.revenue = Decimal(row[1])
            item.commission = Decimal(row[2])
            item.commission_pending = Decimal(row[3])
            item.orders = int(row[4])
            item.buyers = int(row[5]) or None

    expense_group = {
        "platform": Expense.platform_id,
        "bot": Expense.bot_id,
        "campaign": Expense.campaign_id,
        "niche": Expense.niche_id,
    }.get(dimension)
    expense_conditions, current_warnings = _expense_conditions(owner_id, filters)
    warnings.extend(current_warnings)
    if expense_group is None:
        warnings.append(_warning_ignored(f"{dimension}_id", "despesas"))
        spend, traffic, campaign_spend = session.execute(
            select(
                func.coalesce(func.sum(Expense.amount), 0),
                func.coalesce(
                    func.sum(case((ExpenseCategory.slug == "trafego", Expense.amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Expense.campaign_id.is_not(None), Expense.amount), else_=0)), 0
                ),
            )
            .select_from(Expense)
            .outerjoin(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(*expense_conditions)
        ).one()
        for item in values_by_id.values():
            item.spend = Decimal(spend)
            item.traffic_spend = Decimal(traffic)
            item.campaign_spend = Decimal(campaign_spend)
    else:
        statement = (
            select(
                expense_group,
                func.coalesce(func.sum(Expense.amount), 0),
                func.coalesce(
                    func.sum(case((ExpenseCategory.slug == "trafego", Expense.amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Expense.campaign_id.is_not(None), Expense.amount), else_=0)), 0
                ),
            )
            .select_from(Expense)
            .outerjoin(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(*expense_conditions)
            .group_by(expense_group)
        )
        for entity_id, spend, traffic, campaign_spend in session.execute(statement):
            if entity_id not in values_by_id:
                continue
            item = values_by_id[entity_id]
            item.spend = Decimal(spend)
            item.traffic_spend = Decimal(traffic)
            item.campaign_spend = Decimal(campaign_spend)

    event_groups: tuple[tuple[Any, str, dict[str, Any]], ...] = (
        (
            GroupJoin,
            "entradas em grupos",
            {
                "bot": GroupJoin.bot_id,
                "group": GroupJoin.group_id,
                "campaign": GroupJoin.campaign_id,
            },
        ),
        (Click, "cliques", {"bot": Click.bot_id, "group": Click.group_id}),
    )
    for model, label, group_map in event_groups:
        group_column = group_map.get(dimension)
        conditions, current_warnings = _event_conditions(model, owner_id, filters, label)
        warnings.extend(current_warnings)
        statement = None
        if dimension == "niche":
            group_column = Bot.niche_id
            statement = (
                select(group_column, func.count())
                .select_from(model)
                .outerjoin(Bot, Bot.id == model.bot_id)
            )
        elif group_column is not None:
            statement = select(group_column, func.count()).select_from(model)
        else:
            warnings.append(_warning_ignored(f"{dimension}_id", label))
            count = int(
                session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
            )
            for item in values_by_id.values():
                if model is GroupJoin:
                    item.group_joins = count
                else:
                    item.clicks = count or None
        if statement is None or group_column is None:
            continue
        for entity_id, count in session.execute(
            statement.where(*conditions).group_by(group_column)
        ):
            if entity_id not in values_by_id:
                continue
            if model is GroupJoin:
                values_by_id[entity_id].group_joins = int(count)
            else:
                values_by_id[entity_id].clicks = int(count)

    if _has_legacy_sends(session):
        send_group = {"bot": Envio.bot_id, "group": Envio.group_id}.get(dimension)
        send_conditions, current_warnings = _event_conditions(Envio, owner_id, filters, "envios")
        warnings.extend(current_warnings)
        send_conditions.append(Envio.status == "sucesso")
        statement = None
        if dimension == "niche":
            send_group = Bot.niche_id
            statement = (
                select(send_group, func.count())
                .select_from(Envio)
                .outerjoin(Bot, Bot.id == Envio.bot_id)
            )
        elif send_group is not None:
            statement = select(send_group, func.count()).select_from(Envio)
        else:
            warnings.append(_warning_ignored(f"{dimension}_id", "envios"))
            count = int(
                session.scalar(select(func.count()).select_from(Envio).where(*send_conditions)) or 0
            )
            for item in values_by_id.values():
                item.sends = count
        if statement is not None and send_group is not None:
            for entity_id, count in session.execute(
                statement.where(*send_conditions).group_by(send_group)
            ):
                if entity_id in values_by_id:
                    values_by_id[entity_id].sends = int(count)
    else:
        for item in values_by_id.values():
            item.sends = None
        warnings.append("Tabela legada de envios indisponivel; sends sem dados")

    rows = [(entity_id, name, _finish(values_by_id[entity_id])) for entity_id, name in entities]
    return rows, _deduplicate(warnings)
