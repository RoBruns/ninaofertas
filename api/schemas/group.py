"""Schemas de grupos de WhatsApp."""

from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from api.errors import APIError

GroupState = Literal["active", "inaccessible", "archived"]


class GroupFromInvite(BaseModel):
    phone_id: UUID
    invite_link: str = Field(min_length=1, max_length=500)

    @field_validator("invite_link")
    @classmethod
    def validate_invite(cls, value: str) -> str:
        match = re.fullmatch(r"(?:https?://chat\.whatsapp\.com/(?:invite/)?)?([A-Za-z0-9]{20,24})/?(?:\?\S*)?", value.strip())
        if not match:
            message = "Link de convite inválido; use https://chat.whatsapp.com/<código> ou o código"
            raise APIError(422, "VALIDATION_ERROR", message, {"invite_link": message})
        return match.group(1)


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
