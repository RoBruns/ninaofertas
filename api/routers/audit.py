"""Consulta paginada do historico de auditoria."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db, require_role
from api.errors import APIError
from api.schemas.audit import AuditLogResponse
from api.schemas.common import PaginatedResponse, PaginationParams
from core.models import AuditLog, User

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=PaginatedResponse[AuditLogResponse])
def list_audit_logs(
    _admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[Session, Depends(get_db)],
    entity_type: str | None = None,
    entity_id: str | None = None,
    user_id: UUID | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    sort: str = "-created_at",
) -> PaginatedResponse[AuditLogResponse]:
    statement = (
        select(AuditLog, User.email.label("user_email"), User.name.label("user_name"))
        .outerjoin(User, AuditLog.user_id == User.id)
    )
    if entity_type is not None:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditLog.entity_id == entity_id)
    if user_id is not None:
        statement = statement.where(AuditLog.user_id == user_id)
    if from_ is not None:
        statement = statement.where(AuditLog.created_at >= from_)
    if to is not None:
        statement = statement.where(AuditLog.created_at <= to)

    pagination = PaginationParams(page=page, page_size=page_size, sort=sort)
    sort_columns = {"created_at": AuditLog.created_at, "id": AuditLog.id}
    descending = pagination.sort.startswith("-")
    sort_name = pagination.sort.removeprefix("-")
    sort_column = sort_columns.get(sort_name)
    if sort_column is None:
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "Parametros invalidos",
            {"sort": "campo de ordenacao invalido"},
        )

    count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total = int(session.scalar(count_statement) or 0)
    ordering = sort_column.desc() if descending else sort_column.asc()
    offset = (pagination.page - 1) * pagination.page_size
    rows = session.execute(
        statement.order_by(ordering).offset(offset).limit(pagination.page_size)
    ).all()
    items = [
        AuditLogResponse(
            id=entry.id,
            user_id=entry.user_id,
            user_email=user_email,
            user_name=user_name,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            action=entry.action,
            before=entry.before,
            after=entry.after,
            ip=entry.ip,
            created_at=entry.created_at,
        )
        for entry, user_email, user_name in rows
    ]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
