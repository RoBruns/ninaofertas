"""Schemas dos módulos operacionais Nina V3."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DecisionItem(BaseModel):
    id: str
    severity: str
    title: str
    detail: str
    href: str


class DecisionsStats(BaseModel):
    mirror_pending: int
    open_alerts: int
    cups_active: int
    vip_waiting: int
    monitors_hit: int


class DecisionsResponse(BaseModel):
    items: list[DecisionItem]
    stats: DecisionsStats


class MirrorInboxItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bot_id: UUID
    source_group_name: str | None
    body_text: str
    status: str
    skip_reason: str | None
    created_at: datetime
    processed_at: datetime | None


class MirrorInboxPatch(BaseModel):
    status: str = Field(pattern="^(skipped|pending)$")
    skip_reason: str | None = None


class OfferCard(BaseModel):
    id: int
    nome: str
    preco: Decimal | None
    preco_anterior: Decimal | None
    loja: str | None
    url: str | None
    imagem: str | None
    categoria: str | None
    criado_em: datetime | None = None


class CouponRadarCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    store: str | None = None
    title: str | None = None
    url: str | None = None
    status: str = "ativo"
    source_group_name: str | None = None
    notes: str | None = None
    min_value: Decimal = Field(default=Decimal("0"), ge=0)
    validity: str | None = "Até acabar a verba"

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CouponRadarUpdate(BaseModel):
    status: str | None = None
    title: str | None = None
    notes: str | None = None
    url: str | None = None
    store: str | None = None
    min_value: Decimal | None = None
    validity: str | None = None


class CouponRadarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    store: str | None
    title: str | None
    url: str | None
    status: str
    source_group_name: str | None
    notes: str | None
    min_value: Decimal = Decimal("0")
    validity: str | None = None
    report_count: int = 0
    created_at: datetime


class CouponDispatchRequest(BaseModel):
    group_ids: list[UUID] = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)
    image_base64: str | None = None
    link: str | None = None


class CouponDispatchResponse(BaseModel):
    ok: bool
    enviados: int
    total: int
    erro: str | None = None


class CouponDestination(BaseModel):
    id: UUID
    name: str
    phone_label: str | None = None
    bot_name: str | None = None
    whatsapp_id: str


class VipCreate(BaseModel):
    contact_name: str = Field(min_length=1, max_length=120)
    contact_phone: str | None = None
    wish_product: str = Field(min_length=2, max_length=200)
    max_price: Decimal = Field(gt=0)
    notes: str | None = None


class VipUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    max_price: Decimal | None = None


class VipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact_name: str
    contact_phone: str | None
    wish_product: str
    max_price: Decimal
    status: str
    matched_offer_id: int | None
    notes: str | None
    created_at: datetime


class MonitorCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    target_price: Decimal = Field(gt=0)
    title: str | None = None


class MonitorUpdate(BaseModel):
    target_price: Decimal | None = None
    status: str | None = None
    title: str | None = None


class MonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    title: str | None
    image_url: str | None
    target_price: Decimal
    last_price: Decimal | None
    status: str
    last_checked_at: datetime | None
    created_at: datetime


class FeedSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    kind: str
    url: str
    enabled: bool
    last_collected_at: datetime | None
    last_error: str | None
    total_collected: int


class FeedSourceUpdate(BaseModel):
    enabled: bool | None = None


class FeedSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    url: str = Field(min_length=8, max_length=2000)
    kind: str = Field(default="rss", pattern="^(rss)$")
    enabled: bool = True


class FeedSyncResponse(BaseModel):
    fontes: int
    lidas: int
    novas: int
    detalhes: list[dict]
