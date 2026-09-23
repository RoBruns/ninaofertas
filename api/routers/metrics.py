"""Rotas de leitura das metricas financeiras e operacionais."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.errors import APIError
from api.schemas.metrics import (
    CountKPI,
    FunnelResponse,
    MetricBreakdownItem,
    MetricBreakdownResponse,
    MetricPeriod,
    MoneyKPI,
    OverviewKPIs,
    OverviewResponse,
    RatioKPI,
    TimeseriesPoint,
    TimeseriesResponse,
    serialize_point_value,
)
from core.metrics import (
    MONEY_METRICS,
    RATIO_METRICS,
    Dimension,
    Granularity,
    MetricFilters,
    MetricName,
    MetricValues,
    calculate_metrics,
    change_percentage,
    grouped_metrics,
    rounded,
    timeseries,
)
from core.models import User

router = APIRouter(prefix="/metrics", tags=["metrics"])
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
METRIC_NAMES = set(MetricName.__args__)
GRANULARITIES = set(Granularity.__args__)
SORT_FIELDS = METRIC_NAMES | {"name"}


def _filters(
    from_date: date | None,
    to_date: date | None,
    bot_id: UUID | None,
    platform_id: int | None,
    account_id: UUID | None,
    group_id: UUID | None,
    campaign_id: UUID | None,
    niche_id: int | None,
    phone_id: UUID | None,
) -> MetricFilters:
    today = datetime.now(SAO_PAULO).date()
    end = to_date or today
    start = from_date or (end - timedelta(days=29))
    if start > end:
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "Parametros invalidos",
            {"from": "deve ser anterior ou igual a to"},
        )
    return MetricFilters(
        from_date=start,
        to_date=end,
        bot_id=bot_id,
        platform_id=platform_id,
        account_id=account_id,
        group_id=group_id,
        campaign_id=campaign_id,
        niche_id=niche_id,
        phone_id=phone_id,
    )


class FilterDependencies:
    def __init__(
        self,
        from_date: Annotated[date | None, Query(alias="from")] = None,
        to_date: Annotated[date | None, Query(alias="to")] = None,
        bot_id: UUID | None = None,
        platform_id: int | None = None,
        account_id: UUID | None = None,
        group_id: UUID | None = None,
        campaign_id: UUID | None = None,
        niche_id: int | None = None,
        phone_id: UUID | None = None,
    ) -> None:
        self.value = _filters(
            from_date,
            to_date,
            bot_id,
            platform_id,
            account_id,
            group_id,
            campaign_id,
            niche_id,
            phone_id,
        )


def _period(filters: MetricFilters) -> MetricPeriod:
    return MetricPeriod(from_date=filters.from_date, to_date=filters.to_date)


def _previous_value(value: Decimal | int | None) -> Decimal | int | None:
    if value is None or Decimal(value) == 0:
        return None
    return value


def _kpi(metric: str, current: MetricValues, previous: MetricValues) -> object:
    current_raw = getattr(current, metric)
    previous_raw = _previous_value(getattr(previous, metric))
    change = rounded(change_percentage(current_raw, previous_raw), "conversion")
    payload = {
        "value": rounded(current_raw, metric),
        "previous": rounded(previous_raw, metric),
        "change_pct": change,
    }
    if metric in MONEY_METRICS:
        return MoneyKPI(**payload)
    if metric in RATIO_METRICS:
        return RatioKPI(**payload)
    return CountKPI(**payload)


@router.get("/overview", response_model=OverviewResponse)
def overview(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    params: Annotated[FilterDependencies, Depends()],
) -> OverviewResponse:
    filters = params.value
    current = calculate_metrics(session, user.id, filters)
    previous = calculate_metrics(session, user.id, filters.previous, include_data_warnings=False)
    kpis = OverviewKPIs(
        **{metric: _kpi(metric, current.values, previous.values) for metric in METRIC_NAMES}
    )
    return OverviewResponse(period=_period(filters), kpis=kpis, warnings=current.warnings)


@router.get("/timeseries", response_model=TimeseriesResponse)
def metric_timeseries(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    params: Annotated[FilterDependencies, Depends()],
    metric: str,
    granularity: str = "day",
) -> TimeseriesResponse:
    if metric not in METRIC_NAMES:
        raise APIError(
            422, "VALIDATION_ERROR", "Parametros invalidos", {"metric": "metrica invalida"}
        )
    if granularity not in GRANULARITIES:
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "Parametros invalidos",
            {"granularity": "use day, week ou month"},
        )
    points, warnings = timeseries(
        session,
        user.id,
        params.value,
        metric,  # type: ignore[arg-type]
        granularity,  # type: ignore[arg-type]
    )
    return TimeseriesResponse(
        period=_period(params.value),
        metric=metric,
        granularity=granularity,  # type: ignore[arg-type]
        points=[
            TimeseriesPoint(date=day, value=serialize_point_value(metric, value))
            for day, value in points
        ],
        warnings=warnings,
    )


def _breakdown(
    user: User,
    session: Session,
    filters: MetricFilters,
    dimension: Dimension,
    sort: str,
) -> MetricBreakdownResponse:
    descending = sort.startswith("-")
    sort_field = sort.removeprefix("-")
    if sort_field not in SORT_FIELDS:
        raise APIError(422, "VALIDATION_ERROR", "Parametros invalidos", {"sort": "campo invalido"})
    rows, warnings = grouped_metrics(session, user.id, filters, dimension)
    items = [
        MetricBreakdownItem(id=entity_id, name=name, **values.public())
        for entity_id, name, values in rows
    ]

    def sort_value(item: MetricBreakdownItem) -> object:
        value = item.name.casefold() if sort_field == "name" else getattr(item, sort_field)
        return value if value is not None else Decimal("0")

    items.sort(key=sort_value, reverse=descending)
    if sort_field != "name":
        items.sort(key=lambda item: getattr(item, sort_field) is None)
    if items and all(item.buyers is None for item in items):
        warnings.append("Vendas sem buyer_hash no periodo; buyers e cost_per_buyer sem dados")
    if items and all(item.clicks is None for item in items):
        warnings.append("Sem dados de cliques no periodo; clicks e conversion sem dados")
    return MetricBreakdownResponse(
        period=_period(filters), items=items, warnings=list(dict.fromkeys(warnings))
    )


def _breakdown_route(dimension: Dimension):
    def route(
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_db)],
        params: Annotated[FilterDependencies, Depends()],
        sort: str = "profit",
    ) -> MetricBreakdownResponse:
        return _breakdown(user, session, params.value, dimension, sort)

    return route


for _dimension in ("platform", "account", "bot", "group", "campaign", "niche"):
    router.add_api_route(
        f"/by-{_dimension}",
        _breakdown_route(_dimension),  # type: ignore[arg-type]
        methods=["GET"],
        response_model=MetricBreakdownResponse,
        name=f"metrics_by_{_dimension}",
    )


@router.get("/funnel", response_model=FunnelResponse)
def funnel(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    params: Annotated[FilterDependencies, Depends()],
) -> FunnelResponse:
    result = calculate_metrics(session, user.id, params.value)
    values = result.values
    return FunnelResponse(
        period=_period(params.value),
        sends=values.sends,
        clicks=values.clicks,
        orders=values.orders,
        buyers=values.buyers,
        conversion=rounded(values.conversion, "conversion"),
        warnings=result.warnings,
    )
