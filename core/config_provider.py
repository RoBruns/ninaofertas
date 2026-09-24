"""Configuracao operacional dos bots, lida do banco com fallback seguro."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, SQLAlchemyError

from core import db
from core.bot_settings import BotSettings
from core.models import Bot, BotGroup, BotPlatformAccount, Event, Group, Niche, Phone
from core.settings import load_filtros_atual


@dataclass(frozen=True)
class BotRuntime:
    id: UUID
    slug: str
    nome: str
    niche_slug: str | None
    phone_number: str | None
    evolution_instance: str | None
    group_ids: tuple[str, ...]
    settings: BotSettings
    account_ids: tuple[UUID, ...]


_cache: list[BotRuntime] | None = None
_cache_at = 0.0
_cache_lock = threading.Lock()
_runtime_context: ContextVar[BotRuntime | None] = ContextVar("bot_runtime", default=None)


@contextmanager
def usar_bot_runtime(runtime: BotRuntime | None):
    token = _runtime_context.set(runtime)
    try:
        yield
    finally:
        _runtime_context.reset(token)


def bot_runtime_atual() -> BotRuntime | None:
    return _runtime_context.get()


def load_filtros_runtime() -> dict:
    runtime = _runtime_context.get()
    if runtime is None:
        return load_filtros_atual()
    dumped = runtime.settings.model_dump(mode="python")
    if runtime.settings.legacy_input:
        return dumped
    flattened: dict = {}
    for section in ("filters", "pacing", "content", "schedule"):
        flattened.update(dumped.pop(section, {}))
    dumped.pop("schema_version", None)
    flattened.update(dumped)
    return flattened


def registrar_evento_runtime(
    event_type: str,
    message: str,
    *,
    detail: dict | None = None,
    level: str = "error",
) -> None:
    """Emite evento do bot em contexto sem criar dependencia de core em worker."""
    runtime = _runtime_context.get()
    try:
        with db.get_session() as session:
            session.add(
                Event(
                    bot_id=runtime.id if runtime else None,
                    entity_type="bot" if runtime else None,
                    entity_id=str(runtime.id) if runtime else None,
                    level=level,
                    type=event_type,
                    message=message,
                    detail=detail,
                )
            )
    except Exception as exc:
        logger.debug(f"Nao foi possivel gravar evento {event_type}: {exc}")


def invalidar_cache() -> None:
    """Forca a proxima leitura a consultar o banco."""
    global _cache_at
    with _cache_lock:
        _cache_at = 0.0


def _registrar_config_invalida(bot: Bot, exc: ValidationError) -> None:
    logger.error(f"Configuracao invalida no bot {bot.slug}: {exc}")
    try:
        with db.get_session() as session:
            session.add(
                Event(
                    bot_id=bot.id,
                    entity_type="bot",
                    entity_id=str(bot.id),
                    level="error",
                    type="config_invalid",
                    message=f"Configuracao invalida no bot {bot.slug}",
                    detail={
                        "errors": json.loads(exc.json(include_url=False, include_input=False))
                    },
                )
            )
    except Exception as event_exc:
        logger.debug(f"Nao foi possivel gravar evento config_invalid: {event_exc}")


def _registrar_bot_nao_executavel(bot: Bot, reasons: list[str]) -> None:
    reason = ", ".join(reasons)
    logger.warning(f"Bot {bot.slug} esta ativo mas nao pode publicar: {reason}")
    try:
        with db.get_session() as session:
            session.add(
                Event(
                    bot_id=bot.id,
                    entity_type="bot",
                    entity_id=str(bot.id),
                    level="warning",
                    type="bot_not_runnable",
                    message=f"Bot {bot.slug} esta ativo mas nao pode publicar",
                    detail={"reasons": reasons},
                )
            )
    except Exception as event_exc:
        logger.debug(f"Nao foi possivel gravar evento bot_not_runnable: {event_exc}")


def _carregar() -> list[BotRuntime]:
    invalidos: list[tuple[Bot, ValidationError]] = []
    nao_executaveis: list[tuple[Bot, list[str]]] = []
    runtimes: list[BotRuntime] = []
    with db.get_session() as session:
        rows = session.execute(
            select(Bot, Niche.slug, Phone.number, Phone.evolution_instance)
            .outerjoin(Niche, Niche.id == Bot.niche_id)
            .outerjoin(Phone, Phone.id == Bot.phone_id)
            .where(Bot.status == "active")
            .order_by(Bot.slug)
        ).all()
        for bot, niche_slug, phone_number, evolution_instance in rows:
            group_ids = tuple(
                session.scalars(
                    select(Group.whatsapp_id)
                    .join(BotGroup, BotGroup.group_id == Group.id)
                    .where(
                        BotGroup.bot_id == bot.id,
                        BotGroup.is_active.is_(True),
                        Group.status == "active",
                    )
                    .order_by(Group.whatsapp_id)
                )
            )
            account_ids = tuple(
                session.scalars(
                    select(BotPlatformAccount.account_id)
                    .where(
                        BotPlatformAccount.bot_id == bot.id,
                        BotPlatformAccount.is_active.is_(True),
                    )
                    .order_by(BotPlatformAccount.account_id)
                )
            )
            reasons: list[str] = []
            if not phone_number or not evolution_instance:
                reasons.append("telefone ou instancia nao resolvido")
            if not group_ids:
                reasons.append("nenhum grupo ativo")
            if reasons:
                nao_executaveis.append((bot, reasons))
                continue
            try:
                raw_settings = dict(bot.settings or {})
                if bot.message_template and "mensagem_template" not in raw_settings:
                    raw_settings["mensagem_template"] = bot.message_template
                bot_settings = BotSettings.model_validate(raw_settings)
            except ValidationError as exc:
                invalidos.append((bot, exc))
                continue
            runtimes.append(
                BotRuntime(
                    id=bot.id,
                    slug=bot.slug,
                    nome=bot.name,
                    niche_slug=niche_slug,
                    phone_number=phone_number,
                    evolution_instance=evolution_instance,
                    group_ids=group_ids,
                    settings=bot_settings,
                    account_ids=account_ids,
                )
            )
    for bot, exc in invalidos:
        _registrar_config_invalida(bot, exc)
    for bot, reasons in nao_executaveis:
        _registrar_bot_nao_executavel(bot, reasons)
    return runtimes


def bots_ativos(ttl: int = 30) -> list[BotRuntime]:
    """Retorna bots ativos resolvidos; nunca deixa uma falha chegar ao worker."""
    global _cache, _cache_at
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None and now - _cache_at < ttl:
            return list(_cache)
        try:
            loaded = _carregar()
        except (ProgrammingError, DBAPIError) as exc:
            if isinstance(exc, OperationalError) and _cache is not None:
                logger.debug(f"Banco indisponivel; usando ultimo cache de bots: {exc}")
                return list(_cache)
            logger.debug(f"Configuracao de bots indisponivel; usando legado: {exc}")
            return []
        except SQLAlchemyError as exc:
            logger.debug(f"Falha ao ler configuracao de bots; usando legado: {exc}")
            return list(_cache) if _cache is not None else []
        except Exception as exc:
            logger.error(f"Falha inesperada ao ler configuracao de bots; usando legado: {exc}")
            return list(_cache) if _cache is not None else []
        _cache = loaded
        _cache_at = now
        return list(loaded)


__all__ = [
    "BotRuntime",
    "bot_runtime_atual",
    "bots_ativos",
    "invalidar_cache",
    "load_filtros_runtime",
    "registrar_evento_runtime",
    "usar_bot_runtime",
]
