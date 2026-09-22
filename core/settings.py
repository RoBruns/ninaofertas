"""Carrega variáveis de ambiente (.env)."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
_arquivo_config: ContextVar[str] = ContextVar("arquivo_config", default="config.json")


@contextmanager
def usar_arquivo_config(arquivo: str):
    token = _arquivo_config.set(arquivo)
    try:
        yield
    finally:
        _arquivo_config.reset(token)


def load_filtros_atual() -> dict:
    """Lê o config selecionado pelo worker. Recarregado a cada chamada."""
    path = BASE_DIR / _arquivo_config.get()
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    check_interval: int = field(default_factory=lambda: _env_int("CHECK_INTERVAL", 60))
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///ofertas.db")
    )

    evolution_api_url: str = field(
        default_factory=lambda: os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
    )
    evolution_api_key: str = field(default_factory=lambda: os.getenv("EVOLUTION_API_KEY", ""))
    evolution_instance: str = field(default_factory=lambda: os.getenv("EVOLUTION_INSTANCE", ""))
    whatsapp_group_id: str = field(default_factory=lambda: os.getenv("WHATSAPP_GROUP_ID", ""))
    whatsapp_group_id_auto: str = field(
        default_factory=lambda: os.getenv("WHATSAPP_GROUP_ID_AUTO", "")
    )

    reenvio_queda_minima: float = field(
        default_factory=lambda: float(os.getenv("REENVIO_QUEDA_MINIMA", 15))
    )

    mercadolivre_app_id: str = field(
        default_factory=lambda: os.getenv("MERCADOLIVRE_APP_ID", "")
    )
    mercadolivre_app_secret: str = field(
        default_factory=lambda: os.getenv("MERCADOLIVRE_APP_SECRET", "")
    )
    lomadee_source_id: str = field(default_factory=lambda: os.getenv("LOMADEE_SOURCE_ID", ""))
    mercadolivre_affiliate_tag: str = field(
        default_factory=lambda: os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "")
    )
    mercadolivre_affiliate_cookie: str = field(
        default_factory=lambda: os.getenv("MERCADOLIVRE_AFFILIATE_COOKIE", "")
    )

    shopee_app_id: str = field(default_factory=lambda: os.getenv("SHOPEE_APP_ID", ""))
    shopee_app_secret: str = field(default_factory=lambda: os.getenv("SHOPEE_APP_SECRET", ""))

    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


settings = Settings()
