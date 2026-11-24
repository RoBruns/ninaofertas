"""Configura o webhook MESSAGES_UPSERT no telefone de escuta da plataforma."""

from __future__ import annotations

import os

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.evolution import EvolutionClient, EvolutionUnavailable
from core.models import Phone


def public_api_base_url() -> str:
    return (os.getenv("PUBLIC_API_BASE_URL") or "").rstrip("/")


def webhook_secret() -> str:
    return (os.getenv("EVOLUTION_WEBHOOK_SECRET") or "").strip()


def webhook_url() -> str | None:
    base = public_api_base_url()
    secret = webhook_secret()
    if not base or not secret:
        return None
    return f"{base}/webhooks/evolution?token={secret}"


def platform_listen_phone(session: Session) -> Phone | None:
    return session.scalar(select(Phone).where(Phone.is_platform_listen.is_(True)))


def ensure_platform_listen_webhook(session: Session) -> str:
    """Aplica webhook na Nina 1 (único phone com is_platform_listen)."""
    url = webhook_url()
    if not url:
        return "faltam PUBLIC_API_BASE_URL ou EVOLUTION_WEBHOOK_SECRET"
    phone = platform_listen_phone(session)
    if phone is None:
        return "nenhum telefone com is_platform_listen"
    if not phone.evolution_instance:
        return "telefone de plataforma sem instância Evolution"
    try:
        EvolutionClient().set_webhook(phone.evolution_instance, url)
    except EvolutionUnavailable as exc:
        logger.warning(f"Webhook Evolution falhou ({phone.evolution_instance}): {exc}")
        return f"falha Evolution: {exc}"
    return f"webhook ok em {phone.evolution_instance}"
