"""CRUD e importacao atomica de despesas."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from api.schemas.expense import (
    ExpenseCategoryCreate,
    ExpenseCategoryResponse,
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
    ImportResult,
)
from core.models import Bot, Campaign, Expense, ExpenseCategory, Niche, Platform, User

router = APIRouter(tags=["expenses"])
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]


def _owned(session: Session, expense_id: UUID, owner_id: UUID) -> Expense:
    expense = session.scalar(
        select(Expense).where(Expense.id == expense_id, Expense.owner_id == owner_id)
    )
    if expense is None:
        raise APIError(404, "NOT_FOUND", "Despesa nao encontrada")
    return expense


def _response(expense: Expense) -> ExpenseResponse:
    return ExpenseResponse.model_validate(expense, from_attributes=True)


def _validate_refs(session: Session, owner_id: UUID, values: dict[str, object]) -> None:
    owned_refs = (
        ("category_id", ExpenseCategory, "Categoria de despesa"),
        ("campaign_id", Campaign, "Campanha"),
        ("bot_id", Bot, "Bot"),
        ("niche_id", Niche, "Nicho"),
    )
    for field, model, label in owned_refs:
        value = values.get(field)
        if (
            value is not None
            and session.scalar(
                select(model.id).where(model.id == value, model.owner_id == owner_id)
            )
            is None
        ):
            raise APIError(404, "NOT_FOUND", f"{label} nao encontrado")
    platform_id = values.get("platform_id")
    if platform_id is not None and session.get(Platform, platform_id) is None:
        raise APIError(404, "NOT_FOUND", "Plataforma nao encontrada")


@router.get("/expenses", response_model=PaginatedResponse[ExpenseResponse])
def list_expenses(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    category_id: int | None = None,
    campaign_id: UUID | None = None,
    bot_id: UUID | None = None,
    platform_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    sort: str = "-created_at",
) -> PaginatedResponse[ExpenseResponse]:
    statement = select(Expense).where(Expense.owner_id == user.id)
    filters = (
        (from_date, Expense.incurred_on >= from_date if from_date else None),
        (to_date, Expense.incurred_on <= to_date if to_date else None),
        (category_id, Expense.category_id == category_id),
        (campaign_id, Expense.campaign_id == campaign_id),
        (bot_id, Expense.bot_id == bot_id),
        (platform_id, Expense.platform_id == platform_id),
    )
    for value, condition in filters:
        if value is not None:
            statement = statement.where(condition)
    items, total = paginate(
        session,
        statement,
        PaginationParams(page=page, page_size=page_size, sort=sort),
        {
            "created_at": Expense.created_at,
            "incurred_on": Expense.incurred_on,
            "amount": Expense.amount,
            "description": Expense.description,
        },
    )
    return PaginatedResponse(
        items=[_response(item) for item in items], total=total, page=page, page_size=page_size
    )


@router.post(
    "/expenses",
    response_model=ExpenseResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_expense(
    payload: ExpenseCreate,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> ExpenseResponse:
    values = payload.model_dump()
    _validate_refs(session, user.id, values)
    expense = Expense(id=uuid4(), owner_id=user.id, created_by=user.id, source="manual", **values)
    session.add(expense)
    session.flush()
    response = _response(expense)
    record_audit(
        session,
        user,
        "expense",
        str(expense.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.patch(
    "/expenses/{expense_id}",
    response_model=ExpenseResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_expense(
    expense_id: UUID,
    payload: ExpenseUpdate,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> ExpenseResponse:
    expense = _owned(session, expense_id, user.id)
    before = _response(expense).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    required = {"description", "amount", "incurred_on", "currency"}
    if any(changes.get(field, "valid") is None for field in required):
        raise APIError(422, "VALIDATION_ERROR", "Campos obrigatorios nao aceitam null")
    _validate_refs(session, user.id, changes)
    for field, value in changes.items():
        setattr(expense, field, value)
    session.flush()
    response = _response(expense)
    record_audit(
        session,
        user,
        "expense",
        str(expense.id),
        "update",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/expenses/{expense_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_expense(
    expense_id: UUID,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    expense = _owned(session, expense_id, user.id)
    before = _response(expense).model_dump(mode="json")
    session.delete(expense)
    record_audit(
        session, user, "expense", str(expense.id), "delete", before, None, client_ip(request)
    )
    session.commit()


@router.get("/expense-categories", response_model=list[ExpenseCategoryResponse])
def list_categories(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[ExpenseCategoryResponse]:
    return [
        ExpenseCategoryResponse.model_validate(item, from_attributes=True)
        for item in session.scalars(
            select(ExpenseCategory)
            .where(ExpenseCategory.owner_id == user.id)
            .order_by(ExpenseCategory.name.asc())
        )
    ]


@router.post(
    "/expense-categories",
    response_model=ExpenseCategoryResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_category(
    payload: ExpenseCategoryCreate,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> ExpenseCategoryResponse:
    duplicate = session.scalar(
        select(ExpenseCategory.id).where(
            ExpenseCategory.owner_id == user.id, ExpenseCategory.slug == payload.slug
        )
    )
    if duplicate is not None:
        raise APIError(409, "CONFLICT", "Ja existe uma categoria com este slug")
    category = ExpenseCategory(owner_id=user.id, **payload.model_dump())
    session.add(category)
    session.flush()
    response = ExpenseCategoryResponse.model_validate(category, from_attributes=True)
    record_audit(
        session,
        user,
        "expense_category",
        str(category.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


def _expense_csv(content: bytes) -> list[tuple[int, ExpenseCreate, str | None]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise APIError(422, "VALIDATION_ERROR", "CSV invalido", {"line_1": "use UTF-8"}) from None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    aliases = {
        "descricao": "description",
        "valor": "amount",
        "data": "incurred_on",
        "categoria": "category_id",
        "plataforma": "platform_id",
        "campanha": "campaign_id",
        "bot": "bot_id",
        "nicho": "niche_id",
        "observacoes": "notes",
    }
    rows: list[tuple[int, ExpenseCreate, str | None]] = []
    errors: dict[str, str] = {}
    for line, raw in enumerate(reader, start=2):
        values = {
            aliases.get(str(key).strip().casefold(), str(key).strip()): value
            for key, value in raw.items()
            if key
        }
        for field in ("category_id", "platform_id", "campaign_id", "bot_id", "niche_id"):
            if values.get(field) == "":
                values[field] = None
        external_id = str(values.pop("external_id", "") or "").strip() or None
        try:
            rows.append((line, ExpenseCreate.model_validate(values), external_id))
        except ValidationError as exc:
            errors[f"line_{line}"] = "; ".join(error["msg"] for error in exc.errors())
    if errors:
        raise APIError(422, "VALIDATION_ERROR", "CSV invalido; nenhuma linha foi importada", errors)
    if not rows:
        raise APIError(422, "VALIDATION_ERROR", "CSV nao contem despesas", {"line_1": "sem dados"})
    return rows


@router.post(
    "/expenses/import",
    response_model=ImportResult,
    dependencies=[Depends(limit_authenticated_write)],
)
def import_expenses(
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> ImportResult:
    rows = _expense_csv(file.file.read())
    for line, payload, _external_id in rows:
        try:
            _validate_refs(session, user.id, payload.model_dump())
        except APIError as exc:
            raise APIError(
                422,
                "VALIDATION_ERROR",
                "CSV invalido; nenhuma linha foi importada",
                {f"line_{line}": exc.message},
            ) from None
    imported = skipped = 0
    for _line, payload, external_id in rows:
        if external_id and session.scalar(
            select(Expense.id).where(
                Expense.source == "csv_import", Expense.external_id == external_id
            )
        ):
            skipped += 1
            continue
        session.add(
            Expense(
                id=uuid4(),
                owner_id=user.id,
                created_by=user.id,
                source="csv_import",
                external_id=external_id,
                **payload.model_dump(),
            )
        )
        imported += 1
    result = ImportResult(imported=imported, skipped=skipped, errors=[])
    record_audit(
        session,
        user,
        "expense_import",
        str(uuid4()),
        "import",
        None,
        {**result.model_dump(), "file_name": file.filename or ""},
        client_ip(request),
    )
    session.commit()
    return result
