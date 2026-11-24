"""Configura o webhook MESSAGES_UPSERT no telefone de escuta da plataforma."""

from __future__ import annotations

import os

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.evolution import EvolutionClient, EvolutionUnavailable
from core.models import Phone

# Rótulo fixo da capturadora da plataforma (ADR-036). Não é configurável na API.
PLATFORM_LISTEN_LABEL = "Nina 1"


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


def label_is_platform_listen(label: str | None) -> bool:
    return (label or "").strip().casefold() == PLATFORM_LISTEN_LABEL.casefold()


def sync_platform_listen_flags(session: Session) -> Phone | None:
    """Garante que só o telefone 'Nina 1' tem is_platform_listen.

    A escuta é chumbada pelo rótulo — não há toggle na API/dashboard.
    """
    phones = list(session.scalars(select(Phone).order_by(Phone.created_at)))
    candidatos = [phone for phone in phones if label_is_platform_listen(phone.label)]
    if len(candidatos) > 1:
        logger.warning(
            f"Há {len(candidatos)} telefones com rótulo '{PLATFORM_LISTEN_LABEL}'; "
            "usando o mais antigo como escuta da plataforma"
        )
    chosen = candidatos[0] if candidatos else None
    for phone in phones:
        want = chosen is not None and phone.id == chosen.id
        if phone.is_platform_listen != want:
            phone.is_platform_listen = want
    if chosen is not None:
        session.flush()
    return chosen


def platform_listen_phone(session: Session) -> Phone | None:
    return sync_platform_listen_flags(session)


def ensure_platform_listen_webhook(session: Session) -> str:
    """Aplica webhook na Nina 1 (rótulo fixo da plataforma)."""
    url = webhook_url()
    if not url:
        return "faltam PUBLIC_API_BASE_URL ou EVOLUTION_WEBHOOK_SECRET"
    phone = platform_listen_phone(session)
    if phone is None:
        return f"nenhum telefone com rótulo '{PLATFORM_LISTEN_LABEL}'"
    if not phone.evolution_instance:
        return "telefone de plataforma sem instância Evolution"
    try:
        EvolutionClient().set_webhook(phone.evolution_instance, url)
    except EvolutionUnavailable as exc:
        logger.warning(f"Webhook Evolution falhou ({phone.evolution_instance}): {exc}")
        return f"falha Evolution: {exc}"
    return f"webhook ok em {phone.evolution_instance}"
