"""Schemas de grupos de WhatsApp."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

GroupState = Literal["active", "inaccessible", "archived"]


class GroupCreate(BaseModel):
    phone_id: UUID
    whatsapp_id: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=300)
    participants: int | None = Field(default=None, ge=0)
    is_announce: bool | None = None
    bot_is_admin: bool | None = None
    status: GroupState = "active"


class GroupUpdate(BaseModel):
    phone_id: UUID | None = None
    whatsapp_id: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=300)
    participants: int | None = Field(default=None, ge=0)
    is_announce: bool | None = None
    bot_is_admin: bool | None = None
    status: GroupState | None = None


class GroupResponse(BaseModel):
    id: UUID
    phone_id: UUID | None
    whatsapp_id: str
    name: str | None
    participants: int | None
    is_announce: bool | None
    bot_is_admin: bool | None
    status: GroupState
    discovered_at: datetime | None
    last_synced_at: datetime | None
    warning: str | None = None
