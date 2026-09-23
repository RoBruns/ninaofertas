"""Configuracao dos canais: banco primeiro, arquivos legados como fallback."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import select

from core import db
from core.channels import CANAIS
from core.config_provider import (
    BotRuntime,
    bot_runtime_atual,
    bots_ativos,
    load_filtros_runtime,
    usar_bot_runtime,
)
from core.models import BotGroup, Group
from core.settings import usar_arquivo_config

_canal: ContextVar[str] = ContextVar("canal", default="achadinhos")
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
    runtimes = bots_ativos()
    if runtimes:
        return tuple(_token(runtime, grupo) for runtime in runtimes for grupo in runtime.group_ids)
    return tuple(key for key, value in CANAIS.items() if value.get("ativo", True))


@contextmanager
def usar_canal(canal: str):
    resolved = _resolver_token(canal)
    if canal not in CANAIS and resolved is None:
        raise ValueError(f"Canal desconhecido: {canal}")
    canal_token = _canal.set(canal)
    grupo_token = _grupo.set(resolved[1] if resolved else None)
    try:
        arquivo = str(CANAIS[canal]["arquivo"]) if canal in CANAIS else "config.json"
        with usar_bot_runtime(resolved[0] if resolved else None):
            with usar_arquivo_config(arquivo):
                yield
    finally:
        _grupo.reset(grupo_token)
        _canal.reset(canal_token)


def canal_atual() -> str:
    return _canal.get()


def nome_canal() -> str:
    runtime = bot_runtime_atual()
    return runtime.nome if runtime is not None else str(CANAIS[_canal.get()]["nome"])


def grupo_whatsapp() -> str:
    grupo = _grupo.get()
    if grupo is not None:
        return grupo
    env_name = str(CANAIS[_canal.get()]["grupo_env"])
    return os.getenv(env_name, "") or os.getenv("WHATSAPP_GROUP_ID", "")


def load_filtros() -> dict:
    """Le o config do bot atual; sem bot no banco, le o mesmo JSON legado."""
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
    "CANAIS",
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
