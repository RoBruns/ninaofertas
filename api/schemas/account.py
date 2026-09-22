"""Schemas de contas de plataforma."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from api.schemas.credential import CredentialStatus
from api.schemas.platform import PlatformSummary

AccountState = Literal["active", "paused", "error", "disabled"]


class AccountCreate(BaseModel):
    platform_id: int
    label: str = Field(min_length=1, max_length=200)
    external_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class AccountUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    external_id: str | None = None
    config: dict[str, Any] | None = None
    notes: str | None = None


class AccountHealth(BaseModel):
    status: Literal["ok", "warning", "error", "unknown"]
    message: str | None


class AccountResponse(BaseModel):
    id: UUID
    platform: PlatformSummary
    label: str
    external_id: str | None
    status: AccountState
    config: dict[str, Any]
    notes: str | None
    credentials: list[CredentialStatus]
    health: AccountHealth
    created_at: datetime
    updated_at: datetime
