"""Schemas de auditoria."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID | None
    user_email: str | None
    user_name: str | None
    entity_type: str
    entity_id: str
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    created_at: datetime

    @field_validator("ip", mode="before")
    @classmethod
    def _ip_como_texto(cls, value: Any) -> Any:
        # A coluna é INET: o psycopg devolve IPv4Address/IPv6Address, não str.
        return None if value is None else str(value)
