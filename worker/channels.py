"""Configuração dos canais e filtros versionados."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

from core.channels import CANAIS
from core.settings import load_filtros_atual, usar_arquivo_config

_canal: ContextVar[str] = ContextVar("canal", default="achadinhos")


def canais_ativos() -> tuple[str, ...]:
    return tuple(k for k, v in CANAIS.items() if v.get("ativo", True))


@contextmanager
def usar_canal(canal: str):
    if canal not in CANAIS:
        raise ValueError(f"Canal desconhecido: {canal}")
    token = _canal.set(canal)
    try:
        with usar_arquivo_config(str(CANAIS[canal]["arquivo"])):
            yield
    finally:
        _canal.reset(token)


def canal_atual() -> str:
    return _canal.get()


def nome_canal() -> str:
    return str(CANAIS[_canal.get()]["nome"])


def grupo_whatsapp() -> str:
    env_name = str(CANAIS[_canal.get()]["grupo_env"])
    return os.getenv(env_name, "") or os.getenv("WHATSAPP_GROUP_ID", "")


def load_filtros() -> dict:
    """Lê o config do canal atual. Recarregado a cada chamada."""
    return load_filtros_atual()


__all__ = [
    "CANAIS",
    "canal_atual",
    "canais_ativos",
    "grupo_whatsapp",
    "load_filtros",
    "nome_canal",
    "usar_canal",
]
