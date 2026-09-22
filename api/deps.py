"""Dependencies de banco, autenticacao e autorizacao."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from api.errors import APIError
from api.security import TokenError, decode_token
from core.models import User
from core.settings import settings


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


_database_url = _normalize_database_url(settings.database_url)
_connect_args = {"check_same_thread": False} if _database_url.startswith("sqlite") else {}
engine = create_engine(_database_url, future=True, pool_pre_ping=True, connect_args=_connect_args)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionFactory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise APIError(401, "UNAUTHORIZED", "Autenticacao necessaria")
    try:
        payload = decode_token(credentials.credentials, "access")
        user_id = UUID(str(payload["sub"]))
    except (TokenError, ValueError, KeyError):
        raise APIError(401, "UNAUTHORIZED", "Token invalido ou expirado") from None
    user = session.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise APIError(401, "UNAUTHORIZED", "Token invalido ou expirado")
    return user


ROLE_LEVEL = {"viewer": 0, "operator": 1, "admin": 2}


def require_role(*roles: str) -> Callable[[User], User]:
    if not roles:
        raise ValueError("informe ao menos um papel")
    unknown = set(roles) - ROLE_LEVEL.keys()
    if unknown:
        raise ValueError("papel desconhecido")

    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in roles:
            raise APIError(403, "FORBIDDEN", "Permissao insuficiente")
        return current_user

    return dependency


def require_minimum_role(minimum_role: str) -> Callable[[User], User]:
    minimum = ROLE_LEVEL[minimum_role]

    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if ROLE_LEVEL.get(current_user.role, -1) < minimum:
            raise APIError(403, "FORBIDDEN", "Permissao insuficiente")
        return current_user

    return dependency


def limit_authenticated_write(
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    from api.ratelimit import limiter

    if not limiter.hit("write", str(current_user.id), 60, 60):
        raise APIError(429, "RATE_LIMITED", "Limite de escrita excedido")
