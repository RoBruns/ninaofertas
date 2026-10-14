"""Administração de contas, restrita ao administrador da plataforma."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.audit import record_audit
from api.deps import get_db, limit_authenticated_write, require_platform_admin
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.tenant import TenantCreate, TenantResponse, TenantUpdate
from api.schemas.billing import (
    BillingMetricsResponse,
    BillingSummary,
    MonthlyBillingMetrics,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
    SubscriptionEventResponse,
    SubscriptionResponse,
    SubscriptionUpdate,
)
from api.security import hash_password
from core import relogio
from core.billing import metricas_mensais, resumo_mes_atual
from core.billing_store import BillingError, change_subscription, metric_inputs, subscription_mrr
from core.repositories import escopo_envios_conta
from core.models import (
    Bot,
    Envio,
    Group,
    Phone,
    Plan,
    Subscription,
    SubscriptionEvent,
    Tenant,
    User,
)

router = APIRouter(prefix="/platform", tags=["platform"])
PlatformAdmin = Annotated[User, Depends(require_platform_admin)]


def _response(session: Session, tenant: Tenant) -> TenantResponse:
    users = session.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id))
    bots = session.scalar(
        select(func.count(Bot.id)).where(Bot.owner_id == tenant.id, Bot.status == "active")
    )
    sends = session.scalar(
        select(func.count(Envio.id)).where(
            Envio.status == "sucesso",
            Envio.enviado_em >= relogio.agora_banco() - timedelta(days=30),
            escopo_envios_conta(tenant_id=tenant.id),
        )
    )
    subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant.id))
    plan = session.get(Plan, subscription.plan_id) if subscription else None
    usage = {
        key: int(
            session.scalar(select(func.count(model.id)).where(model.owner_id == tenant.id)) or 0
        )
        for key, model in (("bots", Bot), ("phones", Phone), ("groups", Group))
    }
    return TenantResponse.model_validate(tenant).model_copy(
        update={
            "users_count": int(users or 0),
            "active_bots_count": int(bots or 0),
            "successful_sends_30d": int(sends or 0),
            "plan": PlanResponse.model_validate(plan) if plan else None,
            "subscription": SubscriptionResponse.model_validate(subscription)
            if subscription
            else None,
            "mrr": subscription_mrr(subscription) if subscription else Decimal("0.00"),
            "usage": usage,
        }
    )


@router.get("/tenants", response_model=list[TenantResponse])
def list_tenants(
    admin: PlatformAdmin, session: Annotated[Session, Depends(get_db)]
) -> list[TenantResponse]:
    return [
        _response(session, tenant)
        for tenant in session.scalars(select(Tenant).order_by(Tenant.created_at))
    ]


@router.post(
    "/tenants",
    status_code=201,
    response_model=TenantResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_tenant(
    payload: TenantCreate,
    request: Request,
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
) -> TenantResponse:
    if session.scalar(select(User.id).where(User.email == payload.admin_email)):
        raise APIError(409, "CONFLICT", "Email já cadastrado")
    tenant = Tenant(id=uuid4(), name=payload.name, is_internal=False)
    session.add(tenant)
    try:
        session.flush()
        session.add(
            User(
                id=uuid4(),
                tenant_id=tenant.id,
                email=payload.admin_email,
                name=payload.admin_name,
                password_hash=hash_password(payload.admin_password),
                role="admin",
                is_platform_admin=False,
            )
        )
        session.flush()
        try:
            change_subscription(
                session,
                tenant.id,
                {"plan_code": payload.plan_code, "status": payload.status},
                created_by=admin.id,
            )
        except BillingError as exc:
            raise APIError(exc.status_code, "BILLING_ERROR", str(exc)) from exc
        response = _response(session, tenant)
        record_audit(
            session,
            admin,
            "tenant",
            str(tenant.id),
            "create",
            None,
            response.model_dump(mode="json"),
            client_ip(request),
            tenant_id=tenant.id,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise APIError(409, "CONFLICT", "Email já cadastrado") from exc
    return response


@router.get("/plans", response_model=list[PlanResponse])
def list_plans(admin: PlatformAdmin, session: Annotated[Session, Depends(get_db)]) -> list[Plan]:
    return list(session.scalars(select(Plan).order_by(Plan.created_at, Plan.code)))


@router.post(
    "/plans",
    status_code=201,
    response_model=PlanResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_plan(
    payload: PlanCreate,
    request: Request,
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
) -> Plan:
    values = payload.model_dump(exclude={"limits"})
    plan = Plan(**values, limits=payload.limits.model_dump(exclude_unset=True))
    session.add(plan)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise APIError(409, "CONFLICT", "Código de plano já cadastrado") from exc
    record_audit(
        session,
        admin,
        "plan",
        str(plan.id),
        "create",
        None,
        PlanResponse.model_validate(plan).model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return plan


@router.patch(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_plan(
    plan_id: UUID,
    payload: PlanUpdate,
    request: Request,
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.id == plan_id).with_for_update())
    if plan is None:
        raise APIError(404, "NOT_FOUND", "Plano não encontrado")
    before = PlanResponse.model_validate(plan).model_dump(mode="json")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, key, value)
    session.flush()
    record_audit(
        session,
        admin,
        "plan",
        str(plan.id),
        "update",
        before,
        PlanResponse.model_validate(plan).model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return plan


@router.patch(
    "/tenants/{tenant_id}/subscription",
    response_model=SubscriptionResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_subscription(
    tenant_id: UUID,
    payload: SubscriptionUpdate,
    request: Request,
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
) -> Subscription:
    # O mesmo lock protege o snapshot da auditoria e a escrita do livro-razão.
    session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    previous = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    before = (
        SubscriptionResponse.model_validate(previous).model_dump(mode="json") if previous else None
    )
    try:
        subscription = change_subscription(
            session, tenant_id, payload.model_dump(exclude_unset=True), created_by=admin.id
        )
    except BillingError as exc:
        raise APIError(exc.status_code, "BILLING_ERROR", str(exc)) from exc
    record_audit(
        session,
        admin,
        "subscription",
        str(subscription.id),
        "update" if previous else "create",
        before,
        SubscriptionResponse.model_validate(subscription).model_dump(mode="json"),
        client_ip(request),
        tenant_id=tenant_id,
    )
    session.commit()
    return subscription


@router.get(
    "/tenants/{tenant_id}/subscription/events", response_model=list[SubscriptionEventResponse]
)
def subscription_events(
    tenant_id: UUID, admin: PlatformAdmin, session: Annotated[Session, Depends(get_db)]
) -> list[SubscriptionEvent]:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise APIError(404, "NOT_FOUND", "Conta não encontrada")
    if tenant.is_internal:
        raise APIError(409, "CONFLICT", "Contas internas não têm assinatura")
    return list(
        session.scalars(
            select(SubscriptionEvent)
            .where(SubscriptionEvent.tenant_id == tenant_id)
            .order_by(SubscriptionEvent.occurred_at.desc(), SubscriptionEvent.id.desc())
        )
    )


@router.get("/metrics", response_model=BillingMetricsResponse)
def billing_metrics(
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
    months: int = Query(default=12, ge=1, le=120),
) -> BillingMetricsResponse:
    accounts, events = metric_inputs(session)
    now = datetime.now(timezone.utc)
    summary = resumo_mes_atual(accounts, events, now)
    return BillingMetricsResponse(
        months=[
            MonthlyBillingMetrics.model_validate(month)
            for month in metricas_mensais(accounts, events, months, now)
        ],
        summary=BillingSummary(
            mrr=summary.mrr,
            paying=summary.paying_end,
            new_tenants=summary.new_tenants,
            churned=summary.churned,
            churn_rate=summary.churn_rate,
            arpa=summary.arpa,
        ),
    )


@router.patch(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    request: Request,
    admin: PlatformAdmin,
    session: Annotated[Session, Depends(get_db)],
) -> TenantResponse:
    tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise APIError(404, "NOT_FOUND", "Conta não encontrada")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("status") == "suspended" and tenant.id == admin.tenant_id:
        raise APIError(409, "CONFLICT", "Não é permitido suspender sua própria conta")
    before = _response(session, tenant).model_dump(mode="json")
    for key, value in changes.items():
        setattr(tenant, key, value)
    if tenant.status == "suspended":
        for bot in session.scalars(
            select(Bot).where(Bot.owner_id == tenant.id, Bot.status == "active").with_for_update()
        ):
            bot.status = "paused"
            record_audit(
                session,
                admin,
                "bot",
                str(bot.id),
                "tenant_suspended",
                {"status": "active"},
                {"status": "paused"},
                client_ip(request),
                tenant_id=tenant.id,
            )
    session.flush()
    response = _response(session, tenant)
    record_audit(
        session,
        admin,
        "tenant",
        str(tenant.id),
        "update",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
        tenant_id=tenant.id,
    )
    session.commit()
    return response
