"""Schemas de campanhas e metricas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, model_validator


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    channel: str | None = None
    external_id: str | None = None
    bot_id: UUID | None = None
    niche_id: int | None = None
    objective: str | None = None
    status: Literal["active", "paused", "completed"] = "active"
    started_at: date | None = None
    ended_at: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> CampaignCreate:
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at nao pode ser anterior a started_at")
        return self


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    channel: str | None = None
    external_id: str | None = None
    bot_id: UUID | None = None
    niche_id: int | None = None
    objective: str | None = None
    status: Literal["active", "paused", "completed"] | None = None
    started_at: date | None = None
    ended_at: date | None = None


class CampaignResponse(BaseModel):
    id: UUID
    name: str
    channel: str | None
    external_id: str | None
    bot_id: UUID | None
    niche_id: int | None
    objective: str | None
    status: str
    started_at: date | None
    ended_at: date | None


class CampaignMetrics(BaseModel):
    campaign_id: UUID
    spend: Decimal
    group_joins: int
    cost_per_join: Decimal | None

    @field_serializer("spend", "cost_per_join")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")
