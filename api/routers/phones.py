"""Telefones e comandos de descoberta de grupos."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from api.schemas.phone import CommandResponse, PhoneCreate, PhoneResponse, PhoneUpdate, QRCodeResponse
from core.evolution import EvolutionClient, EvolutionUnavailable
from core.models import Bot, BotGroup, Command, Group, Phone, User

router = APIRouter(prefix="/phones", tags=["phones"])
AdminUser = Annotated[User, Depends(require_role("admin"))]
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]


def _owned(session: Session, phone_id: UUID, owner_id: UUID) -> Phone:
    phone = session.scalar(select(Phone).where(Phone.id == phone_id, Phone.owner_id == owner_id))
    if phone is None:
        raise APIError(404, "NOT_FOUND", "Telefone não encontrado")
    return phone


def _response(phone: Phone, *, query_status: bool = True) -> PhoneResponse:
    status = EvolutionClient().connection_status(phone.evolution_instance) if query_status else phone.status
    if status not in {"connected", "disconnected", "banned", "unknown"}:
        status = "unknown"
    return PhoneResponse(
        id=phone.id,
        label=phone.label,
        number=phone.number,
        evolution_instance=phone.evolution_instance,
        status=status,
        last_seen_at=phone.last_seen_at,
        created_at=phone.created_at,
    )


def _check_instance(session: Session, admin: User, fields: set[str], instance: str | None,
                    phone_id: UUID | None = None) -> None:
    if "evolution_instance" not in fields:
        return
    if not admin.is_platform_admin:
        raise APIError(403, "FORBIDDEN", "A instância é controlada pela plataforma")
    if instance is not None:
        query = select(Phone.id).where(Phone.evolution_instance == instance)
        if phone_id is not None:
            query = query.where(Phone.id != phone_id)
        if session.scalar(query) is not None:
            raise APIError(409, "CONFLICT", "Instância já vinculada a outro telefone")


def _flush_phone(session: Session) -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise APIError(409, "CONFLICT", "Telefone ou instância já cadastrado") from exc


@router.get("", response_model=PaginatedResponse[PhoneResponse])
def list_phones(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: str = "-created_at",
) -> PaginatedResponse[PhoneResponse]:
    items, total = paginate(
        session,
        select(Phone).where(Phone.owner_id == user.tenant_id),
        PaginationParams(page=page, page_size=page_size, sort=sort),
        {"created_at": Phone.created_at, "label": Phone.label, "number": Phone.number},
    )
    return PaginatedResponse(
        items=[_response(phone) for phone in items], total=total, page=page, page_size=page_size
    )


@router.post("", response_model=PhoneResponse, status_code=201, dependencies=[Depends(limit_authenticated_write)])
def create_phone(
    payload: PhoneCreate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> PhoneResponse:
    _check_instance(session, admin, payload.model_fields_set, payload.evolution_instance)
    if session.scalar(select(Phone.id).where(Phone.owner_id == admin.tenant_id, Phone.number == payload.number)):
        raise APIError(409, "CONFLICT", "Telefone já cadastrado")
    phone = Phone(
        id=uuid4(), owner_id=admin.tenant_id, label=payload.label, number=payload.number,
        evolution_instance=payload.evolution_instance, status="unknown",
    )
    session.add(phone)
    _flush_phone(session)
    response = _response(phone)
    record_audit(session, admin, "phone", str(phone.id), "create", None, response.model_dump(mode="json"), client_ip(request))
    session.commit()
    return response


@router.patch("/{phone_id}", response_model=PhoneResponse, dependencies=[Depends(limit_authenticated_write)])
def update_phone(
    phone_id: UUID,
    payload: PhoneUpdate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> PhoneResponse:
    phone = _owned(session, phone_id, admin.tenant_id)
    _check_instance(session, admin, payload.model_fields_set, payload.evolution_instance, phone.id)
    before = _response(phone, query_status=False).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("label", "ok") is None or changes.get("number", "ok") is None:
        raise APIError(422, "VALIDATION_ERROR", "label e number não aceitam null")
    if "number" in changes and session.scalar(
        select(Phone.id).where(Phone.owner_id == admin.tenant_id, Phone.number == changes["number"], Phone.id != phone.id)
    ):
        raise APIError(409, "CONFLICT", "Telefone já cadastrado")
    for field, value in changes.items():
        setattr(phone, field, value)
    _flush_phone(session)
    response = _response(phone)
    record_audit(session, admin, "phone", str(phone.id), "update", before, response.model_dump(mode="json"), client_ip(request))
    session.commit()
    return response


@router.delete("/{phone_id}", status_code=204, dependencies=[Depends(limit_authenticated_write)])
def delete_phone(
    phone_id: UUID,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    phone = _owned(session, phone_id, admin.tenant_id)
    bots = list(
        session.scalars(
            select(Bot).where(Bot.owner_id == admin.tenant_id, Bot.phone_id == phone.id).order_by(Bot.name)
        )
    )
    linked_group_bots = list(
        session.scalars(
            select(Bot).join(BotGroup, BotGroup.bot_id == Bot.id).join(Group, Group.id == BotGroup.group_id)
            .where(Group.phone_id == phone.id).order_by(Bot.name)
        )
    )
    by_id = {bot.id: bot for bot in bots + linked_group_bots}
    if by_id:
        names = ", ".join(bot.name for bot in by_id.values())
        raise APIError(409, "CONFLICT", f"Telefone em uso pelos bots: {names}", {"bots": names})
    if session.scalar(select(Group.id).where(Group.phone_id == phone.id).limit(1)) is not None:
        raise APIError(409, "CONFLICT", "Telefone possui grupos cadastrados")
    before = _response(phone, query_status=False).model_dump(mode="json")
    session.delete(phone)
    record_audit(session, admin, "phone", str(phone.id), "delete", before, None, client_ip(request))
    session.commit()


@router.get("/{phone_id}/qrcode", response_model=QRCodeResponse)
def get_qrcode(
    phone_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> QRCodeResponse:
    phone = _owned(session, phone_id, user.tenant_id)
    try:
        code, expires_at = EvolutionClient().qrcode(phone.evolution_instance)
    except EvolutionUnavailable as exc:
        raise APIError(503, "SERVICE_UNAVAILABLE", str(exc)) from exc
    return QRCodeResponse(qrcode_base64=code, expires_at=expires_at)


@router.post(
    "/{phone_id}/sync-groups",
    response_model=CommandResponse,
    status_code=202,
    dependencies=[Depends(limit_authenticated_write)],
)
def sync_groups(
    phone_id: UUID,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> CommandResponse:
    phone = _owned(session, phone_id, user.tenant_id)
    command = Command(
        bot_id=None, type="sync_groups", payload={"phone_id": str(phone.id)},
        status="pending", requested_by=user.id,
    )
    session.add(command)
    session.flush()
    record_audit(session, user, "phone", str(phone.id), "sync_groups", None, {"command_id": command.id}, client_ip(request))
    session.commit()
    return CommandResponse(command_id=command.id)


@router.post("/{phone_id}/instance", response_model=QRCodeResponse,
             dependencies=[Depends(limit_authenticated_write)])
def connect_instance(phone_id: UUID, request: Request, admin: AdminUser,
                     session: Annotated[Session, Depends(get_db)]) -> QRCodeResponse:
    phone = session.scalar(select(Phone).where(Phone.id == phone_id, Phone.owner_id == admin.tenant_id).with_for_update())
    if phone is None:
        raise APIError(404, "NOT_FOUND", "Telefone não encontrado")
    evolution = EvolutionClient()
    try:
        if phone.evolution_instance:
            code, expires_at = evolution.qrcode(phone.evolution_instance)
        else:
            instance = f"nb-{str(admin.tenant_id)[:8]}-{str(phone.id)[:8]}"
            code, expires_at = evolution.create_instance(instance)
            phone.evolution_instance = instance
            _flush_phone(session)
            record_audit(session, admin, "phone", str(phone.id), "create_instance", None,
                         {"evolution_instance": instance}, client_ip(request))
            session.commit()
            # O provedor pode criar sem QR pronto. Preservar a instância permite
            # que a próxima tentativa consulte o QR, sem criar outra instância.
            if code is None:
                code, expires_at = evolution.qrcode(instance)
    except EvolutionUnavailable as exc:
        raise APIError(503, "SERVICE_UNAVAILABLE", str(exc)) from exc
    return QRCodeResponse(qrcode_base64=code, expires_at=expires_at)
