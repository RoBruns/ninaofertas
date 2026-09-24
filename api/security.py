"""Hash de senhas e emissao/validacao de JWTs."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

ACCESS_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=7)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "ninaofertas-api"
JWT_AUDIENCE = "ninaofertas-dashboard"
REFRESH_COOKIE_NAME = "refresh_token"

_password_hasher = PasswordHasher(type=Type.ID)
_dummy_password_hash = _password_hasher.hash("senha-inexistente-para-equalizar-tempo")


class TokenError(ValueError):
    """Token ausente, invalido ou expirado."""


def validate_security_config() -> None:
    if not os.getenv("JWT_SECRET"):
        raise RuntimeError("JWT_SECRET e obrigatorio para iniciar a API")


def _jwt_secret() -> str:
    validate_security_config()
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def consume_dummy_password_check(password: str) -> None:
    """Reduz diferenca de tempo entre usuario ausente e senha incorreta."""
    verify_password(password, _dummy_password_hash)


def _encode_token(
    subject: str,
    token_type: Literal["access", "refresh"],
    ttl: timedelta,
    session_version: int,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "sv": session_version,
        "iat": now,
        "exp": now + ttl,
        "jti": str(uuid4()),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    *,
    session_version: int,
) -> str:
    return _encode_token(
        subject,
        "access",
        expires_delta or ACCESS_TOKEN_TTL,
        session_version,
    )


def create_refresh_token(
    subject: str,
    expires_delta: timedelta | None = None,
    *,
    session_version: int,
) -> str:
    return _encode_token(
        subject,
        "refresh",
        expires_delta or REFRESH_TOKEN_TTL,
        session_version,
    )


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={"require": ["sub", "type", "sv", "iat", "exp", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("token invalido ou expirado") from exc
    if payload.get("type") != expected_type:
        raise TokenError("tipo de token invalido")
    if type(payload.get("sv")) is not int or payload["sv"] < 0:
        raise TokenError("versao de sessao invalida")
    return payload
