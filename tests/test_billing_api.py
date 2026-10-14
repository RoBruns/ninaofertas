# ruff: noqa: F401, F811
"""Cobrança real em Postgres: eventos, auditoria, catálogo e histórico das métricas."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from api.ratelimit import limiter
from api.security import create_access_token
from core.billing_store import change_subscription
from core.models import AuditLog, Bot, Envio, Oferta, Subscription, SubscriptionEvent, Tenant
from tests.test_api import add_user, auth_header, client, session_factory
from tests.test_bots_api import safe_settings


@pytest.fixture
def platform(client, session_factory):
    limiter.clear()
    admin = add_user(session_factory, email="platform@teste.com", role="admin")
    with session_factory.begin() as session:
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)
    return auth_header(
        create_access_token(str(admin.id), session_version=admin.session_version)
    ), admin


def create_customer(client, headers, **extra):
    return client.post(
        "/api/platform/tenants",
        headers=headers,
        json={
            "name": "Cliente",
            "admin_name": "Dono",
            "admin_email": f"{uuid4()}@teste.com",
            "admin_password": "senha-segura",
            **extra,
        },
    )


def test_catalogo_assinatura_historico_e_auditoria(client, session_factory, platform):
    headers, admin = platform
    plan = client.post(
        "/api/platform/plans",
        headers=headers,
        json={
            "code": "pro",
            "name": "Pro",
            "price": "1200.00",
            "interval": "year",
            "limits": {"max_bots": 3, "max_phones": 1, "max_groups": 10},
        },
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]
    assert (
        client.post(
            "/api/platform/plans", headers=headers, json={"code": "pro", "name": "Duplicado"}
        ).status_code
        == 409
    )
    response = create_customer(client, headers, plan_code="pro", status="active")
    assert response.status_code == 201, response.text
    tenant = response.json()
    assert tenant["mrr"] == "100.00" and tenant["subscription"]["price"] == "1200.00"
    assert tenant["usage"] == {"bots": 0, "phones": 0, "groups": 0}
    tenant_id = tenant["id"]
    path = f"/api/platform/tenants/{tenant_id}/subscription"
    events_path = path + "/events"
    assert (
        client.patch(
            f"/api/platform/plans/{plan_id}",
            headers=headers,
            json={"price": "2400.00", "limits": {}},
        ).status_code
        == 200
    )
    listed = client.get("/api/platform/tenants", headers=headers).json()
    customer = next(t for t in listed if t["id"] == tenant_id)
    assert customer["plan"]["price"] == "2400.00" and customer["subscription"]["price"] == "1200.00"
    assert customer["plan"]["limits"] == {}
    assert client.patch(path, headers=headers, json={"status": "canceled"}).status_code == 422
    assert (
        client.patch(
            path, headers=headers, json={"status": "canceled", "cancel_reason": "  "}
        ).status_code
        == 422
    )
    assert len(client.get(events_path, headers=headers).json()) == 1
    for body in (
        {"price": "1440.00", "note": "Ajuste anual"},
        {"status": "past_due"},
        {"status": "canceled", "cancel_reason": "Pausa", "note": "Pedido do cliente"},
        {"status": "active"},
        {"plan_code": "beta"},
    ):
        result = client.patch(path, headers=headers, json=body)
        assert result.status_code == 200, result.text
    events = list(reversed(client.get(events_path, headers=headers).json()))
    assert [e["type"] for e in events] == [
        "created",
        "price_changed",
        "status_changed",
        "canceled",
        "reactivated",
        "plan_changed",
    ]
    assert [(e["mrr_before"], e["mrr_after"]) for e in events] == [
        ("0.00", "100.00"),
        ("100.00", "120.00"),
        ("120.00", "120.00"),
        ("120.00", "0.00"),
        ("0.00", "120.00"),
        ("120.00", "0.00"),
    ]
    assert all(e["created_by"] == str(admin.id) for e in events)
    with session_factory() as session:
        audit = session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "subscription").order_by(AuditLog.id)
        ).all()
        assert len(audit) == 5 and all(str(a.tenant_id) == tenant_id for a in audit)
        assert audit[0].before["price"] == "1200.00" and audit[0].after["price"] == "1440.00"


def test_trial_validacoes_conta_interna_e_atomicidade(client, session_factory, platform):
    headers, admin = platform
    response = create_customer(client, headers)
    assert response.status_code == 201, response.text
    tenant = response.json()
    subscription = tenant["subscription"]
    assert subscription["status"] == "trialing" and tenant["mrr"] == "0.00"
    assert datetime.fromisoformat(subscription["trial_ends_at"]) - datetime.fromisoformat(
        subscription["started_at"]
    ) == timedelta(days=14)
    path = f"/api/platform/tenants/{tenant['id']}/subscription"
    for body in (
        {"price": -1},
        {"price": 1.5},
        {"price": "NaN"},
        {"status": "invalid"},
        {"status": None},
        {"interval": None},
        {"current_period_end": "2026-10-01T00:00:00"},
    ):
        assert client.patch(path, headers=headers, json=body).status_code == 422
    for body in (
        {"limits": {"max_bots": -1}},
        {"limits": {"max_bots": None}},
        {"limits": {"max_bots": True}},
        {"limits": {"other": 1}},
    ):
        assert (
            client.patch(
                "/api/platform/plans/" + tenant["plan"]["id"], headers=headers, json=body
            ).status_code
            == 422
        )
    assert (
        client.patch(
            f"/api/platform/tenants/{admin.tenant_id}/subscription",
            headers=headers,
            json={"status": "comp"},
        ).status_code
        == 409
    )
    assert (
        client.get(
            f"/api/platform/tenants/{uuid4()}/subscription/events", headers=headers
        ).status_code
        == 404
    )
    failed = create_customer(client, headers, name="Não persistir", plan_code="ausente")
    assert failed.status_code == 404
    with session_factory() as session:
        assert session.scalar(select(Tenant).where(Tenant.name == "Não persistir")) is None
        assert (
            session.scalar(select(Subscription).where(Subscription.tenant_id == admin.tenant_id))
            is None
        )
    result = client.patch(
        path, headers=headers, json={"status": "comp", "current_period_end": "2027-01-02T03:00:00Z"}
    )
    assert result.status_code == 200 and result.json()["trial_ends_at"] is None
    beta_id = tenant["plan"]["id"]
    assert (
        client.patch(
            f"/api/platform/plans/{beta_id}", headers=headers, json={"is_active": False}
        ).status_code
        == 200
    )
    assert create_customer(client, headers).status_code == 409
    # A inativação não impede ajustes em contratos existentes.
    assert client.patch(path, headers=headers, json={"status": "active"}).status_code == 200


def test_metricas_do_banco_reconstroem_historia_sem_estado_atual(client, session_factory, platform):
    headers, admin = platform
    now = datetime.now(timezone.utc)
    from core.relogio import BR

    start = now.astimezone(BR).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tenant_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name="Antigo",
                is_internal=False,
                created_at=start - timedelta(days=40),
            )
        )
        session.flush()
        # Criação histórica: não atualizamos o livro-razão para montar o cenário.
        sub = change_subscription(
            session,
            tenant_id,
            {"status": "active", "price": Decimal("100.00")},
            created_by=admin.id,
        )
        session.execute(
            text(
                "INSERT INTO subscription_events (tenant_id, subscription_id, type, status_after, mrr_before, mrr_after, occurred_at) VALUES (:tenant, :sub, 'price_changed', 'active', 0, 80, :date)"
            ),
            {"tenant": tenant_id, "sub": sub.id, "date": start - timedelta(days=1)},
        )
    result = client.get("/api/platform/metrics?months=12", headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert len(data["months"]) == 12
    assert data["months"][-2]["mrr"] == "80.00"
    assert data["months"][-1]["paying_start"] == 1
    assert data["months"][-1]["expansion_mrr"] == "20.00"
    assert data["summary"] == {
        "mrr": "100.00",
        "paying": 1,
        "new_tenants": 0,
        "churned": 0,
        "churn_rate": "0.0000",
        "arpa": "100.00",
    }
    path = f"/api/platform/tenants/{tenant_id}/subscription"
    assert (
        client.patch(
            path, headers=headers, json={"status": "canceled", "cancel_reason": "Saiu"}
        ).status_code
        == 200
    )
    data = client.get("/api/platform/metrics", headers=headers).json()
    assert data["summary"]["churned"] == 1 and data["summary"]["churn_rate"] == "1.0000"
    assert data["months"][-2]["mrr"] == "80.00"
    assert client.patch(path, headers=headers, json={"status": "active"}).status_code == 200
    assert client.get("/api/platform/metrics", headers=headers).json()["summary"]["churned"] == 0


def test_sem_pagantes_e_rollback_do_writer(client, session_factory, platform):
    headers, admin = platform
    data = client.get("/api/platform/metrics", headers=headers).json()
    assert data["summary"]["churn_rate"] is None and data["summary"]["arpa"] is None
    tenant_id = uuid4()
    with session_factory.begin() as session:
        session.add(Tenant(id=tenant_id, name="Rollback", is_internal=False))
    with session_factory() as session:
        change_subscription(
            session, tenant_id, {"status": "active", "price": Decimal("99.00")}, created_by=admin.id
        )
        session.rollback()
    with session_factory() as session:
        assert (
            session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id)) is None
        )
        assert (
            session.scalar(
                select(SubscriptionEvent).where(SubscriptionEvent.tenant_id == tenant_id)
            )
            is None
        )


def test_writer_recarrega_apos_alteracao_por_outra_sessao(session_factory):
    tenant_id = uuid4()
    with session_factory.begin() as session:
        session.add(Tenant(id=tenant_id, name="Concorrência", is_internal=False))
    with session_factory() as first:
        subscription = change_subscription(
            first, tenant_id, {"status": "active", "price": Decimal("10.00")}, created_by=None
        )
        first.commit()
        with session_factory.begin() as second:
            change_subscription(second, tenant_id, {"price": Decimal("20.00")}, created_by=None)
        assert subscription.price == Decimal("10.00")
        change_subscription(first, tenant_id, {"price": Decimal("30.00")}, created_by=None)
        first.commit()
        events = first.scalars(
            select(SubscriptionEvent)
            .where(SubscriptionEvent.tenant_id == tenant_id)
            .order_by(SubscriptionEvent.id)
        ).all()
        assert [(event.mrr_before, event.mrr_after) for event in events] == [
            (Decimal("0.00"), Decimal("10.00")),
            (Decimal("10.00"), Decimal("20.00")),
            (Decimal("20.00"), Decimal("30.00")),
        ]


def test_cobranca_e_limites_nao_bloqueiam_cliente_nem_pausam_bot(client, session_factory, platform):
    headers, _ = platform
    plan = client.post(
        "/api/platform/plans",
        headers=headers,
        json={"code": "zero", "name": "Sem cota", "limits": {"max_bots": 0}},
    ).json()
    tenant = create_customer(client, headers, plan_code=plan["code"]).json()
    with session_factory() as session:
        from core.models import User

        user = session.scalar(select(User).where(User.tenant_id == tenant["id"]))
    customer_headers = auth_header(
        create_access_token(str(user.id), session_version=user.session_version)
    )
    created = client.post(
        "/api/bots",
        headers=customer_headers,
        json={"name": "Bot do cliente", "slug": "cliente", "settings": safe_settings()},
    )
    assert created.status_code == 201, created.text
    bot_id = created.json()["id"]
    with session_factory.begin() as session:
        session.get(Bot, bot_id).status = "active"
    for status in ("past_due", "canceled", "comp", "trialing"):
        result = client.patch(
            f"/api/platform/tenants/{tenant['id']}/subscription",
            headers=headers,
            json={"status": status, "cancel_reason": "Pausa" if status == "canceled" else None},
        )
        assert result.status_code == 200, result.text
        assert client.get("/api/auth/me", headers=customer_headers).status_code == 200
        assert (
            client.get(f"/api/bots/{bot_id}", headers=customer_headers).json()["status"] == "active"
        )
    listed = client.get("/api/platform/tenants", headers=headers).json()
    customer = next(row for row in listed if row["id"] == tenant["id"])
    assert customer["usage"]["bots"] == 1 and customer["plan"]["limits"]["max_bots"] == 0
