"""CRUD e operacao de contas de plataforma."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.account import (
    AccountCreate,
    AccountHealth,
    AccountResponse,
    AccountUpdate,
)
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from api.schemas.credential import CredentialStatus
from api.schemas.platform import PlatformSummary
from core.models import (
    Bot,
    BotPlatformAccount,
    Platform,
    PlatformAccount,
    PlatformCredential,
    User,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])
AdminUser = Annotated[User, Depends(require_role("admin"))]
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]


def get_owned_account(session: Session, account_id: UUID, owner_id: UUID) -> PlatformAccount:
    account = session.scalar(
        select(PlatformAccount).where(
            PlatformAccount.id == account_id,
            PlatformAccount.owner_id == owner_id,
        )
    )
    if account is None:
        raise APIError(404, "NOT_FOUND", "Conta de plataforma nao encontrada")
    return account


def credential_status(credential: PlatformCredential) -> CredentialStatus:
    now = datetime.now(timezone.utc)
    state = credential.status
    if credential.expires_at is not None:
        if credential.expires_at <= now:
            state = "expired"
        elif credential.expires_at <= now + timedelta(hours=48) and state != "invalid":
            state = "expiring"
    if state not in {"valid", "expiring", "expired", "invalid", "unknown"}:
        state = "unknown"
    return CredentialStatus(
        kind=credential.kind,
        status=state,
        expires_at=credential.expires_at,
        last_rotated_at=credential.last_rotated_at,
        last_used_at=credential.last_used_at,
        last_success_at=credential.last_success_at,
        last_error=credential.last_error,
        last_error_at=credential.last_error_at,
        needs_renewal=state in {"expiring", "expired", "invalid"},
    )


def _health(credentials: list[CredentialStatus]) -> AccountHealth:
    states = {credential.status for credential in credentials}
    if "invalid" in states or "expired" in states:
        return AccountHealth(status="error", message="Uma credencial precisa ser renovada")
    if "expiring" in states:
        return AccountHealth(status="warning", message="Uma credencial expira em menos de 48 horas")
    if not credentials or "unknown" in states:
        return AccountHealth(status="unknown", message="Credenciais ainda nao validadas")
    return AccountHealth(status="ok", message=None)


def account_response(session: Session, account: PlatformAccount) -> AccountResponse:
    platform = session.get(Platform, account.platform_id)
    if platform is None:
        raise APIError(500, "INTERNAL", "Plataforma da conta nao encontrada")
    credentials = [
        credential_status(credential)
        for credential in session.scalars(
            select(PlatformCredential)
            .where(PlatformCredential.account_id == account.id)
            .order_by(PlatformCredential.kind.asc())
        )
    ]
    return AccountResponse(
        id=account.id,
        platform=PlatformSummary.model_validate(platform),
        label=account.label,
        external_id=account.external_id,
        status=account.status,
        config=account.config,
        notes=account.notes,
        credentials=credentials,
        health=_health(credentials),
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _audit_account(response: AccountResponse) -> dict[str, Any]:
    return response.model_dump(mode="json")


@router.get("", response_model=PaginatedResponse[AccountResponse])
def list_accounts(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    platform_id: int | None = None,
    status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    sort: str = "-created_at",
) -> PaginatedResponse[AccountResponse]:
    statement = select(PlatformAccount).where(PlatformAccount.owner_id == current_user.id)
    if platform_id is not None:
        statement = statement.where(PlatformAccount.platform_id == platform_id)
    if status is not None:
        statement = statement.where(PlatformAccount.status == status)
    accounts, total = paginate(
        session,
        statement,
        PaginationParams(page=page, page_size=page_size, sort=sort),
        {
            "created_at": PlatformAccount.created_at,
            "updated_at": PlatformAccount.updated_at,
            "label": PlatformAccount.label,
            "status": PlatformAccount.status,
        },
    )
    return PaginatedResponse(
        items=[account_response(session, account) for account in accounts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=AccountResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_account(
    payload: AccountCreate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    platform = session.get(Platform, payload.platform_id)
    if platform is None:
        raise APIError(404, "NOT_FOUND", "Plataforma nao encontrada")
    duplicate = session.scalar(
        select(PlatformAccount.id).where(
            PlatformAccount.owner_id == admin.id,
            PlatformAccount.platform_id == payload.platform_id,
            PlatformAccount.label == payload.label,
        )
    )
    if duplicate is not None:
        raise APIError(409, "CONFLICT", "Ja existe uma conta com este label na plataforma")
    now = datetime.now(timezone.utc)
    account = PlatformAccount(
        id=uuid4(),
        owner_id=admin.id,
        platform_id=payload.platform_id,
        label=payload.label,
        external_id=payload.external_id,
        status="active",
        config=payload.config,
        notes=payload.notes,
        created_at=now,
        updated_at=now,
    )
    session.add(account)
    session.flush()
    response = account_response(session, account)
    record_audit(
        session,
        admin,
        "platform_account",
        str(account.id),
        "create",
        None,
        _audit_account(response),
        client_ip(request),
    )
    session.commit()
    return response


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    return account_response(session, get_owned_account(session, account_id, current_user.id))


@router.patch(
    "/{account_id}",
    response_model=AccountResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    account = get_owned_account(session, account_id, admin.id)
    before = _audit_account(account_response(session, account))
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("label", "valid") is None or changes.get("config", {}) is None:
        raise APIError(422, "VALIDATION_ERROR", "label e config nao aceitam null")
    if "label" in changes:
        duplicate = session.scalar(
            select(PlatformAccount.id).where(
                PlatformAccount.owner_id == admin.id,
                PlatformAccount.platform_id == account.platform_id,
                PlatformAccount.label == changes["label"],
                PlatformAccount.id != account.id,
            )
        )
        if duplicate is not None:
            raise APIError(409, "CONFLICT", "Ja existe uma conta com este label na plataforma")
    for field, value in changes.items():
        setattr(account, field, value)
    account.updated_at = datetime.now(timezone.utc)
    session.flush()
    response = account_response(session, account)
    record_audit(
        session,
        admin,
        "platform_account",
        str(account.id),
        "update",
        before,
        _audit_account(response),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/{account_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_account(
    account_id: UUID,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    account = get_owned_account(session, account_id, admin.id)
    bots = list(
        session.scalars(
            select(Bot)
            .join(BotPlatformAccount, BotPlatformAccount.bot_id == Bot.id)
            .where(BotPlatformAccount.account_id == account.id)
            .order_by(Bot.name.asc())
        )
    )
    if bots:
        names = ", ".join(bot.name for bot in bots)
        raise APIError(
            409,
            "CONFLICT",
            f"Conta vinculada aos bots: {names}",
            {"bots": names},
        )
    before = _audit_account(account_response(session, account))
    session.delete(account)
    record_audit(
        session,
        admin,
        "platform_account",
        str(account.id),
        "delete",
        before,
        None,
        client_ip(request),
    )
    session.commit()


def _change_status(
    account_id: UUID,
    status: str,
    action: str,
    request: Request,
    user: User,
    session: Session,
) -> AccountResponse:
    account = get_owned_account(session, account_id, user.id)
    before = _audit_account(account_response(session, account))
    account.status = status
    account.updated_at = datetime.now(timezone.utc)
    session.flush()
    response = account_response(session, account)
    record_audit(
        session,
        user,
        "platform_account",
        str(account.id),
        action,
        before,
        _audit_account(response),
        client_ip(request),
    )
    session.commit()
    return response


@router.post(
    "/{account_id}/activate",
    response_model=AccountResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def activate_account(
    account_id: UUID,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    return _change_status(account_id, "active", "activate", request, user, session)


@router.post(
    "/{account_id}/pause",
    response_model=AccountResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def pause_account(
    account_id: UUID,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    return _change_status(account_id, "paused", "pause", request, user, session)
