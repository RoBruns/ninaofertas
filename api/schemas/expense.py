"""Schemas de despesas e categorias."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field, field_serializer


def _decimal_input(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("use uma string decimal, nunca float")
    try:
        parsed = Decimal(value)  # type: ignore[arg-type]
    except (ArithmeticError, TypeError, ValueError):
        raise ValueError("amount deve ser uma string decimal valida") from None
    if parsed < 0:
        raise ValueError("amount deve ser >= 0")
    return parsed


Money = Annotated[
    Decimal,
    BeforeValidator(_decimal_input),
    Field(ge=Decimal("0"), max_digits=14, decimal_places=2),
]


class ExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    amount: Money
    incurred_on: date
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    category_id: int | None = None
    platform_id: int | None = None
    campaign_id: UUID | None = None
    bot_id: UUID | None = None
    niche_id: int | None = None
    notes: str | None = None


class ExpenseUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    amount: Money | None = None
    incurred_on: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category_id: int | None = None
    platform_id: int | None = None
    campaign_id: UUID | None = None
    bot_id: UUID | None = None
    niche_id: int | None = None
    notes: str | None = None


class ExpenseResponse(BaseModel):
    id: UUID
    description: str
    amount: Decimal
    currency: str
    incurred_on: date
    category_id: int | None
    platform_id: int | None
    campaign_id: UUID | None
    bot_id: UUID | None
    niche_id: int | None
    source: str
    external_id: str | None
    notes: str | None
    created_at: datetime

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, ".2f")


class ExpenseCategoryCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)


class ExpenseCategoryResponse(BaseModel):
    id: int
    slug: str
    name: str


class ImportErrorItem(BaseModel):
    line: int
    message: str


class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[ImportErrorItem]
