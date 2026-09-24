"""Schemas de alertas acionaveis."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

AlertStatus = Literal["open", "acknowledged", "resolved"]
AlertSeverity = Literal["warning", "critical"]


class AlertResponse(BaseModel):
    id: UUID
    owner_id: UUID
    type: str
    severity: AlertSeverity
    entity_type: str | None
    entity_id: str | None
    title: str
    detail: str | None
    status: AlertStatus
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    dedup_key: str
