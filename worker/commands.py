"""Drenagem concorrente e tolerante a falhas da caixa de comandos."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from core.tenant_context import event_tenant_id
from core import db
from core.config_provider import invalidar_cache
from core.models import Bot, Command, Event, Group, Phone, PlatformAccount, Tenant, User
from core.sales_sync import sync_account
from core.settings import settings
from worker.logger import logger

_run_now: set[UUID] = set()
_run_now_lock = threading.Lock()


def consumir_run_now() -> set[UUID]:
    with _run_now_lock:
        result = set(_run_now)
        _run_now.clear()
        return result


def bot_esta_ativo(bot_id: UUID) -> bool:
    """Falha aberta para nao derrubar um ciclo quando o banco oscilar."""
    try:
        with db.get_session() as session:
            status = session.scalar(
                select(Bot.status)
                .join(Tenant, Tenant.id == Bot.owner_id)
                .where(Bot.id == bot_id, Bot.archived_at.is_(None), Tenant.status == "active")
            )
        return status == "active"
    except Exception as exc:
        logger.debug(f"Nao foi possivel confirmar status do bot {bot_id}: {exc}")
        return True


def _grupos_evolution(phone: Phone) -> list[dict]:
    if not phone.evolution_instance:
        raise RuntimeError("Telefone sem instancia da evolution-api")
    url = (
        f"{settings.evolution_api_url.rstrip('/')}/group/fetchAllGroups/{phone.evolution_instance}"
    )
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            url,
            headers={"apikey": settings.evolution_api_key},
            params={"getParticipants": "true"},
        )
    response.raise_for_status()
    payload = response.json()
    groups = (
        payload if isinstance(payload, list) else payload.get("data") or payload.get("groups") or []
    )
    if not isinstance(groups, list):
        raise RuntimeError("Resposta invalida ao sincronizar grupos")
    return [item for item in groups if isinstance(item, dict)]


def _is_admin(group: dict, number: str) -> bool:
    for participant in group.get("participants") or []:
        if number in json.dumps(participant, ensure_ascii=False):
            return bool(participant.get("admin"))
    return False


def _sync_groups(session, command: Command) -> str:
    raw_phone_id = (command.payload or {}).get("phone_id")
    if not raw_phone_id:
        raise ValueError("sync_groups sem phone_id")
    phone = session.get(Phone, UUID(str(raw_phone_id)))
    if phone is None:
        raise ValueError("Telefone nao encontrado")
    now = datetime.now(timezone.utc)
    groups = _grupos_evolution(phone)
    synced = 0
    for item in groups:
        whatsapp_id = str(item.get("id") or item.get("jid") or "")
        if not whatsapp_id:
            continue
        group = session.scalar(
            select(Group).where(Group.phone_id == phone.id, Group.whatsapp_id == whatsapp_id)
        )
        if group is None:
            group = Group(
                owner_id=phone.owner_id,
                phone_id=phone.id,
                whatsapp_id=whatsapp_id,
                discovered_at=now,
            )
            session.add(group)
        group.name = item.get("subject") or item.get("name")
        participants = item.get("participants") or []
        group.participants = len(participants) if isinstance(participants, list) else None
        group.is_announce = bool(item.get("announce"))
        group.bot_is_admin = _is_admin(item, phone.number)
        group.status = "active"
        group.last_synced_at = now
        synced += 1
    return f"{synced} grupos sincronizados"


def _executar(session, command: Command) -> str:
    if _conta_suspensa(session, command):
        raise ValueError("conta suspensa")
    if command.type in {"pause", "resume"}:
        bot = session.get(Bot, command.bot_id)
        if bot is None:
            raise ValueError("Bot nao encontrado")
        if bot.archived_at is not None:
            raise ValueError("Bot arquivado não pode mudar de status")
        bot.status = "paused" if command.type == "pause" else "active"
        invalidar_cache()
        return bot.status
    if command.type == "run_now":
        if command.bot_id is None:
            raise ValueError("run_now sem bot_id")
        with _run_now_lock:
            _run_now.add(command.bot_id)
        return "execucao imediata agendada"
    if command.type == "sync_groups":
        return _sync_groups(session, command)
    if command.type == "reload_config":
        invalidar_cache()
        return "cache invalidado"
    if command.type == "commission_import":
        raw_account_id = (command.payload or {}).get("account_id")
        if not raw_account_id:
            raise ValueError("commission_import sem account_id")
        result = sync_account(UUID(str(raw_account_id)), requested_by=command.requested_by)
        return f"{result.imported} vendas importadas; {result.skipped} sem alteracao"
    raise ValueError(f"Comando desconhecido: {command.type}")


def _conta_suspensa(session: Session, command: Command) -> bool:
    """Verifica autoria e entidade, inclusive comandos sem bot (vendas/grupos)."""
    owners: set[UUID | None] = set()
    if command.requested_by:
        owners.add(session.scalar(select(User.tenant_id).where(User.id == command.requested_by)))
    if command.bot_id:
        owners.add(session.scalar(select(Bot.owner_id).where(Bot.id == command.bot_id)))
    for key, model in (("account_id", PlatformAccount), ("phone_id", Phone)):
        raw_id = (command.payload or {}).get(key)
        if raw_id:
            try:
                entity_id = UUID(str(raw_id))
            except ValueError:
                continue
            owners.add(session.scalar(select(model.owner_id).where(model.id == entity_id)))
    return (
        session.scalar(
            select(Tenant.id)
            .where(Tenant.id.in_(owners - {None}), Tenant.status == "suspended")
            .limit(1)
        )
        is not None
    )


def _marcar_falha(command_id: int, exc: Exception) -> None:
    try:
        with db.get_session() as session:
            command = session.get(Command, command_id)
            if command is not None:
                command.status = "failed"
                command.finished_at = datetime.now(timezone.utc)
                if str(exc) == "conta suspensa":
                    command.result = "conta suspensa"
                elif command.type == "commission_import":
                    account_id = str((command.payload or {}).get("account_id") or "")
                    command.result = "Falha na sincronizacao de vendas"
                    session.add(
                        Event(
                            entity_type="platform_account",
                            tenant_id=event_tenant_id(
                                session, entity_type="platform_account", entity_id=account_id
                            ),
                            entity_id=account_id or None,
                            level="error",
                            type="commission_import_failed",
                            message="Sincronizacao de vendas solicitada falhou",
                            detail={"error_type": type(exc).__name__},
                        )
                    )
                else:
                    command.result = str(exc)[:1000]
    except Exception as mark_exc:
        logger.debug(f"Nao foi possivel marcar comando {command_id} como failed: {mark_exc}")


def drenar_comandos(limit: int = 10) -> None:
    """Processa ate ``limit`` comandos sem bloquear outros workers."""
    for _ in range(limit):
        try:
            with db.get_session() as session:
                command = session.scalar(
                    select(Command)
                    .where(Command.status == "pending")
                    .order_by(Command.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if command is None:
                    return
                if _conta_suspensa(session, command):
                    command.status = "failed"
                    command.result = "conta suspensa"
                    command.finished_at = datetime.now(timezone.utc)
                    continue
                command.status = "running"
                command.picked_at = datetime.now(timezone.utc)
                command_id = command.id
        except (ProgrammingError, DBAPIError):
            return
        except Exception as exc:
            logger.debug(f"Drenagem de comandos indisponivel: {exc}")
            return

        try:
            with db.get_session() as session:
                command = session.get(Command, command_id)
                if command is None:
                    continue
                result = _executar(session, command)
                command.status = "done"
                command.finished_at = datetime.now(timezone.utc)
                command.result = result
        except Exception as exc:
            logger.error(f"Comando {command_id} falhou")
            _marcar_falha(command_id, exc)


__all__ = ["bot_esta_ativo", "consumir_run_now", "drenar_comandos"]
