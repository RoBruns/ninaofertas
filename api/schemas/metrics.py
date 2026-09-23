"""Schemas publicos das metricas do dashboard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer


class MetricPeriod(BaseModel):
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")

    @field_serializer("from_date")
    def serialize_from(self, value: date) -> str:
        return value.isoformat()

    @field_serializer("to_date")
    def serialize_to(self, value: date) -> str:
        return value.isoformat()


class MoneyKPI(BaseModel):
    value: Decimal | None
    previous: Decimal | None
    change_pct: Decimal | None

    @field_serializer("value", "previous")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")

    @field_serializer("change_pct")
    def serialize_change(self, value: Decimal | None) -> float | None:
        return None if value is None else float(format(value, ".4f"))


class CountKPI(BaseModel):
    value: int | None
    previous: int | None
    change_pct: Decimal | None

    @field_serializer("change_pct")
    def serialize_change(self, value: Decimal | None) -> float | None:
        return None if value is None else float(format(value, ".4f"))


class RatioKPI(BaseModel):
    value: Decimal | None
    previous: Decimal | None
    change_pct: Decimal | None

    @field_serializer("value", "previous", "change_pct")
    def serialize_ratio(self, value: Decimal | None) -> float | None:
        return None if value is None else float(format(value, ".4f"))


class OverviewKPIs(BaseModel):
    revenue: MoneyKPI
    commission: MoneyKPI
    commission_pending: MoneyKPI
    orders: CountKPI
    buyers: CountKPI
    spend: MoneyKPI
    traffic_spend: MoneyKPI
    profit: MoneyKPI
    roi: RatioKPI
    roas: RatioKPI
    cost_per_sale: MoneyKPI
    cost_per_buyer: MoneyKPI
    cost_per_join: MoneyKPI
    group_joins: CountKPI
    sends: CountKPI
    clicks: CountKPI
    conversion: RatioKPI


class OverviewResponse(BaseModel):
    period: MetricPeriod
    kpis: OverviewKPIs
    warnings: list[str]


class TimeseriesPoint(BaseModel):
    date: date
    value: str | int | float | None


class TimeseriesResponse(BaseModel):
    period: MetricPeriod
    metric: str
    granularity: Literal["day", "week", "month"]
    points: list[TimeseriesPoint]
    warnings: list[str]


class MetricBreakdownItem(BaseModel):
    id: int | UUID
    name: str
    revenue: Decimal
    commission: Decimal
    commission_pending: Decimal
    orders: int
    buyers: int | None
    spend: Decimal
    traffic_spend: Decimal
    profit: Decimal
    roi: Decimal | None
    roas: Decimal | None
    cost_per_sale: Decimal | None
    cost_per_buyer: Decimal | None
    cost_per_join: Decimal | None
    group_joins: int
    sends: int | None
    clicks: int | None
    conversion: Decimal | None

    @field_serializer(
        "revenue",
        "commission",
        "commission_pending",
        "spend",
        "traffic_spend",
        "profit",
        "cost_per_sale",
        "cost_per_buyer",
        "cost_per_join",
    )
    def serialize_money(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")

    @field_serializer("roi", "roas", "conversion")
    def serialize_ratio(self, value: Decimal | None) -> float | None:
        return None if value is None else float(format(value, ".4f"))


class MetricBreakdownResponse(BaseModel):
    period: MetricPeriod
    items: list[MetricBreakdownItem]
    warnings: list[str]


class FunnelResponse(BaseModel):
    period: MetricPeriod
    sends: int | None
    clicks: int | None
    orders: int
    buyers: int | None
    conversion: Decimal | None
    warnings: list[str]

    @field_serializer("conversion")
    def serialize_conversion(self, value: Decimal | None) -> float | None:
        return None if value is None else float(format(value, ".4f"))


def serialize_point_value(metric: str, value: Any) -> str | int | float | None:
    if value is None or isinstance(value, int):
        return value
    if metric in {
        "revenue",
        "commission",
        "commission_pending",
        "spend",
        "traffic_spend",
        "profit",
        "cost_per_sale",
        "cost_per_buyer",
        "cost_per_join",
    }:
        return format(value, ".2f")
    return float(format(value, ".4f"))
