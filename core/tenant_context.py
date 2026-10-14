"""Resolve a conta de entidades conhecidas ao registrar eventos."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Bot, Group, Phone, PlatformAccount


def event_tenant_id(
    session: Session,
    bot_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> UUID | None:
    if bot_id is not None:
        return session.scalar(select(Bot.owner_id).where(Bot.id == bot_id))
    model = {"bot": Bot, "group": Group, "phone": Phone, "platform_account": PlatformAccount}.get(
        entity_type
    )
    if model is None or not entity_id:
        return None
    try:
        identity = UUID(entity_id)
    except ValueError:
        return None
    return session.scalar(select(model.owner_id).where(model.id == identity))
