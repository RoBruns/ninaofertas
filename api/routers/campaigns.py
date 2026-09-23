"""CRUD e metricas de campanhas."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write, require_role
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.campaign import (
    CampaignCreate,
    CampaignMetrics,
    CampaignResponse,
    CampaignUpdate,
)
from api.schemas.common import PaginatedResponse, PaginationParams, paginate
from core.models import Bot, Campaign, Expense, GroupJoin, Niche, User

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
OperatorUser = Annotated[User, Depends(require_role("operator", "admin"))]


def _owned(session: Session, campaign_id: UUID, owner_id: UUID) -> Campaign:
    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.owner_id == owner_id)
    )
    if campaign is None:
        raise APIError(404, "NOT_FOUND", "Campanha nao encontrada")
    return campaign


def _response(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse.model_validate(campaign, from_attributes=True)


def _validate_refs(
    session: Session, owner_id: UUID, bot_id: UUID | None, niche_id: int | None
) -> None:
    if (
        bot_id is not None
        and session.scalar(select(Bot.id).where(Bot.id == bot_id, Bot.owner_id == owner_id)) is None
    ):
        raise APIError(404, "NOT_FOUND", "Bot nao encontrado")
    if (
        niche_id is not None
        and session.scalar(select(Niche.id).where(Niche.id == niche_id, Niche.owner_id == owner_id))
        is None
    ):
        raise APIError(404, "NOT_FOUND", "Nicho nao encontrado")


@router.get("", response_model=PaginatedResponse[CampaignResponse])
def list_campaigns(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    status: str | None = None,
    bot_id: UUID | None = None,
    niche_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    sort: str = "name",
) -> PaginatedResponse[CampaignResponse]:
    statement = select(Campaign).where(Campaign.owner_id == user.id)
    if status is not None:
        statement = statement.where(Campaign.status == status)
    if bot_id is not None:
        statement = statement.where(Campaign.bot_id == bot_id)
    if niche_id is not None:
        statement = statement.where(Campaign.niche_id == niche_id)
    items, total = paginate(
        session,
        statement,
        PaginationParams(page=page, page_size=page_size, sort=sort),
        {
            "name": Campaign.name,
            "status": Campaign.status,
            "started_at": Campaign.started_at,
            "ended_at": Campaign.ended_at,
        },
    )
    return PaginatedResponse(
        items=[_response(item) for item in items], total=total, page=page, page_size=page_size
    )


@router.post(
    "",
    response_model=CampaignResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_campaign(
    payload: CampaignCreate,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> CampaignResponse:
    _validate_refs(session, user.id, payload.bot_id, payload.niche_id)
    campaign = Campaign(id=uuid4(), owner_id=user.id, **payload.model_dump())
    session.add(campaign)
    session.flush()
    response = _response(campaign)
    record_audit(
        session,
        user,
        "campaign",
        str(campaign.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.patch(
    "/{campaign_id}",
    response_model=CampaignResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> CampaignResponse:
    campaign = _owned(session, campaign_id, user.id)
    before = _response(campaign).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name", "valid") is None or changes.get("status", "valid") is None:
        raise APIError(422, "VALIDATION_ERROR", "name e status nao aceitam null")
    _validate_refs(
        session,
        user.id,
        changes.get("bot_id") if "bot_id" in changes else None,
        changes.get("niche_id") if "niche_id" in changes else None,
    )
    started_at = changes.get("started_at", campaign.started_at)
    ended_at = changes.get("ended_at", campaign.ended_at)
    if started_at and ended_at and ended_at < started_at:
        raise APIError(422, "VALIDATION_ERROR", "ended_at nao pode ser anterior a started_at")
    for field, value in changes.items():
        setattr(campaign, field, value)
    session.flush()
    response = _response(campaign)
    record_audit(
        session,
        user,
        "campaign",
        str(campaign.id),
        "update",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/{campaign_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_campaign(
    campaign_id: UUID,
    request: Request,
    user: OperatorUser,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    campaign = _owned(session, campaign_id, user.id)
    linked = session.scalar(
        select(Expense.id).where(Expense.campaign_id == campaign.id).limit(1)
    ) or session.scalar(select(GroupJoin.id).where(GroupJoin.campaign_id == campaign.id).limit(1))
    if linked is not None:
        raise APIError(409, "CONFLICT", "Campanha possui despesas ou entradas vinculadas")
    before = _response(campaign).model_dump(mode="json")
    session.delete(campaign)
    record_audit(
        session, user, "campaign", str(campaign.id), "delete", before, None, client_ip(request)
    )
    session.commit()


@router.get("/{campaign_id}/metrics", response_model=CampaignMetrics)
def campaign_metrics(
    campaign_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> CampaignMetrics:
    campaign = _owned(session, campaign_id, user.id)
    expense_query = select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.owner_id == user.id, Expense.campaign_id == campaign.id
    )
    joins_query = select(func.count(GroupJoin.id)).where(GroupJoin.campaign_id == campaign.id)
    if from_date is not None:
        expense_query = expense_query.where(Expense.incurred_on >= from_date)
        joins_query = joins_query.where(
            GroupJoin.joined_at >= datetime.combine(from_date, time.min, timezone.utc)
        )
    if to_date is not None:
        expense_query = expense_query.where(Expense.incurred_on <= to_date)
        joins_query = joins_query.where(
            GroupJoin.joined_at
            < datetime.combine(to_date + timedelta(days=1), time.min, timezone.utc)
        )
    spend = Decimal(session.scalar(expense_query) or 0)
    joins = int(session.scalar(joins_query) or 0)
    cost = None if joins == 0 else (spend / joins).quantize(Decimal("0.01"))
    return CampaignMetrics(
        campaign_id=campaign.id, spend=spend, group_joins=joins, cost_per_join=cost
    )
