"""Visao curta para responder se toda a operacao esta funcionando."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.system import (
    AccountSystemStatus,
    AlertTotals,
    BotSystemStatus,
    PhoneSystemStatus,
    SystemStatusResponse,
)
from core.models import Alert, AutomationRun, Bot, Phone, PlatformAccount, PlatformCredential, User

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatusResponse)
def system_status(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> SystemStatusResponse:
    bots = []
    for bot in session.scalars(select(Bot).where(Bot.owner_id == user.id).order_by(Bot.name)):
        latest = session.scalar(
            select(AutomationRun)
            .where(AutomationRun.bot_id == bot.id)
            .order_by(AutomationRun.started_at.desc())
            .limit(1)
        )
        last_failure = session.scalar(
            select(func.max(AutomationRun.started_at)).where(
                AutomationRun.bot_id == bot.id, AutomationRun.status == "failed"
            )
        )
        bots.append(
            BotSystemStatus(
                id=bot.id,
                name=bot.name,
                status=bot.status,
                last_run_at=latest.started_at if latest else None,
                last_run_status=latest.status if latest else None,
                last_failure_at=last_failure,
            )
        )

    accounts = []
    priority = {"invalid": 0, "expired": 1, "expiring": 2, "unknown": 3, "valid": 4}
    for account in session.scalars(
        select(PlatformAccount)
        .where(PlatformAccount.owner_id == user.id)
        .order_by(PlatformAccount.label)
    ):
        statuses = list(
            session.scalars(
                select(PlatformCredential.status).where(PlatformCredential.account_id == account.id)
            )
        )
        credential_health = (
            min(statuses, key=lambda item: priority.get(item, 3)) if statuses else "unknown"
        )
        accounts.append(
            AccountSystemStatus(
                id=account.id,
                label=account.label,
                status=account.status,
                credential_health=credential_health,
            )
        )

    phones = [
        PhoneSystemStatus(
            id=phone.id,
            label=phone.label,
            status=phone.status,
            last_seen_at=phone.last_seen_at,
        )
        for phone in session.scalars(
            select(Phone).where(Phone.owner_id == user.id).order_by(Phone.label)
        )
    ]
    # `.tuples().all()`: um Result tem `.keys()`, e `dict(result)` o trata como
    # mapping e tenta indexá-lo — TypeError. Materialize os pares antes.
    counts = dict(
        session.execute(
            select(Alert.severity, func.count(Alert.id))
            .where(
                Alert.owner_id == user.id,
                Alert.status.in_(("open", "acknowledged")),
            )
            .group_by(Alert.severity)
        )
        .tuples()
        .all()
    )
    return SystemStatusResponse(
        bots=bots,
        accounts=accounts,
        phones=phones,
        open_alerts=AlertTotals(
            critical=int(counts.get("critical", 0)), warning=int(counts.get("warning", 0))
        ),
    )
