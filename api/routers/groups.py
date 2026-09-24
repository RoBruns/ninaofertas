"""Cadastro e consulta de grupos de WhatsApp."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from api.schemas.group import GroupCreate, GroupResponse, GroupUpdate
from core.models import Bot, BotGroup, Group, Phone, User

router = APIRouter(prefix="/groups", tags=["groups"])
AdminUser = Annotated[User, Depends(require_role("admin"))]
WARNING = "Grupo somente-admins e o bot não é admin: mensagens não serão entregues"


def _owned(session: Session, group_id: UUID, owner_id: UUID) -> Group:
    group = session.scalar(select(Group).where(Group.id == group_id, Group.owner_id == owner_id))
    if group is None:
        raise APIError(404, "NOT_FOUND", "Grupo nao encontrado")
    return group


def _owned_phone(session: Session, phone_id: UUID, owner_id: UUID) -> Phone:
    phone = session.scalar(select(Phone).where(Phone.id == phone_id, Phone.owner_id == owner_id))
    if phone is None:
        raise APIError(404, "NOT_FOUND", "Telefone nao encontrado")
    return phone


def group_response(group: Group) -> GroupResponse:
    return GroupResponse(
        id=group.id, phone_id=group.phone_id, whatsapp_id=group.whatsapp_id,
        name=group.name, participants=group.participants, is_announce=group.is_announce,
        bot_is_admin=group.bot_is_admin, status=group.status,
        discovered_at=group.discovered_at, last_synced_at=group.last_synced_at,
        warning=WARNING if group.is_announce and not group.bot_is_admin else None,
    )


@router.get("", response_model=PaginatedResponse[GroupResponse])
def list_groups(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    phone_id: UUID | None = None,
    status: str | None = None,
    bot_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: str = "name",
) -> PaginatedResponse[GroupResponse]:
    statement = select(Group).where(Group.owner_id == user.id)
    if phone_id is not None:
        statement = statement.where(Group.phone_id == phone_id)
    if status is not None:
        statement = statement.where(Group.status == status)
    if bot_id is not None:
        statement = statement.join(BotGroup, BotGroup.group_id == Group.id).where(
            BotGroup.bot_id == bot_id, BotGroup.is_active.is_(True)
        )
    items, total = paginate(
        session, statement, PaginationParams(page=page, page_size=page_size, sort=sort),
        {"name": Group.name, "status": Group.status, "last_synced_at": Group.last_synced_at},
    )
    return PaginatedResponse(
        items=[group_response(group) for group in items], total=total, page=page, page_size=page_size
    )


@router.post("", response_model=GroupResponse, status_code=201, dependencies=[Depends(limit_authenticated_write)])
def create_group(
    payload: GroupCreate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> GroupResponse:
    _owned_phone(session, payload.phone_id, admin.id)
    if session.scalar(select(Group.id).where(Group.phone_id == payload.phone_id, Group.whatsapp_id == payload.whatsapp_id)):
        raise APIError(409, "CONFLICT", "Grupo ja cadastrado para este telefone")
    group = Group(id=uuid4(), owner_id=admin.id, **payload.model_dump())
    session.add(group)
    session.flush()
    response = group_response(group)
    record_audit(session, admin, "group", str(group.id), "create", None, response.model_dump(mode="json"), client_ip(request))
    session.commit()
    return response


@router.patch("/{group_id}", response_model=GroupResponse, dependencies=[Depends(limit_authenticated_write)])
def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> GroupResponse:
    group = _owned(session, group_id, admin.id)
    before = group_response(group).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("whatsapp_id", "ok") is None or changes.get("status", "ok") is None:
        raise APIError(422, "VALIDATION_ERROR", "whatsapp_id e status nao aceitam null")
    target_phone = changes.get("phone_id", group.phone_id)
    if target_phone is not None:
        _owned_phone(session, target_phone, admin.id)
    target_whatsapp = changes.get("whatsapp_id", group.whatsapp_id)
    if session.scalar(
        select(Group.id).where(Group.phone_id == target_phone, Group.whatsapp_id == target_whatsapp, Group.id != group.id)
    ):
        raise APIError(409, "CONFLICT", "Grupo ja cadastrado para este telefone")
    for field, value in changes.items():
        setattr(group, field, value)
    response = group_response(group)
    record_audit(session, admin, "group", str(group.id), "update", before, response.model_dump(mode="json"), client_ip(request))
    session.commit()
    return response


@router.delete("/{group_id}", status_code=204, dependencies=[Depends(limit_authenticated_write)])
def delete_group(
    group_id: UUID,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    group = _owned(session, group_id, admin.id)
    bots = list(
        session.scalars(
            select(Bot).join(BotGroup, BotGroup.bot_id == Bot.id)
            .where(BotGroup.group_id == group.id).order_by(Bot.name)
        )
    )
    if bots:
        names = ", ".join(bot.name for bot in bots)
        raise APIError(409, "CONFLICT", f"Grupo em uso pelos bots: {names}", {"bots": names})
    before = group_response(group).model_dump(mode="json")
    session.delete(group)
    record_audit(session, admin, "group", str(group.id), "delete", before, None, client_ip(request))
    session.commit()
