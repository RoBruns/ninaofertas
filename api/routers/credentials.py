"""Gestao write-only e validacao de credenciais de plataforma."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.routers.accounts import credential_status, get_owned_account
from api.schemas.credential import CredentialStatus, CredentialTestResponse, CredentialWrite
from core.credentials import normalize_cookie, read_account_credentials, store_credential
from core.models import Platform, PlatformCredential, User
from core.platforms.registry import (
    PlatformConfigurationError,
    PlatformNotIntegratedError,
    resolve,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/accounts", tags=["credentials"])
AdminUser = Annotated[User, Depends(require_role("admin"))]
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]
KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def _validate_kind(kind: str) -> str:
    if not KIND_PATTERN.fullmatch(kind):
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "Tipo de credencial invalido",
            {"kind": "use letras minusculas, numeros e underscore"},
        )
    return kind


def _get_credential(
    session: Session,
    account_id: UUID,
    kind: str,
) -> PlatformCredential:
    credential = session.scalar(
        select(PlatformCredential).where(
            PlatformCredential.account_id == account_id,
            PlatformCredential.kind == kind,
        )
    )
    if credential is None:
        raise APIError(404, "NOT_FOUND", "Credencial nao encontrada")
    return credential


def _audit_metadata(credential: PlatformCredential) -> dict[str, object]:
    return {
        "kind": credential.kind,
        "fingerprint": credential.fingerprint,
        "status": credential.status,
        "last_rotated_at": credential.last_rotated_at.isoformat()
        if credential.last_rotated_at
        else None,
        "last_used_at": credential.last_used_at.isoformat() if credential.last_used_at else None,
        "last_success_at": credential.last_success_at.isoformat()
        if credential.last_success_at
        else None,
        "last_error": credential.last_error,
        "last_error_at": credential.last_error_at.isoformat()
        if credential.last_error_at
        else None,
    }


@router.get("/{account_id}/credentials", response_model=list[CredentialStatus])
def list_credentials(
    account_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[CredentialStatus]:
    account = get_owned_account(session, account_id, current_user.id)
    return [
        credential_status(credential)
        for credential in session.scalars(
            select(PlatformCredential)
            .where(PlatformCredential.account_id == account.id)
            .order_by(PlatformCredential.kind.asc())
        )
    ]


@router.put(
    "/{account_id}/credentials/{kind}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def put_credential(
    account_id: UUID,
    kind: str,
    payload: CredentialWrite,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    kind = _validate_kind(kind)
    account = get_owned_account(session, account_id, admin.id)
    value = payload.value
    if kind == "cookie":
        try:
            value = normalize_cookie(value)
        except ValueError as exc:
            raise APIError(422, "VALIDATION_ERROR", str(exc), {"value": str(exc)}) from None
    credential, previous_fingerprint = store_credential(session, account.id, kind, value)
    record_audit(
        session,
        admin,
        "platform_credential",
        str(credential.id),
        "update" if previous_fingerprint is not None else "create",
        {"kind": kind, "fingerprint": previous_fingerprint}
        if previous_fingerprint is not None
        else None,
        {"kind": kind, "fingerprint": credential.fingerprint, "changed": True},
        client_ip(request),
    )
    session.commit()


@router.delete(
    "/{account_id}/credentials/{kind}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_credential(
    account_id: UUID,
    kind: str,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    kind = _validate_kind(kind)
    account = get_owned_account(session, account_id, admin.id)
    credential = _get_credential(session, account.id, kind)
    before = {"kind": credential.kind, "fingerprint": credential.fingerprint}
    credential_id = credential.id
    session.delete(credential)
    record_audit(
        session,
        admin,
        "platform_credential",
        str(credential_id),
        "delete",
        before,
        None,
        client_ip(request),
    )
    session.commit()


@router.post(
    "/{account_id}/credentials/{kind}/test",
    response_model=CredentialTestResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def test_credential(
    account_id: UUID,
    kind: str,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> CredentialTestResponse:
    kind = _validate_kind(kind)
    account = get_owned_account(session, account_id, user.id)
    target = _get_credential(session, account.id, kind)
    platform = session.get(Platform, account.platform_id)
    if platform is None:
        raise APIError(500, "INTERNAL", "Plataforma da conta nao encontrada")
    try:
        platform_client = resolve(platform.slug)
    except PlatformNotIntegratedError as exc:
        raise APIError(501, "NOT_IMPLEMENTED", str(exc)) from None

    before = _audit_metadata(target)
    checked_at = datetime.now(timezone.utc)
    credentials, _loaded = read_account_credentials(session, account.id)
    try:
        result = platform_client.test_credentials(credentials, account.config)
    except PlatformConfigurationError as exc:
        result_message = str(exc)
        ok = False
        new_status = "unknown"
    except Exception as exc:
        # Um valor malformado não pode virar 500; a mensagem não repete o segredo.
        logger.warning(f"Teste de credencial falhou: tipo={type(exc).__name__}")
        result_message = f"Nao foi possivel testar a credencial ({type(exc).__name__}); cadastre-a de novo"
        ok = False
        new_status = "unknown"
    else:
        result_message = result.message
        ok = result.ok
        if result.ok:
            new_status = "valid"
        elif result.invalid:
            new_status = "invalid"
        else:
            new_status = "unknown"

    target.status = new_status
    if ok:
        target.last_success_at = checked_at
        target.last_error = None
        target.last_error_at = None
    else:
        target.last_error = result_message
        target.last_error_at = checked_at
    session.flush()
    record_audit(
        session,
        user,
        "platform_credential",
        str(target.id),
        "test",
        before,
        _audit_metadata(target),
        client_ip(request),
    )
    session.commit()
    return CredentialTestResponse(ok=ok, checked_at=checked_at, message=result_message)
