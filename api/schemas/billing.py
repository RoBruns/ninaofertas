"""Contratos da cobrança manual; dinheiro decimal em strings no JSON."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from api.schemas.expense import Money

Interval = Literal["month", "year"]
SubscriptionStatus = Literal["trialing", "active", "past_due", "canceled", "comp"]
Limit = Annotated[int, Field(strict=True, ge=0)]


class PlanLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_bots: Limit = Field(default=None)
    max_phones: Limit = Field(default=None)
    max_groups: Limit = Field(default=None)

    @field_validator("max_bots", "max_phones", "max_groups")
    @classmethod
    def non_null(cls, value: int) -> int:
        if value is None:
            raise ValueError("Omita o limite para deixá-lo ilimitado")
        return value


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    price: Decimal
    currency: str
    interval: Interval
    limits: dict[str, int]
    is_active: bool
    created_at: datetime


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=80)
    name: str = Field(min_length=1, max_length=200)
    price: Money = Decimal("0.00")
    currency: Literal["BRL"] = "BRL"
    interval: Interval = "month"
    limits: PlanLimits = Field(default_factory=PlanLimits)
    is_active: bool = True


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default=None, min_length=1, max_length=200)
    price: Money = Field(default=None)
    limits: PlanLimits = Field(default=None)
    is_active: bool = Field(default=None)

    @field_validator("name", "price", "limits", "is_active")
    @classmethod
    def non_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("O campo não pode ser nulo")
        return value


class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(default=None, min_length=1, max_length=80)
    status: SubscriptionStatus = Field(default=None)
    price: Money = Field(default=None)
    interval: Interval = Field(default=None)
    current_period_end: AwareDatetime | None = None
    cancel_reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("plan_code", "status", "price", "interval")
    @classmethod
    def non_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("O campo não pode ser nulo")
        return value


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    plan_id: UUID
    status: SubscriptionStatus
    price: Decimal
    interval: Interval
    started_at: datetime
    current_period_start: datetime
    current_period_end: datetime | None
    trial_ends_at: datetime | None
    canceled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime


class SubscriptionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: UUID
    subscription_id: UUID
    type: Literal[
        "created", "plan_changed", "price_changed", "status_changed", "canceled", "reactivated"
    ]
    status_before: SubscriptionStatus | None
    status_after: SubscriptionStatus
    mrr_before: Decimal
    mrr_after: Decimal
    occurred_at: datetime
    created_by: UUID | None
    note: str | None


class MonthlyBillingMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    mes: date
    mrr: Decimal
    paying_start: int
    paying_end: int
    new_tenants: int
    new_paying: int
    churned: int
    churn_rate: Decimal | None
    expansion_mrr: Decimal
    contraction_mrr: Decimal
    arpa: Decimal | None


class BillingSummary(BaseModel):
    mrr: Decimal
    paying: int
    new_tenants: int
    churned: int
    churn_rate: Decimal | None
    arpa: Decimal | None


class BillingMetricsResponse(BaseModel):
    months: list[MonthlyBillingMetrics]
    summary: BillingSummary
