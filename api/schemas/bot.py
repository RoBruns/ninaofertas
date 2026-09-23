"""Schemas de bots, vinculacoes, execucoes e saude."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from core.bot_settings import BotSettings

BotState = Literal["active", "paused", "disabled"]


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=100)
    niche_id: int | None = None
    phone_id: UUID | None = None
    settings: BotSettings
    message_template: str | None = None
    group_ids: list[UUID] = Field(default_factory=list)
    account_ids: list[UUID] = Field(default_factory=list)


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(
        default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=100
    )
    niche_id: int | None = None
    phone_id: UUID | None = None
    settings: BotSettings | None = None
    message_template: str | None = None


class BotResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    niche_id: int | None
    phone_id: UUID | None
    status: BotState
    settings: BotSettings
    message_template: str | None
    group_ids: list[UUID]
    account_ids: list[UUID]
    last_run_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IdList(BaseModel):
    group_ids: list[UUID] | None = None
    account_ids: list[UUID] | None = None


class BotGroupsUpdate(BaseModel):
    group_ids: list[UUID]


class BotAccountsUpdate(BaseModel):
    account_ids: list[UUID]


class AutomationRunResponse(BaseModel):
    id: int
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    offers_found: int | None
    offers_sent: int | None
    error: str | None
    detail: dict[str, object] | None


class BotHealth(BaseModel):
    status: Literal["ok", "warning", "error", "unknown"]
    message: str
    last_run_status: str | None
    last_run_at: datetime | None
    credential_issues: list[str]
    group_issues: list[str]
