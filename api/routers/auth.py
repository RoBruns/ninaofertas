"""Rotas de autenticacao."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import bearer_scheme, get_current_user, get_db
from api.errors import APIError
from api.ratelimit import client_ip, limit_login
from api.schemas.auth import AccessTokenResponse, LoginRequest, LoginResponse
from api.schemas.user import UserResponse
from api.security import (
    REFRESH_COOKIE_NAME,
    REFRESH_TOKEN_TTL,
    TokenError,
    consume_dummy_password_check,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from core.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/auth",
    )


def _token_identity(
    token: str,
    expected_type: Literal["access", "refresh"],
) -> tuple[UUID, int] | None:
    try:
        payload = decode_token(token, expected_type)
        return UUID(str(payload["sub"])), payload["sv"]
    except (TokenError, ValueError, KeyError):
        return None


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(limit_login)],
    responses={401: {"description": "Credenciais invalidas"}, 429: {"description": "Limite"}},
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    user = session.scalar(select(User).where(User.email == payload.email))
    valid = False
    if user is None:
        consume_dummy_password_check(payload.password)
    else:
        valid = verify_password(payload.password, user.password_hash)

    if not valid or user is None or not user.is_active:
        record_audit(
            session,
            user if user is not None else None,
            "auth",
            payload.email,
            "login_failed",
            None,
            {"email": payload.email},
            client_ip(request),
        )
        session.commit()
        raise APIError(401, "UNAUTHORIZED", "Email ou senha invalidos")

    user.last_login_at = datetime.now(timezone.utc)
    record_audit(
        session,
        user,
        "auth",
        str(user.id),
        "login",
        None,
        {"email": user.email},
        client_ip(request),
    )
    session.commit()
    access_token = create_access_token(str(user.id), session_version=user.session_version)
    refresh_token = create_refresh_token(str(user.id), session_version=user.session_version)
    _set_refresh_cookie(response, refresh_token)
    return LoginResponse(access_token=access_token, user=UserResponse.model_validate(user))


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(
    session: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> AccessTokenResponse:
    if refresh_token is None:
        raise APIError(401, "UNAUTHORIZED", "Refresh token ausente")
    identity = _token_identity(refresh_token, "refresh")
    if identity is None:
        raise APIError(401, "UNAUTHORIZED", "Refresh token invalido ou expirado") from None
    user_id, session_version = identity
    user = session.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active or session_version != user.session_version:
        raise APIError(401, "UNAUTHORIZED", "Refresh token invalido ou expirado")
    return AccessTokenResponse(
        access_token=create_access_token(
            str(user.id),
            session_version=user.session_version,
        )
    )


@router.post(
    "/logout",
    status_code=204,
)
def logout(
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    identities: list[tuple[UUID, int]] = []
    if credentials is not None and credentials.scheme.casefold() == "bearer":
        identity = _token_identity(credentials.credentials, "access")
        if identity is not None:
            identities.append(identity)
    if refresh_token is not None:
        identity = _token_identity(refresh_token, "refresh")
        if identity is not None and identity not in identities:
            identities.append(identity)

    for user_id, session_version in identities:
        result = session.execute(
            update(User)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                User.session_version == session_version,
            )
            .values(session_version=User.session_version + 1)
        )
        if result.rowcount:
            session.commit()
            break

    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path="/api/auth",
        secure=True,
        httponly=True,
        samesite="strict",
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
