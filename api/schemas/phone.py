"""Schemas de telefones conectados a evolution-api."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PhoneState = Literal["connected", "disconnected", "banned", "unknown"]


def normalize_e164(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if not 8 <= len(digits) <= 15:
        raise ValueError("number deve conter DDI e entre 8 e 15 digitos")
    return digits


class PhoneCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    number: str
    evolution_instance: str | None = Field(default=None, max_length=200)

    _normalize_number = field_validator("number")(normalize_e164)


class PhoneUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    number: str | None = None
    evolution_instance: str | None = Field(default=None, max_length=200)

    _normalize_number = field_validator("number")(lambda value: normalize_e164(value) if value else value)


class PhoneResponse(BaseModel):
    id: UUID
    label: str
    number: str
    evolution_instance: str | None
    status: PhoneState
    last_seen_at: datetime | None
    created_at: datetime


class QRCodeResponse(BaseModel):
    qrcode_base64: str
    expires_at: datetime


class CommandResponse(BaseModel):
    command_id: int
