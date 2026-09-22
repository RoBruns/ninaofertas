"""Consulta paginada do historico de auditoria."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db, require_role
from api.schemas.audit import AuditLogResponse
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
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
    statement = select(AuditLog)
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
    entries, total = paginate(
        session,
        statement,
        pagination,
        {"created_at": AuditLog.created_at, "id": AuditLog.id},
    )
    return PaginatedResponse(
        items=[AuditLogResponse.model_validate(entry) for entry in entries],
        total=total,
        page=page,
        page_size=page_size,
    )
