"""Schemas de vendas, importacoes e sincronizacao."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_serializer

from api.schemas.expense import ImportResult

SaleStatus = Literal["pending", "confirmed", "cancelled", "paid"]


class SaleResponse(BaseModel):
    id: UUID
    account_id: UUID | None
    platform_id: int
    external_id: str
    sub_id: str | None
    bot_id: UUID | None
    group_id: UUID | None
    product_name: str | None
    quantity: int
    gross_amount: Decimal
    commission: Decimal
    commission_rate: Decimal | None
    status: SaleStatus
    buyer_hash: str | None
    ordered_at: datetime
    confirmed_at: datetime | None
    source: str
    imported_at: datetime

    @field_serializer("gross_amount", "commission")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")

    @field_serializer("commission_rate")
    def serialize_rate(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class SalesImportResult(ImportResult):
    pass


class SalesSyncRequest(BaseModel):
    account_id: UUID


class SalesSyncResponse(BaseModel):
    command_id: int


class SalesImportHistory(BaseModel):
    id: int
    platform_id: int
    file_name: str
    imported: int
    skipped: int
    created_at: datetime
