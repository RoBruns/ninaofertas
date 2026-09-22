"""Administracao de usuarios."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from api.schemas.user import UserCreate, UserResponse, UserUpdate
from api.security import hash_password
from core.models import User

router = APIRouter(prefix="/users", tags=["users"])
AdminUser = Annotated[User, Depends(require_role("admin"))]


def _public_dict(user: User) -> dict[str, object]:
    return UserResponse.model_validate(user).model_dump(mode="json")


@router.get("", response_model=PaginatedResponse[UserResponse])
def list_users(
    _admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    sort: str = "-created_at",
) -> PaginatedResponse[UserResponse]:
    pagination = PaginationParams(page=page, page_size=page_size, sort=sort)
    users, total = paginate(
        session,
        select(User),
        pagination,
        {"created_at": User.created_at, "email": User.email, "name": User.name},
    )
    return PaginatedResponse(
        items=[UserResponse.model_validate(user) for user in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_user(
    payload: UserCreate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> User:
    if session.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise APIError(409, "CONFLICT", "Email ja cadastrado")
    user = User(
        id=uuid4(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        role=payload.role,
        is_active=payload.is_active,
    )
    session.add(user)
    session.flush()
    record_audit(
        session,
        admin,
        "user",
        str(user.id),
        "create",
        None,
        _public_dict(user),
        client_ip(request),
    )
    session.commit()
    return user


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise APIError(404, "NOT_FOUND", "Usuario nao encontrado")
    changes = payload.model_dump(exclude_unset=True)
    if user.id == admin.id and (
        ("role" in changes and changes["role"] != admin.role)
        or changes.get("is_active") is False
    ):
        raise APIError(409, "CONFLICT", "Nao e permitido remover seu proprio acesso admin")
    if "email" in changes:
        existing_id = session.scalar(select(User.id).where(User.email == changes["email"]))
        if existing_id is not None and existing_id != user.id:
            raise APIError(409, "CONFLICT", "Email ja cadastrado")

    before = _public_dict(user)
    password = changes.pop("password", None)
    if password is not None:
        user.password_hash = hash_password(password)
    for field, value in changes.items():
        setattr(user, field, value)
    session.flush()
    record_audit(
        session,
        admin,
        "user",
        str(user.id),
        "update",
        before,
        _public_dict(user),
        client_ip(request),
    )
    session.commit()
    return user


@router.delete(
    "/{user_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_user(
    user_id: UUID,
    request: Request,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise APIError(404, "NOT_FOUND", "Usuario nao encontrado")
    if user.id == admin.id:
        raise APIError(409, "CONFLICT", "Nao e permitido remover o proprio usuario")
    before = _public_dict(user)
    # Remocao logica preserva a autoria dos audit_logs, cuja FK nao permite
    # apagar fisicamente um usuario que ja executou acoes.
    user.is_active = False
    record_audit(
        session,
        admin,
        "user",
        str(user.id),
        "delete",
        before,
        _public_dict(user),
        client_ip(request),
    )
    session.commit()
