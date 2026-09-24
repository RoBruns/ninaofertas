"""Canais do worker: um por (bot ativo, grupo), sempre vindos do dashboard.

Nao ha modo legado (ADR-020): sem bot ativo com telefone e grupo, o worker
nao publica nada.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import select

from core import db
from core.config_provider import (
    BotRuntime,
    bot_runtime_atual,
    bots_ativos,
    load_filtros_runtime,
    usar_bot_runtime,
)
from core.models import BotGroup, Group

_canal: ContextVar[str] = ContextVar("canal", default="")
_grupo: ContextVar[str | None] = ContextVar("grupo_runtime", default=None)


def _token(runtime: BotRuntime, grupo: str) -> str:
    return f"db:{runtime.id}:{grupo}"


def _resolver_token(canal: str) -> tuple[BotRuntime, str] | None:
    if not canal.startswith("db:"):
        return None
    for runtime in bots_ativos():
        for grupo in runtime.group_ids:
            if _token(runtime, grupo) == canal:
                return runtime, grupo
    return None


def canais_ativos() -> tuple[str, ...]:
    return tuple(_token(runtime, grupo) for runtime in bots_ativos() for grupo in runtime.group_ids)


@contextmanager
def usar_canal(canal: str):
    resolved = _resolver_token(canal)
    if resolved is None:
        raise ValueError(f"Canal desconhecido ou bot nao esta mais ativo: {canal}")
    canal_token = _canal.set(canal)
    grupo_token = _grupo.set(resolved[1])
    try:
        with usar_bot_runtime(resolved[0]):
            yield
    finally:
        _grupo.reset(grupo_token)
        _canal.reset(canal_token)


def canal_atual() -> str:
    return _canal.get()


def nome_canal() -> str:
    runtime = bot_runtime_atual()
    return runtime.nome if runtime is not None else "sem bot"


def grupo_whatsapp() -> str:
    return _grupo.get() or ""


def load_filtros() -> dict:
    """Le os settings do bot atual, editados no dashboard."""
    return load_filtros_runtime()


def bot_atual() -> BotRuntime | None:
    return bot_runtime_atual()


def telefone_bot() -> str | None:
    runtime = bot_runtime_atual()
    return runtime.phone_number if runtime else None


def instancia_evolution() -> str | None:
    runtime = bot_runtime_atual()
    return runtime.evolution_instance if runtime else None


def grupo_db_id() -> UUID | None:
    runtime = bot_runtime_atual()
    grupo = _grupo.get()
    if runtime is None or grupo is None:
        return None
    try:
        with db.get_session() as session:
            return session.scalar(
                select(Group.id)
                .join(BotGroup, BotGroup.group_id == Group.id)
                .where(BotGroup.bot_id == runtime.id, Group.whatsapp_id == grupo)
            )
    except Exception:
        return None


__all__ = [
    "bot_atual",
    "canal_atual",
    "canais_ativos",
    "grupo_db_id",
    "grupo_whatsapp",
    "instancia_evolution",
    "load_filtros",
    "nome_canal",
    "telefone_bot",
    "usar_canal",
]
