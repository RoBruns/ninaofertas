"""Contratos do painel da plataforma."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.schemas.user import _normalize_email
from api.schemas.billing import PlanResponse, SubscriptionResponse


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    status: Literal["active", "suspended"]
    is_internal: bool
    created_at: datetime
    users_count: int = 0
    active_bots_count: int = 0
    successful_sends_30d: int = 0
    plan: PlanResponse | None = None
    subscription: SubscriptionResponse | None = None
    mrr: Decimal = Decimal("0.00")
    usage: dict[str, int] = Field(default_factory=dict)


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    admin_email: str
    admin_name: str = Field(min_length=1, max_length=200)
    admin_password: str = Field(min_length=8, max_length=1024)
    plan_code: str = Field(default="beta", min_length=1, max_length=80)
    status: Literal["trialing", "active", "comp"] = "trialing"
    _email = field_validator("admin_email")(_normalize_email)


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "suspended"] = Field(default=None)

    @field_validator("name", "status")
    @classmethod
    def reject_null(cls, value: str) -> str:
        if value is None:
            raise ValueError("O campo não pode ser nulo")
        return value
