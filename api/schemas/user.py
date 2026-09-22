"""Schemas de usuario sem campos de credencial na saida."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["admin", "operator", "viewer"]


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("email invalido")
    return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str | None
    role: Role
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=1024)
    name: str | None = Field(default=None, max_length=200)
    role: Role = "viewer"
    is_active: bool = True

    _email = field_validator("email")(_normalize_email)


class UserUpdate(BaseModel):
    email: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=1024)
    name: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    is_active: bool | None = None

    _email = field_validator("email")(_normalize_email)

    @model_validator(mode="after")
    def reject_null_for_required_columns(self) -> "UserUpdate":
        for field in ("email", "role", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} nao pode ser nulo")
        return self
