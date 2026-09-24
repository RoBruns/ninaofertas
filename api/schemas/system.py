"""Schemas da visao consolidada de saude do sistema."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BotSystemStatus(BaseModel):
    id: UUID
    name: str
    status: str
    last_run_at: datetime | None
    last_run_status: str | None
    last_failure_at: datetime | None


class AccountSystemStatus(BaseModel):
    id: UUID
    label: str
    status: str
    credential_health: str


class PhoneSystemStatus(BaseModel):
    id: UUID
    label: str
    status: str
    last_seen_at: datetime | None


class AlertTotals(BaseModel):
    critical: int
    warning: int


class SystemStatusResponse(BaseModel):
    bots: list[BotSystemStatus]
    accounts: list[AccountSystemStatus]
    phones: list[PhoneSystemStatus]
    open_alerts: AlertTotals
