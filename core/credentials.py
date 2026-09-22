"""Persistencia cifrada de credenciais de plataforma para uso interno."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.crypto import decrypt, encrypt, fingerprint
from core.models import PlatformCredential


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
