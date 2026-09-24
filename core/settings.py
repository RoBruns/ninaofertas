"""Carrega variáveis de ambiente (.env).

Só infraestrutura: banco, Evolution API, intervalo e log. Bots, grupos,
telefones e credenciais de plataforma vêm do dashboard (ADR-020).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


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

    reenvio_queda_minima: float = field(
        default_factory=lambda: float(os.getenv("REENVIO_QUEDA_MINIMA", 15))
    )

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


settings = Settings()
