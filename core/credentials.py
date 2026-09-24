"""Persistencia cifrada de credenciais de plataforma para uso interno."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.crypto import decrypt, encrypt, fingerprint
from core import db
from core.models import Event, Platform, PlatformAccount, PlatformCredential


def normalize_cookie(value: str) -> str:
    """Aceita o cookie como texto (`a=1; b=2`) ou o JSON exportado pelo navegador.

    Extensões como Cookie-Editor exportam `[{"name": ..., "value": ...}, ...]`;
    as plataformas esperam o cabeçalho `Cookie`, então o JSON vira `nome=valor; ...`.
    """
    text = value.strip()
    if not text.startswith("["):
        return text
    try:
        items = json.loads(text)
    except ValueError as exc:
        raise ValueError("JSON de cookies inválido") from exc
    pairs: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("name") and item.get("value") is not None:
            pairs.setdefault(str(item["name"]), str(item["value"]))
    if not pairs:
        raise ValueError("JSON de cookies sem nenhum par name/value")
    return "; ".join(f"{name}={cookie}" for name, cookie in pairs.items())


def store_credential(
    session: Session,
    account_id: UUID,
    kind: str,
    value: str,
) -> tuple[PlatformCredential, str | None]:
    """Cria ou substitui uma credencial e devolve apenas fingerprints auditaveis."""
    credential = session.scalar(
        select(PlatformCredential).where(
            PlatformCredential.account_id == account_id,
            PlatformCredential.kind == kind,
        )
    )
    previous_fingerprint = credential.fingerprint if credential is not None else None
    now = datetime.now(timezone.utc)
    if credential is None:
        credential = PlatformCredential(account_id=account_id, kind=kind)
        session.add(credential)
    credential.ciphertext = encrypt(value)
    credential.fingerprint = fingerprint(value)
    credential.key_version = 1
    credential.status = "unknown"
    credential.last_rotated_at = now
    credential.last_error = None
    credential.last_error_at = None
    session.flush()
    return credential, previous_fingerprint


def read_credential(
    session: Session,
    credential: PlatformCredential,
    *,
    touch: bool = True,
) -> str:
    """Decifra uma credencial para consumo interno; seu valor nunca deve ser serializado."""
    value = decrypt(credential.ciphertext)
    if touch:
        credential.last_used_at = datetime.now(timezone.utc)
    return value


def read_account_credentials(
    session: Session,
    account_id: UUID,
) -> tuple[dict[str, str], list[PlatformCredential]]:
    """Carrega todas as credenciais de uma conta para clientes que usam pares de chaves."""
    credentials = list(
        session.scalars(
            select(PlatformCredential).where(PlatformCredential.account_id == account_id)
        )
    )
    return (
        {credential.kind: read_credential(session, credential) for credential in credentials},
        credentials,
    )


def runtime_account_credentials(
    account_ids: tuple[UUID, ...], platform_slug: str
) -> tuple[UUID, dict, dict[str, str]] | None:
    """Resolve config e segredos da primeira conta ativa da plataforma."""
    if not account_ids:
        return None
    with db.get_session() as session:
        account = session.scalar(
            select(PlatformAccount)
            .join(Platform, Platform.id == PlatformAccount.platform_id)
            .where(
                PlatformAccount.id.in_(account_ids),
                PlatformAccount.status == "active",
                Platform.slug == platform_slug,
            )
            .order_by(PlatformAccount.created_at)
        )
        if account is None:
            return None
        values, _ = read_account_credentials(session, account.id)
        config = dict(account.config or {})
        if account.external_id:
            config.setdefault("external_id", account.external_id)
        return account.id, config, values


def mark_account_credentials_invalid(
    account_id: UUID, error: str, *, bot_id: UUID | None = None
) -> None:
    """Marca segredos rejeitados e emite auth_expired, sempre best-effort."""
    try:
        with db.get_session() as session:
            now = datetime.now(timezone.utc)
            credentials = list(
                session.scalars(
                    select(PlatformCredential).where(
                        PlatformCredential.account_id == account_id
                    )
                )
            )
            for credential in credentials:
                credential.status = "invalid"
                credential.last_error = error[:1000]
                credential.last_error_at = now
            session.add(
                Event(
                    bot_id=bot_id,
                    entity_type="platform_account",
                    entity_id=str(account_id),
                    level="error",
                    type="auth_expired",
                    message="Credencial de plataforma rejeitada",
                    detail={"status": "invalid"},
                )
            )
    except Exception:
        return


def platforms_with_usable_credentials(account_ids: tuple[UUID, ...]) -> set[str]:
    """Slugs das plataformas em que o bot tem conta ativa com credencial não invalidada.

    O worker só publica ofertas dessas plataformas: sem conta, o link sairia
    sem comissão (ADR-020).
    """
    if not account_ids:
        return set()
    with db.get_session() as session:
        return set(
            session.scalars(
                select(Platform.slug)
                .join(PlatformAccount, PlatformAccount.platform_id == Platform.id)
                .join(PlatformCredential, PlatformCredential.account_id == PlatformAccount.id)
                .where(
                    PlatformAccount.id.in_(account_ids),
                    PlatformAccount.status == "active",
                    PlatformCredential.status != "invalid",
                )
                .distinct()
            )
        )
