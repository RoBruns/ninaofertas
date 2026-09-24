"""Schemas do log tecnico estruturado."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

EventLevel = Literal["info", "warning", "error", "critical"]


class EventResponse(BaseModel):
    id: int
    bot_id: UUID | None
    entity_type: str | None
    entity_id: str | None
    level: EventLevel
    type: str
    message: str
    detail: dict[str, object] | None
    created_at: datetime
