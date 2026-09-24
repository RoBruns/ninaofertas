"""Consulta paginada do log tecnico, sempre com segredos redigidos."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.audit import redact_sensitive
from api.deps import get_current_user, get_db
from api.schemas.common import PaginatedResponse
from api.schemas.event import EventLevel, EventResponse
from core.models import Event, User

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=PaginatedResponse[EventResponse])
def list_events(
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    level: EventLevel | None = None,
    bot_id: UUID | None = None,
    event_type: Annotated[str | None, Query(alias="type")] = None,
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PaginatedResponse[EventResponse]:
    statement = select(Event)
    # Cada condição só é montada quando o filtro foi informado: `coluna >= None`
    # levanta ArgumentError já na construção, então montar tudo antes e filtrar
    # depois derrubava a rota quando `from`/`to` não vinham — o caso comum.
    if level is not None:
        statement = statement.where(Event.level == level)
    if bot_id is not None:
        statement = statement.where(Event.bot_id == bot_id)
    if event_type is not None:
        statement = statement.where(Event.type == event_type)
    if from_at is not None:
        statement = statement.where(Event.created_at >= from_at)
    if to_at is not None:
        statement = statement.where(Event.created_at <= to_at)
    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    events = list(
        session.scalars(
            statement.order_by(Event.created_at.desc(), Event.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items = [
        EventResponse(
            id=event.id,
            bot_id=event.bot_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            level=event.level,
            type=event.type,
            message=event.message,
            detail=redact_sensitive(event.detail),
            created_at=event.created_at,
        )
        for event in events
    ]
    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)
