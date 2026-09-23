"""Carrega variáveis de ambiente (.env) e critérios de filtro por canal."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# achadinhos = casa/feminino | auto = peças automotivas (Nina Ofertas)
_canal: ContextVar[str] = ContextVar("canal", default="achadinhos")

CANAIS = {
    "achadinhos": {
        "arquivo": "config.json",
        "grupo_env": "WHATSAPP_GROUP_ID",
        "nome": "Achadinhos da Nina",
        "ativo": True,
    },
    "auto": {
        "arquivo": "config.auto.json",
        "grupo_env": "WHATSAPP_GROUP_ID_AUTO",
        "nome": "Nina Ofertas",
        "ativo": False,
    },
}


def canais_ativos() -> tuple[str, ...]:
    return tuple(k for k, v in CANAIS.items() if v.get("ativo", True))


@contextmanager
def usar_canal(canal: str):
    if canal not in CANAIS:
        raise ValueError(f"Canal desconhecido: {canal}")
    token = _canal.set(canal)
    try:
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    check_interval: int = field(default_factory=lambda: _env_int("CHECK_INTERVAL", 60))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///ofertas.db"))

    evolution_api_url: str = field(default_factory=lambda: os.getenv("EVOLUTION_API_URL", "http://localhost:8080"))
    evolution_api_key: str = field(default_factory=lambda: os.getenv("EVOLUTION_API_KEY", ""))
    evolution_instance: str = field(default_factory=lambda: os.getenv("EVOLUTION_INSTANCE", ""))
    whatsapp_group_id: str = field(default_factory=lambda: os.getenv("WHATSAPP_GROUP_ID", ""))
    whatsapp_group_id_auto: str = field(default_factory=lambda: os.getenv("WHATSAPP_GROUP_ID_AUTO", ""))

    reenvio_queda_minima: float = field(default_factory=lambda: float(os.getenv("REENVIO_QUEDA_MINIMA", 15)))

    mercadolivre_app_id: str = field(default_factory=lambda: os.getenv("MERCADOLIVRE_APP_ID", ""))
    mercadolivre_app_secret: str = field(default_factory=lambda: os.getenv("MERCADOLIVRE_APP_SECRET", ""))
    lomadee_source_id: str = field(default_factory=lambda: os.getenv("LOMADEE_SOURCE_ID", ""))
    mercadolivre_affiliate_tag: str = field(default_factory=lambda: os.getenv("MERCADOLIVRE_AFFILIATE_TAG", ""))
    mercadolivre_affiliate_cookie: str = field(default_factory=lambda: os.getenv("MERCADOLIVRE_AFFILIATE_COOKIE", ""))

    shopee_app_id: str = field(default_factory=lambda: os.getenv("SHOPEE_APP_ID", ""))
    shopee_app_secret: str = field(default_factory=lambda: os.getenv("SHOPEE_APP_SECRET", ""))

    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


def load_filtros() -> dict:
    """Lê o config do canal atual. Recarregado a cada chamada."""
    arquivo = str(CANAIS[_canal.get()]["arquivo"])
    path = BASE_DIR / arquivo
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


settings = Settings()
