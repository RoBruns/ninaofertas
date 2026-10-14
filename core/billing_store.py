"""Persistência da cobrança: uma única escrita de assinatura e evento, sem commit.

O chamador confirma assinatura, evento e auditoria na mesma transação. O lock da
conta serializa inclusive a primeira assinatura; ocorrido_em é obtido após o lock.
Trocar plano adota seu preço/intervalo, salvo valores explícitos. Editar o catálogo
de planos não altera preços já contratados. Clientes anteriores à S2 podem receber
sua primeira assinatura pela mesma função; não fabricamos receita retroativa.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.billing import Conta, EventoAssinatura, mrr_da_assinatura
from core.models import Plan, Subscription, SubscriptionEvent, Tenant


class BillingError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def subscription_mrr(subscription: Subscription) -> Decimal:
    return mrr_da_assinatura(
        subscription.price,
        cast(Literal["month", "year"], subscription.interval),
        subscription.status,
    )


def change_subscription(
    session: Session, tenant_id: UUID, changes: dict[str, Any], *, created_by: UUID | None
) -> Subscription:
    """Único ponto de criação/alteração; grava um evento com a variação integral."""
    tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise BillingError("Conta não encontrada", 404)
    if tenant.is_internal:
        raise BillingError("Contas internas não têm assinatura", 409)
    # Recarrega o contrato após o lock, mesmo em uma sessão reutilizada que já
    # tenha a versão anterior no identity map do SQLAlchemy.
    subscription = session.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    now = datetime.now(timezone.utc)
    before_status = subscription.status if subscription else None
    before_mrr = subscription_mrr(subscription) if subscription else Decimal("0.00")
    plan_changed = False
    price_changed = False
    plan = None
    if "plan_code" in changes or subscription is None:
        plan = session.scalar(select(Plan).where(Plan.code == changes.get("plan_code", "beta")))
        if plan is None:
            raise BillingError("Plano não encontrado", 404)
        plan_changed = subscription is None or plan.id != subscription.plan_id
        if plan_changed and not plan.is_active:
            raise BillingError("O plano está inativo", 409)
    status = changes.get("status", before_status or "trialing")
    reason = changes.get("cancel_reason", subscription.cancel_reason if subscription else None)
    if status == "canceled" and (not reason or not reason.strip()):
        raise BillingError("Informe o motivo do cancelamento")
    if subscription is None:
        subscription = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            price=plan.price,
            interval=plan.interval,
            status=status,
            started_at=now,
            current_period_start=now,
        )
        session.add(subscription)
    elif plan_changed:
        subscription.plan_id, subscription.price, subscription.interval = (
            plan.id,
            plan.price,
            plan.interval,
        )
    old_price, old_interval = subscription.price, subscription.interval
    for field in ("price", "interval", "current_period_end"):
        if field in changes:
            setattr(subscription, field, changes[field])
    price_changed = subscription.price != old_price or subscription.interval != old_interval
    subscription.status = status
    subscription.cancel_reason = reason if status == "canceled" else None
    if status == "canceled" and before_status != "canceled":
        subscription.canceled_at = now
    elif status != "canceled":
        subscription.canceled_at = None
    if status == "trialing" and before_status != "trialing":
        subscription.trial_ends_at = now + timedelta(days=14)
    elif status != "trialing":
        subscription.trial_ends_at = None
    subscription.updated_at = now
    after_mrr = subscription_mrr(subscription)
    event_type = (
        "created"
        if before_status is None
        else "canceled"
        if status == "canceled" and before_status != status
        else "reactivated"
        if before_status == "canceled" and status != "canceled"
        else "plan_changed"
        if plan_changed
        else "price_changed"
        if price_changed
        else "status_changed"
    )
    session.flush()
    session.add(
        SubscriptionEvent(
            tenant_id=tenant_id,
            subscription_id=subscription.id,
            type=event_type,
            status_before=before_status,
            status_after=status,
            mrr_before=before_mrr,
            mrr_after=after_mrr,
            occurred_at=now,
            created_by=created_by,
            note=changes.get("note"),
        )
    )
    session.flush()
    return subscription


def metric_inputs(session: Session) -> tuple[list[Conta], list[EventoAssinatura]]:
    """Lê todo o histórico, inclusive anterior à janela, para reconstruir a abertura."""
    accounts = [Conta(t.id, t.created_at, t.is_internal) for t in session.scalars(select(Tenant))]
    events = [
        EventoAssinatura(e.tenant_id, e.occurred_at, e.mrr_before, e.mrr_after)
        for e in session.scalars(
            select(SubscriptionEvent).order_by(SubscriptionEvent.occurred_at, SubscriptionEvent.id)
        )
    ]
    return accounts, events
