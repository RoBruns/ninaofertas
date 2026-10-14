"""Administração de contas, restrita ao administrador da plataforma."""

from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_db, limit_authenticated_write, require_platform_admin
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.tenant import TenantCreate, TenantResponse, TenantUpdate
from api.security import hash_password
from core import relogio
from core.models import Bot, Envio, Group, Tenant, User

router = APIRouter(prefix="/platform", tags=["platform"])
PlatformAdmin = Annotated[User, Depends(require_platform_admin)]


def _response(session: Session, tenant: Tenant) -> TenantResponse:
    users = session.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id))
    bots = session.scalar(
        select(func.count(Bot.id)).where(Bot.owner_id == tenant.id, Bot.status == "active")
    )
    sends = session.scalar(
        select(func.count(Envio.id)).where(
            Envio.status == "sucesso",
            Envio.enviado_em >= relogio.agora_banco() - timedelta(days=30),
            (Envio.bot_id.in_(select(Bot.id).where(Bot.owner_id == tenant.id)))
            | (
                Envio.bot_id.is_(None)
                & Envio.grupo.in_(select(Group.whatsapp_id).where(Group.owner_id == tenant.id))
            ),
        )
    )
    return TenantResponse.model_validate(tenant).model_copy(
        update={
            "users_count": int(users or 0),
            "active_bots_count": int(bots or 0),
            "successful_sends_30d": int(sends or 0),
        }
    )


@router.get("/tenants", response_model=list[TenantResponse])
def list_tenants(
    admin: PlatformAdmin, session: Annotated[Session, Depends(get_db)]
) -> list[TenantResponse]:
    return [
        _response(session, tenant)
        for tenant in session.scalars(select(Tenant).order_by(Tenant.created_at))
    ]


@router.post(
    "/tenants",
    status_code=201,
    response_model=TenantResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_tenant(
    payload: TenantCreate,
    request: Request,
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
) -> TenantResponse:
    if session.scalar(select(User.id).where(User.email == payload.admin_email)):
        raise APIError(409, "CONFLICT", "Email já cadastrado")
    tenant = Tenant(id=uuid4(), name=payload.name, is_internal=False)
    session.add(tenant)
    try:
        session.flush()
        session.add(
            User(
                id=uuid4(),
                tenant_id=tenant.id,
                email=payload.admin_email,
                name=payload.admin_name,
                password_hash=hash_password(payload.admin_password),
                role="admin",
                is_platform_admin=False,
            )
        )
        session.flush()
        response = _response(session, tenant)
        record_audit(
            session,
            admin,
            "tenant",
            str(tenant.id),
            "create",
            None,
            response.model_dump(mode="json"),
            client_ip(request),
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise APIError(409, "CONFLICT", "Email já cadastrado") from exc
    return response


@router.patch(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    request: Request,
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
) -> TenantResponse:
    tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise APIError(404, "NOT_FOUND", "Conta não encontrada")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("status") == "suspended" and tenant.id == admin.tenant_id:
        raise APIError(409, "CONFLICT", "Não é permitido suspender sua própria conta")
    before = _response(session, tenant).model_dump(mode="json")
    for key, value in changes.items():
        setattr(tenant, key, value)
    if tenant.status == "suspended":
        for bot in session.scalars(
            select(Bot).where(Bot.owner_id == tenant.id, Bot.status == "active").with_for_update()
        ):
            bot.status = "paused"
            record_audit(
                session,
                admin,
                "bot",
                str(bot.id),
                "tenant_suspended",
                {"status": "active"},
                {"status": "paused"},
                client_ip(request),
            )
    session.flush()
    response = _response(session, tenant)
    record_audit(
        session,
        admin,
        "tenant",
        str(tenant.id),
        "update",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response
