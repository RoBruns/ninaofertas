"""CRUD, vinculacoes, comandos e saude dos bots."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.bot import (
    AutomationRunResponse,
    BotAccountsUpdate,
    BotCreate,
    BotGroupsUpdate,
    BotHealth,
    BotResponse,
    BotUpdate,
)
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from api.schemas.phone import CommandResponse
from core.bot_settings import BotSettings
from core.models import (
    AutomationRun,
    Bot,
    BotGroup,
    BotPlatformAccount,
    Command,
    Group,
    Niche,
    Phone,
    PlatformAccount,
    PlatformCredential,
    User,
)

router = APIRouter(prefix="/bots", tags=["bots"])
AdminUser = Annotated[User, Depends(require_role("admin"))]
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]
ACTIVATION_CONFLICT = "Vincule um telefone e ao menos um grupo antes de ativar o bot"


def _owned(session: Session, bot_id: UUID, owner_id: UUID) -> Bot:
    bot = session.scalar(select(Bot).where(Bot.id == bot_id, Bot.owner_id == owner_id))
    if bot is None:
        raise APIError(404, "NOT_FOUND", "Bot nao encontrado")
    return bot


def _validate_refs(
    session: Session,
    owner_id: UUID,
    *,
    niche_id: int | None = None,
    phone_id: UUID | None = None,
) -> None:
    if niche_id is not None and session.scalar(
        select(Niche.id).where(Niche.id == niche_id, Niche.owner_id == owner_id)
    ) is None:
        raise APIError(404, "NOT_FOUND", "Nicho nao encontrado")
    if phone_id is not None and session.scalar(
        select(Phone.id).where(Phone.id == phone_id, Phone.owner_id == owner_id)
    ) is None:
        raise APIError(404, "NOT_FOUND", "Telefone nao encontrado")


def _group_ids(session: Session, bot_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(BotGroup.group_id).where(
                BotGroup.bot_id == bot_id, BotGroup.is_active.is_(True)
            ).order_by(BotGroup.group_id)
        )
    )


def _account_ids(session: Session, bot_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(BotPlatformAccount.account_id).where(
                BotPlatformAccount.bot_id == bot_id, BotPlatformAccount.is_active.is_(True)
            ).order_by(BotPlatformAccount.account_id)
        )
    )


def bot_response(session: Session, bot: Bot) -> BotResponse:
    return BotResponse(
        id=bot.id,
        name=bot.name,
        slug=bot.slug,
        niche_id=bot.niche_id,
        phone_id=bot.phone_id,
        status=bot.status,
        settings=BotSettings.model_validate(bot.settings),
        message_template=bot.message_template,
        group_ids=_group_ids(session, bot.id),
        account_ids=_account_ids(session, bot.id),
        last_run_at=bot.last_run_at,
        last_success_at=bot.last_success_at,
        created_at=bot.created_at,
        updated_at=bot.updated_at,
    )


def _audit(response: BotResponse) -> dict[str, Any]:
    return response.model_dump(mode="json")


def _ensure_groups(session: Session, owner_id: UUID, group_ids: list[UUID]) -> list[Group]:
    unique_ids = list(dict.fromkeys(group_ids))
    groups = list(
        session.scalars(select(Group).where(Group.owner_id == owner_id, Group.id.in_(unique_ids)))
    ) if unique_ids else []
    if len(groups) != len(unique_ids):
        raise APIError(404, "NOT_FOUND", "Um ou mais grupos nao foram encontrados")
    return groups


def _has_publishable_group(session: Session, bot_id: UUID) -> bool:
    return session.scalar(
        select(BotGroup.group_id)
        .join(Group, Group.id == BotGroup.group_id)
        .where(
            BotGroup.bot_id == bot_id,
            BotGroup.is_active.is_(True),
            Group.status != "archived",
        )
        .limit(1)
    ) is not None


def _ensure_can_activate(session: Session, bot: Bot) -> None:
    if bot.phone_id is None or not _has_publishable_group(session, bot.id):
        raise APIError(409, "CONFLICT", ACTIVATION_CONFLICT)


def _ensure_accounts(
    session: Session, owner_id: UUID, account_ids: list[UUID]
) -> list[PlatformAccount]:
    unique_ids = list(dict.fromkeys(account_ids))
    accounts = list(
        session.scalars(
            select(PlatformAccount).where(
                PlatformAccount.owner_id == owner_id, PlatformAccount.id.in_(unique_ids)
            )
        )
    ) if unique_ids else []
    if len(accounts) != len(unique_ids):
        raise APIError(404, "NOT_FOUND", "Uma ou mais contas nao foram encontradas")
    return accounts


def _replace_groups(session: Session, bot: Bot, group_ids: list[UUID]) -> None:
    groups = _ensure_groups(session, bot.owner_id, group_ids)
    session.execute(delete(BotGroup).where(BotGroup.bot_id == bot.id))
    session.add_all(BotGroup(bot_id=bot.id, group_id=group.id, is_active=True) for group in groups)


def _replace_accounts(session: Session, bot: Bot, account_ids: list[UUID]) -> None:
    accounts = _ensure_accounts(session, bot.owner_id, account_ids)
    session.execute(delete(BotPlatformAccount).where(BotPlatformAccount.bot_id == bot.id))
    session.add_all(
        BotPlatformAccount(bot_id=bot.id, account_id=account.id, is_active=True)
        for account in accounts
    )


@router.get("", response_model=PaginatedResponse[BotResponse])
def list_bots(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    status: str | None = None,
    niche_id: int | None = None,
    phone_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: str = "-created_at",
) -> PaginatedResponse[BotResponse]:
    statement = select(Bot).where(Bot.owner_id == user.id)
    if status is not None:
        statement = statement.where(Bot.status == status)
    if niche_id is not None:
        statement = statement.where(Bot.niche_id == niche_id)
    if phone_id is not None:
        statement = statement.where(Bot.phone_id == phone_id)
    items, total = paginate(
        session, statement, PaginationParams(page=page, page_size=page_size, sort=sort),
        {"created_at": Bot.created_at, "updated_at": Bot.updated_at, "name": Bot.name, "status": Bot.status},
    )
    return PaginatedResponse(
        items=[bot_response(session, bot) for bot in items], total=total, page=page, page_size=page_size
    )


@router.post("", response_model=BotResponse, status_code=201, dependencies=[Depends(limit_authenticated_write)])
def create_bot(
    payload: BotCreate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> BotResponse:
    if session.scalar(select(Bot.id).where(Bot.owner_id == admin.id, Bot.slug == payload.slug)):
        raise APIError(409, "CONFLICT", "Ja existe um bot com este slug")
    _validate_refs(session, admin.id, niche_id=payload.niche_id, phone_id=payload.phone_id)
    now = datetime.now(timezone.utc)
    bot = Bot(
        id=uuid4(), owner_id=admin.id, name=payload.name, slug=payload.slug,
        niche_id=payload.niche_id, phone_id=payload.phone_id, status="paused",
        settings=payload.settings.model_dump(mode="json"), message_template=payload.message_template,
        created_at=now, updated_at=now,
    )
    session.add(bot)
    session.flush()
    _replace_groups(session, bot, payload.group_ids)
    _replace_accounts(session, bot, payload.account_ids)
    session.flush()
    response = bot_response(session, bot)
    record_audit(session, admin, "bot", str(bot.id), "create", None, _audit(response), client_ip(request))
    session.commit()
    return response


@router.get("/{bot_id}", response_model=BotResponse)
def get_bot(
    bot_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> BotResponse:
    return bot_response(session, _owned(session, bot_id, user.id))


@router.patch("/{bot_id}", response_model=BotResponse, dependencies=[Depends(limit_authenticated_write)])
def update_bot(
    bot_id: UUID,
    payload: BotUpdate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> BotResponse:
    bot = _owned(session, bot_id, admin.id)
    before = _audit(bot_response(session, bot))
    changes = payload.model_dump(exclude_unset=True)
    if (
        changes.get("name", "ok") is None
        or changes.get("slug", "ok") is None
        or changes.get("settings", "ok") is None
        or changes.get("status", "ok") is None
    ):
        raise APIError(422, "VALIDATION_ERROR", "name, slug, settings e status nao aceitam null")
    if "slug" in changes and session.scalar(
        select(Bot.id).where(Bot.owner_id == admin.id, Bot.slug == changes["slug"], Bot.id != bot.id)
    ):
        raise APIError(409, "CONFLICT", "Ja existe um bot com este slug")
    _validate_refs(
        session, admin.id,
        niche_id=changes.get("niche_id") if "niche_id" in changes else None,
        phone_id=changes.get("phone_id") if "phone_id" in changes else None,
    )
    if "settings" in changes:
        changes["settings"] = changes["settings"].model_dump(mode="json")
    for field, value in changes.items():
        setattr(bot, field, value)
    if changes.get("status") == "active" or (
        bot.status == "active" and "phone_id" in changes
    ):
        _ensure_can_activate(session, bot)
    bot.updated_at = datetime.now(timezone.utc)
    session.flush()
    response = bot_response(session, bot)
    record_audit(session, admin, "bot", str(bot.id), "update", before, _audit(response), client_ip(request))
    session.commit()
    return response


@router.delete("/{bot_id}", status_code=204, dependencies=[Depends(limit_authenticated_write)])
def delete_bot(
    bot_id: UUID,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    bot = _owned(session, bot_id, admin.id)
    before = _audit(bot_response(session, bot))
    session.delete(bot)
    record_audit(session, admin, "bot", str(bot.id), "delete", before, None, client_ip(request))
    session.commit()


def _unique_slug(session: Session, owner_id: UUID, source: str) -> str:
    suffix = 2
    while session.scalar(select(Bot.id).where(Bot.owner_id == owner_id, Bot.slug == f"{source}-{suffix}")):
        suffix += 1
    return f"{source}-{suffix}"


@router.post("/{bot_id}/duplicate", response_model=BotResponse, status_code=201, dependencies=[Depends(limit_authenticated_write)])
def duplicate_bot(
    bot_id: UUID,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> BotResponse:
    source = _owned(session, bot_id, admin.id)
    now = datetime.now(timezone.utc)
    duplicate = Bot(
        id=uuid4(), owner_id=admin.id, name=f"{source.name} (copia)",
        slug=_unique_slug(session, admin.id, source.slug), niche_id=source.niche_id,
        phone_id=source.phone_id, status="paused", settings=deepcopy(source.settings),
        message_template=source.message_template, created_at=now, updated_at=now,
    )
    session.add(duplicate)
    session.flush()
    for link in session.scalars(select(BotGroup).where(BotGroup.bot_id == source.id)):
        session.add(BotGroup(bot_id=duplicate.id, group_id=link.group_id, is_active=link.is_active))
    for link in session.scalars(select(BotPlatformAccount).where(BotPlatformAccount.bot_id == source.id)):
        session.add(BotPlatformAccount(bot_id=duplicate.id, account_id=link.account_id, is_active=link.is_active))
    session.flush()
    response = bot_response(session, duplicate)
    record_audit(session, admin, "bot", str(duplicate.id), "duplicate", None, _audit(response), client_ip(request))
    session.commit()
    return response


def _change_status(bot_id: UUID, status: str, action: str, request: Request, user: User, session: Session) -> BotResponse:
    bot = _owned(session, bot_id, user.id)
    before = _audit(bot_response(session, bot))
    if status == "active":
        _ensure_can_activate(session, bot)
    bot.status = status
    bot.updated_at = datetime.now(timezone.utc)
    response = bot_response(session, bot)
    record_audit(session, user, "bot", str(bot.id), action, before, _audit(response), client_ip(request))
    session.commit()
    return response


@router.post("/{bot_id}/activate", response_model=BotResponse, dependencies=[Depends(limit_authenticated_write)])
def activate_bot(bot_id: UUID, request: Request, user: OperatorUser, session: Annotated[Session, Depends(get_db)]) -> BotResponse:
    return _change_status(bot_id, "active", "activate", request, user, session)


@router.post("/{bot_id}/pause", response_model=BotResponse, dependencies=[Depends(limit_authenticated_write)])
def pause_bot(bot_id: UUID, request: Request, user: OperatorUser, session: Annotated[Session, Depends(get_db)]) -> BotResponse:
    return _change_status(bot_id, "paused", "pause", request, user, session)


@router.post("/{bot_id}/disable", response_model=BotResponse, dependencies=[Depends(limit_authenticated_write)])
def disable_bot(bot_id: UUID, request: Request, user: OperatorUser, session: Annotated[Session, Depends(get_db)]) -> BotResponse:
    return _change_status(bot_id, "disabled", "disable", request, user, session)


@router.post("/{bot_id}/run-now", response_model=CommandResponse, status_code=202, dependencies=[Depends(limit_authenticated_write)])
def run_now(
    bot_id: UUID,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> CommandResponse:
    bot = _owned(session, bot_id, user.id)
    command = Command(bot_id=bot.id, type="run_now", payload={}, status="pending", requested_by=user.id)
    session.add(command)
    session.flush()
    record_audit(session, user, "bot", str(bot.id), "run_now", None, {"command_id": command.id}, client_ip(request))
    session.commit()
    return CommandResponse(command_id=command.id)


def _run_response(run: AutomationRun) -> AutomationRunResponse:
    return AutomationRunResponse(
        id=run.id, kind=run.kind, status=run.status, started_at=run.started_at,
        finished_at=run.finished_at, duration_ms=run.duration_ms, offers_found=run.offers_found,
        offers_sent=run.offers_sent, error=run.error, detail=run.detail,
    )


@router.get("/{bot_id}/runs", response_model=PaginatedResponse[AutomationRunResponse])
def list_runs(
    bot_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: str = "-started_at",
) -> PaginatedResponse[AutomationRunResponse]:
    bot = _owned(session, bot_id, user.id)
    items, total = paginate(
        session, select(AutomationRun).where(AutomationRun.bot_id == bot.id),
        PaginationParams(page=page, page_size=page_size, sort=sort),
        {"started_at": AutomationRun.started_at, "status": AutomationRun.status},
    )
    return PaginatedResponse(items=[_run_response(run) for run in items], total=total, page=page, page_size=page_size)


@router.get("/{bot_id}/health", response_model=BotHealth)
def get_health(
    bot_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> BotHealth:
    bot = _owned(session, bot_id, user.id)
    latest = session.scalar(
        select(AutomationRun).where(AutomationRun.bot_id == bot.id).order_by(AutomationRun.started_at.desc()).limit(1)
    )
    credential_issues: list[str] = []
    account_ids = _account_ids(session, bot.id)
    now = datetime.now(timezone.utc)
    if account_ids:
        credentials = list(
            session.scalars(select(PlatformCredential).where(PlatformCredential.account_id.in_(account_ids)))
        )
        accounts_with_credentials = {credential.account_id for credential in credentials}
        for account_id in account_ids:
            if account_id not in accounts_with_credentials:
                credential_issues.append(f"Conta {account_id} sem credencial")
        for credential in credentials:
            if credential.status in {"invalid", "expired"} or (
                credential.expires_at is not None and credential.expires_at <= now
            ):
                credential_issues.append(f"Credencial {credential.kind} precisa ser renovada")
    group_issues = [
        group.name or group.whatsapp_id
        for group in session.scalars(
            select(Group).join(BotGroup, BotGroup.group_id == Group.id).where(
                BotGroup.bot_id == bot.id,
                BotGroup.is_active.is_(True),
                (Group.status != "active") | (Group.is_announce.is_(True) & Group.bot_is_admin.is_not(True)),
            )
        )
    ]
    check_interval = BotSettings.model_validate(bot.settings).schedule.check_interval
    is_recent = latest is not None and latest.started_at >= now - timedelta(seconds=max(900, check_interval * 3))
    if credential_issues or (latest is not None and latest.status == "failed"):
        status, message = "error", "Bot requer atencao antes da proxima execucao"
    elif not is_recent:
        status, message = "unknown", "Sem execucao recente para confirmar a saude do bot"
    elif group_issues or latest.status in {"partial", "running"}:
        status, message = "warning", "Bot executa com alertas"
    else:
        status, message = "ok", "Ultima execucao concluida sem alertas"
    return BotHealth(
        status=status, message=message, last_run_status=latest.status if latest else None,
        last_run_at=latest.started_at if latest else None,
        credential_issues=credential_issues, group_issues=group_issues,
    )


@router.put("/{bot_id}/groups", response_model=BotResponse, dependencies=[Depends(limit_authenticated_write)])
def set_groups(
    bot_id: UUID,
    payload: BotGroupsUpdate,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> BotResponse:
    bot = _owned(session, bot_id, user.id)
    before = _audit(bot_response(session, bot))
    groups = _ensure_groups(session, bot.owner_id, payload.group_ids)
    if bot.status == "active" and not any(group.status != "archived" for group in groups):
        raise APIError(409, "CONFLICT", ACTIVATION_CONFLICT)
    _replace_groups(session, bot, payload.group_ids)
    session.flush()
    response = bot_response(session, bot)
    record_audit(session, user, "bot", str(bot.id), "set_groups", before, _audit(response), client_ip(request))
    session.commit()
    return response


@router.put("/{bot_id}/accounts", response_model=BotResponse, dependencies=[Depends(limit_authenticated_write)])
def set_accounts(
    bot_id: UUID,
    payload: BotAccountsUpdate,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> BotResponse:
    bot = _owned(session, bot_id, user.id)
    before = _audit(bot_response(session, bot))
    _replace_accounts(session, bot, payload.account_ids)
    session.flush()
    response = bot_response(session, bot)
    record_audit(session, user, "bot", str(bot.id), "set_accounts", before, _audit(response), client_ip(request))
    session.commit()
    return response
