"""Listagem, importacao idempotente e sincronizacao de vendas."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from api.schemas.sale import (
    SaleResponse,
    SaleStatus,
    SalesImportHistory,
    SalesImportResult,
    SalesSyncRequest,
    SalesSyncResponse,
)
from core.importers import IMPORTERS, ImportValidationError, SaleImportRow
from core.models import (
    AuditLog,
    Bot,
    Command,
    Group,
    Platform,
    PlatformAccount,
    Sale,
    User,
)

router = APIRouter(prefix="/sales", tags=["sales"])
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]
REVENUE_STATUSES = ("confirmed", "paid")


def recognized_revenue_statement(owner_id: UUID) -> Select[Any]:
    """Consulta canonica: vendas canceladas/pendentes nunca viram receita."""
    return select(func.coalesce(func.sum(Sale.commission), 0)).where(
        Sale.owner_id == owner_id, Sale.status.in_(REVENUE_STATUSES)
    )


def _response(sale: Sale) -> SaleResponse:
    return SaleResponse.model_validate(sale, from_attributes=True)


@router.get("", response_model=PaginatedResponse[SaleResponse])
def list_sales(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    platform_id: int | None = None,
    bot_id: UUID | None = None,
    status: SaleStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: str = "-ordered_at",
) -> PaginatedResponse[SaleResponse]:
    statement = select(Sale).where(Sale.owner_id == user.id)
    if from_date is not None:
        statement = statement.where(
            Sale.ordered_at >= datetime.combine(from_date, time.min, timezone.utc)
        )
    if to_date is not None:
        statement = statement.where(
            Sale.ordered_at < datetime.combine(to_date + timedelta(days=1), time.min, timezone.utc)
        )
    if platform_id is not None:
        statement = statement.where(Sale.platform_id == platform_id)
    if bot_id is not None:
        statement = statement.where(Sale.bot_id == bot_id)
    if status is not None:
        statement = statement.where(Sale.status == status)
    items, total = paginate(
        session,
        statement,
        PaginationParams(page=page, page_size=page_size, sort=sort),
        {
            "ordered_at": Sale.ordered_at,
            "imported_at": Sale.imported_at,
            "gross_amount": Sale.gross_amount,
            "commission": Sale.commission,
            "status": Sale.status,
        },
    )
    return PaginatedResponse(
        items=[_response(item) for item in items], total=total, page=page, page_size=page_size
    )


def _validate_row_refs(session: Session, owner_id: UUID, rows: list[SaleImportRow]) -> None:
    errors: dict[str, str] = {}
    for row in rows:
        if (
            row.bot_id is not None
            and session.scalar(select(Bot.id).where(Bot.id == row.bot_id, Bot.owner_id == owner_id))
            is None
        ):
            errors[f"line_{row.line}"] = "bot_id nao pertence ao usuario"
        if (
            row.group_id is not None
            and session.scalar(
                select(Group.id).where(Group.id == row.group_id, Group.owner_id == owner_id)
            )
            is None
        ):
            errors[f"line_{row.line}"] = "group_id nao pertence ao usuario"
    if errors:
        raise APIError(422, "VALIDATION_ERROR", "CSV invalido; nenhuma linha foi importada", errors)


def _sale_values(row: SaleImportRow, owner_id: UUID, platform_id: int) -> dict[str, object]:
    return {
        "owner_id": owner_id,
        "platform_id": platform_id,
        "external_id": row.external_id,
        "sub_id": row.sub_id,
        "bot_id": row.bot_id,
        "group_id": row.group_id,
        "product_name": row.product_name,
        "quantity": row.quantity,
        "gross_amount": row.gross_amount,
        "commission": row.commission,
        "commission_rate": row.commission_rate,
        "status": row.status,
        "buyer_hash": row.buyer_hash,
        "ordered_at": row.ordered_at,
        "confirmed_at": row.confirmed_at,
        "source": "csv_import",
        "raw": row.raw,
    }


def _same_sale(sale: Sale, values: dict[str, object]) -> bool:
    fields = (
        "sub_id",
        "bot_id",
        "group_id",
        "product_name",
        "quantity",
        "gross_amount",
        "commission",
        "commission_rate",
        "status",
        "buyer_hash",
        "ordered_at",
        "confirmed_at",
        "raw",
    )
    return all(getattr(sale, field) == values[field] for field in fields)


@router.post(
    "/import",
    response_model=SalesImportResult,
    dependencies=[Depends(limit_authenticated_write)],
)
def import_sales(
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
    platform_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
) -> SalesImportResult:
    platform = session.get(Platform, platform_id)
    if platform is None:
        raise APIError(404, "NOT_FOUND", "Plataforma nao encontrada")
    importer = IMPORTERS.get(platform.slug)
    if importer is None:
        raise APIError(
            422,
            "VALIDATION_ERROR",
            f"Importacao CSV de {platform.name} ainda nao possui mapeamento",
        )
    try:
        rows = importer.parse(file.file.read())
    except ImportValidationError as exc:
        fields = {f"line_{error.line}": error.message for error in exc.errors}
        raise APIError(
            422, "VALIDATION_ERROR", "CSV invalido; nenhuma linha foi importada", fields
        ) from None
    _validate_row_refs(session, user.id, rows)

    imported = skipped = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        values = _sale_values(row, user.id, platform.id)
        sale = session.scalar(
            select(Sale).where(Sale.platform_id == platform.id, Sale.external_id == row.external_id)
        )
        if sale is not None and sale.owner_id != user.id:
            raise APIError(409, "CONFLICT", "Venda ja pertence a outro usuario")
        if sale is None:
            session.add(Sale(id=uuid4(), imported_at=now, **values))
            imported += 1
        elif _same_sale(sale, values):
            skipped += 1
        else:
            for field, value in values.items():
                setattr(sale, field, value)
            sale.imported_at = now
            imported += 1

    result = SalesImportResult(imported=imported, skipped=skipped, errors=[])
    record_audit(
        session,
        user,
        "sale_import",
        str(uuid4()),
        "import",
        None,
        {
            **result.model_dump(),
            "platform_id": platform.id,
            "file_name": file.filename or "",
        },
        client_ip(request),
    )
    session.commit()
    return result


@router.get("/imports", response_model=list[SalesImportHistory])
def list_imports(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[SalesImportHistory]:
    entries = session.scalars(
        select(AuditLog)
        .where(AuditLog.user_id == user.id, AuditLog.entity_type == "sale_import")
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    )
    result: list[SalesImportHistory] = []
    for entry in entries:
        detail = entry.after or {}
        result.append(
            SalesImportHistory(
                id=entry.id,
                platform_id=int(detail["platform_id"]),
                file_name=str(detail.get("file_name") or ""),
                imported=int(detail.get("imported") or 0),
                skipped=int(detail.get("skipped") or 0),
                created_at=entry.created_at,
            )
        )
    return result


@router.post(
    "/sync",
    response_model=SalesSyncResponse,
    status_code=202,
    dependencies=[Depends(limit_authenticated_write)],
)
def sync_sales(
    payload: SalesSyncRequest,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> SalesSyncResponse:
    account = session.scalar(
        select(PlatformAccount).where(
            PlatformAccount.id == payload.account_id, PlatformAccount.owner_id == user.id
        )
    )
    if account is None:
        raise APIError(404, "NOT_FOUND", "Conta de plataforma nao encontrada")
    platform = session.get(Platform, account.platform_id)
    if platform is None:
        raise APIError(500, "INTERNAL", "Plataforma da conta nao encontrada")
    can_sync = bool(
        platform.capabilities.get("commission_api")
        or platform.capabilities.get("commission_scrape")
    )
    if not can_sync:
        raise APIError(
            501,
            "NOT_IMPLEMENTED",
            f"{platform.name} nao oferece sincronizacao de comissoes por API; use a importacao CSV",
        )
    command = Command(
        bot_id=None,
        type="commission_import",
        payload={"account_id": str(account.id)},
        status="pending",
        requested_by=user.id,
    )
    session.add(command)
    session.flush()
    record_audit(
        session,
        user,
        "sale_sync",
        str(command.id),
        "enqueue",
        None,
        {"account_id": str(account.id), "platform_id": platform.id},
        client_ip(request),
    )
    session.commit()
    return SalesSyncResponse(command_id=command.id)
