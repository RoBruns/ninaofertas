"""Schemas e helpers compartilhados."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    sort: str = "-created_at"


def paginate(
    session: Session,
    statement: Select[Any],
    pagination: PaginationParams,
    sort_columns: dict[str, Any],
) -> tuple[list[Any], int]:
    """Executa uma listagem paginada com ordenacao em allowlist."""
    descending = pagination.sort.startswith("-")
    sort_name = pagination.sort.removeprefix("-")
    sort_column = sort_columns.get(sort_name)
    if sort_column is None:
        from api.errors import APIError

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
    items = list(
        session.scalars(statement.order_by(ordering).offset(offset).limit(pagination.page_size))
    )
    return items, total
