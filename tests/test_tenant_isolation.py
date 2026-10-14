# ruff: noqa: F401, F811
"""Matriz de isolamento descobrindo rotas reais; rota nova exige cobertura."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from api.main import app
from api.ratelimit import limiter
from api.security import REFRESH_COOKIE_NAME, create_access_token, create_refresh_token
from core.models import (
    Alert,
    AuditLog,
    Base,
    Bot,
    BotConfigBackup,
    BotGroup,
    BotPlatformAccount,
    Campaign,
    Envio,
    Event,
    Expense,
    ExpenseCategory,
    Group,
    Oferta,
    PlatformAccount,
    Sale,
    Tenant,
    User,
)
from tests.test_api import add_user, auth_header, client, session_factory
from tests.test_bots_api import add_catalog, safe_settings


# Métodos explicitados: adicionar método a uma rota existente também falha.
RESOURCE_ROUTES = {
    "/api/users/{user_id}": {"PATCH": {"name": "Alterado"}, "DELETE": None},
    "/api/accounts/{account_id}": {"GET": None, "PATCH": {"label": "Alterado"}, "DELETE": None},
    "/api/accounts/{account_id}/activate": {"POST": None},
    "/api/accounts/{account_id}/pause": {"POST": None},
    "/api/accounts/{account_id}/credentials": {"GET": None},
    "/api/accounts/{account_id}/credentials/{kind}": {
        "PUT": {"value": "cookie=teste"},
        "DELETE": None,
    },
    "/api/accounts/{account_id}/credentials/{kind}/test": {"POST": None},
    "/api/alerts/{alert_id}/acknowledge": {"POST": None},
    "/api/alerts/{alert_id}/resolve": {"POST": None},
    "/api/niches/{niche_id}": {"PATCH": {"name": "Alterado"}, "DELETE": None},
    "/api/phones/{phone_id}": {"PATCH": {"label": "Alterado"}, "DELETE": None},
    "/api/phones/{phone_id}/qrcode": {"GET": None},
    "/api/phones/{phone_id}/sync-groups": {"POST": None},
    "/api/phones/{phone_id}/instance": {"POST": None},
    "/api/phones/{phone_id}/instance/token/sync": {"POST": None},
    "/api/phones/{phone_id}/status": {"GET": None},
    "/api/groups/{group_id}": {"PATCH": {"name": "Alterado"}, "DELETE": None},
    "/api/bots/{test_bot_id}/import-config": {"POST": "target"},
    "/api/bots/{bot_id}/archive": {"POST": None},
    "/api/bots/{bot_id}/config-backups": {"GET": None},
    "/api/bots/{bot_id}/config-backups/{backup_id}/restore": {"POST": None},
    "/api/bots/{bot_id}": {"GET": None, "PATCH": {"name": "Alterado"}, "DELETE": None},
    "/api/bots/{bot_id}/duplicate": {"POST": None},
    "/api/bots/{bot_id}/activate": {"POST": None},
    "/api/bots/{bot_id}/pause": {"POST": None},
    "/api/bots/{bot_id}/disable": {"POST": None},
    "/api/bots/{bot_id}/run-now": {"POST": None},
    "/api/bots/{bot_id}/runs": {"GET": None},
    "/api/bots/{bot_id}/health": {"GET": None},
    "/api/bots/{bot_id}/groups": {"PUT": {"group_ids": []}},
    "/api/bots/{bot_id}/accounts": {"PUT": {"account_ids": []}},
    "/api/expenses/{expense_id}": {"PATCH": {"description": "Alterada"}, "DELETE": None},
    "/api/campaigns/{campaign_id}": {"PATCH": {"name": "Alterada"}, "DELETE": None},
    "/api/campaigns/{campaign_id}/metrics": {"GET": None},
}

LIST_ROUTES = {
    "/api/users",
    "/api/audit-logs",
    "/api/accounts",
    "/api/alerts",
    "/api/events",
    "/api/niches",
    "/api/phones",
    "/api/groups",
    "/api/bots",
    "/api/expenses",
    "/api/expense-categories",
    "/api/campaigns",
    "/api/sales",
    "/api/sales/imports",
    "/api/metrics/overview",
    "/api/metrics/timeseries",
    "/api/metrics/by-platform",
    "/api/metrics/by-account",
    "/api/metrics/by-bot",
    "/api/metrics/by-group",
    "/api/metrics/by-campaign",
    "/api/metrics/by-niche",
    "/api/metrics/funnel",
    "/api/system/status",
}

# Exclusões específicas, sem prefixos que escondam novas rotas.
EXCLUDED_ROUTES = {
    **{
        (method, path): "Cobrança global; usuário comum recebe 403 no teste de permissões"
        for method, path in (
            ("GET", "/api/platform/plans"),
            ("POST", "/api/platform/plans"),
            ("PATCH", "/api/platform/plans/{plan_id}"),
            ("PATCH", "/api/platform/tenants/{tenant_id}/subscription"),
            ("GET", "/api/platform/tenants/{tenant_id}/subscription/events"),
            ("GET", "/api/platform/metrics"),
        )
    },
    ("GET", "/api/health"): "Saúde pública sem dados operacionais",
    ("POST", "/api/internal/heartbeat"): "Autenticação própria do worker",
    ("POST", "/api/auth/login"): "Identidade; suspensão testada separadamente",
    ("POST", "/api/auth/refresh"): "Identidade; suspensão testada separadamente",
    ("POST", "/api/auth/logout"): "Identidade; sem consulta operacional",
    ("GET", "/api/auth/me"): "Identidade; tenant testado separadamente",
    ("GET", "/api/platforms"): "Catálogo global compartilhado por definição",
    ("GET", "/api/platform/tenants"): "Painel global; permissão testada separadamente",
    ("POST", "/api/platform/tenants"): "Painel global; permissão testada separadamente",
    (
        "PATCH",
        "/api/platform/tenants/{tenant_id}",
    ): "Painel global; permissão testada separadamente",
    **{
        (
            "POST",
            path,
        ): "Criação/importação sem id no caminho; vínculos cobertos pelos testes da API"
        for path in (
            "/api/users",
            "/api/accounts",
            "/api/niches",
            "/api/phones",
            "/api/groups",
            "/api/groups/from-invite",
            "/api/bots",
            "/api/bots/test",
            "/api/expenses",
            "/api/expense-categories",
            "/api/expenses/import",
            "/api/campaigns",
            "/api/sales/import",
            "/api/sales/sync",
        )
    },
}


def routes_from_app():
    for route in app.routes:
        # FastAPI recente mantém inclusões lazy; usa seus contextos efetivos.
        if hasattr(route, "effective_route_contexts"):
            yield from route.effective_route_contexts()
        elif isinstance(route, APIRoute):
            yield route


def test_todas_as_rotas_tem_cobertura():
    actual = {(method, route.path) for route in routes_from_app() for method in route.methods}
    covered = {(method, path) for path, methods in RESOURCE_ROUTES.items() for method in methods}
    covered |= {("GET", path) for path in LIST_ROUTES} | EXCLUDED_ROUTES.keys()
    assert actual == covered, (
        f"Sem cobertura: {actual - covered}; cobertura obsoleta: {covered - actual}"
    )


@pytest.fixture
def operations(session_factory, monkeypatch):
    original_send = httpx.Client.send

    def no_http(self, request, **kwargs):
        if request.url.host != "testserver":
            pytest.fail("O teste tentou chamar servico externo")
        return original_send(self, request, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", no_http)
    # TestClient implementa request; a Evolution usa o método acima.
    from core.evolution import EvolutionClient

    monkeypatch.setattr(EvolutionClient, "connection_status", lambda *args: "unknown")
    result = []
    for name in ("A", "B"):
        tenant_id = uuid4()
        with session_factory.begin() as session:
            session.add(Tenant(id=tenant_id, name=name, is_internal=False))
        user = add_user(
            session_factory,
            email=f"{name}@teste.com",
            tenant_id=tenant_id,
            role="admin",
            is_platform_admin=False,
        )
        catalog = add_catalog(session_factory, user.tenant_id)
        with session_factory.begin() as session:
            Oferta.__table__.create(session.connection(), checkfirst=True)
            Envio.__table__.create(session.connection(), checkfirst=True)
            for group_id in catalog["group_ids"]:
                session.get(Group, group_id).whatsapp_id = f"{name}-{group_id}@g.us"
            bot = Bot(
                id=uuid4(),
                owner_id=user.tenant_id,
                name=name,
                slug=name.lower(),
                phone_id=catalog["phone_id"],
                settings=safe_settings(),
                status="active",
            )
            category = ExpenseCategory(owner_id=user.tenant_id, slug="infra", name=name)
            session.add_all([bot, category])
            session.flush()
            campaign = Campaign(id=uuid4(), owner_id=user.tenant_id, name=name, bot_id=bot.id)
            backup = BotConfigBackup(
                id=uuid4(),
                owner_id=user.tenant_id,
                bot_id=bot.id,
                settings=bot.settings,
                reason="restore",
                created_by=user.id,
            )
            session.add_all(
                [
                    campaign,
                    backup,
                    BotGroup(bot_id=bot.id, group_id=catalog["group_ids"][0]),
                    BotPlatformAccount(bot_id=bot.id, account_id=catalog["account_ids"][0]),
                ]
            )
            session.flush()
            expense = Expense(
                id=uuid4(),
                owner_id=user.tenant_id,
                description=name,
                amount=Decimal("10"),
                incurred_on=date.today(),
                category_id=category.id,
                campaign_id=campaign.id,
                created_by=user.id,
            )
            account = session.get(PlatformAccount, catalog["account_ids"][0])
            sale = Sale(
                id=uuid4(),
                owner_id=user.tenant_id,
                account_id=account.id,
                platform_id=account.platform_id,
                external_id=name,
                gross_amount=Decimal("100"),
                commission=Decimal("10"),
                ordered_at=datetime.now(timezone.utc),
                source="teste",
                bot_id=bot.id,
            )
            alert = Alert(
                id=uuid4(),
                owner_id=user.tenant_id,
                type="teste",
                severity="warning",
                title=name,
                dedup_key=name,
            )
            event = Event(
                tenant_id=user.tenant_id, bot_id=bot.id, level="error", type="teste", message=name
            )
            audit = AuditLog(
                tenant_id=user.tenant_id,
                user_id=user.id,
                entity_type="teste",
                entity_id=name,
                action="create",
            )
            session.add_all([expense, sale, alert, event, audit])
            session.flush()
            ids = {
                "user_id": user.id,
                "account_id": account.id,
                "niche_id": catalog["niche_id"],
                "phone_id": catalog["phone_id"],
                "group_id": catalog["group_ids"][0],
                "bot_id": bot.id,
                "test_bot_id": bot.id,
                "backup_id": backup.id,
                "expense_id": expense.id,
                "campaign_id": campaign.id,
                "alert_id": alert.id,
                "sale_id": sale.id,
                "event_id": event.id,
                "audit_id": audit.id,
                "category_id": category.id,
                "kind": "cookie",
            }
            # Inclui os demais UUIDs e IDs nos sentinelas de leitura.
            sentinels = {str(v) for k, v in ids.items() if k != "kind" and not isinstance(v, int)}
            sentinels |= {str(v) for v in catalog["account_ids"] + catalog["group_ids"]}
            result.append((user, ids, sentinels))
    return result


def snapshot(factory):
    with factory() as session:
        return {
            table.name: sorted(repr(row) for row in session.execute(select(table)))
            for table in Base.metadata.sorted_tables
        }


def test_recursos_e_listagens_isolados(client, session_factory, operations):
    (a, ids, sentinels), (b, b_ids, _) = operations
    headers = auth_header(create_access_token(str(b.id), session_version=b.session_version))
    before = snapshot(session_factory)
    for route in routes_from_app():
        if route.path not in RESOURCE_ROUTES:
            continue
        path = re.sub(r"\{([^}]+)\}", lambda match: str(ids[match[1]]), route.path)
        for method in route.methods:
            limiter.clear()
            body = RESOURCE_ROUTES[route.path][method]
            if body == "target":
                body = {"target_bot_id": str(b_ids["bot_id"])}
            response = client.request(
                method, path, headers=headers, **({"json": body} if body is not None else {})
            )
            if route.path.startswith("/api/phones/"):
                assert response.status_code == 404, (method, path, response.text)
            else:
                assert response.status_code in (403, 404), (method, path, response.text)
            assert snapshot(session_factory) == before, (method, path)
    for route in routes_from_app():
        if route.path not in LIST_ROUTES:
            continue
        response = client.get(
            route.path,
            headers=headers,
            params={"metric": "sends"} if route.path == "/api/metrics/timeseries" else {},
        )
        assert response.status_code == 200, (route.path, response.text)
        assert not any(identity in response.text for identity in sentinels), (
            route.path,
            response.text,
        )
    # Eventos sem dono só existem no painel técnico de platform admin.
    with session_factory.begin() as session:
        session.add(Event(level="error", type="sistema", message="SENTINELA_SISTEMA"))
    assert "SENTINELA_SISTEMA" not in client.get("/api/events", headers=headers).text
    assert client.get("/api/niches", headers=headers).json()[0]["id"] != ids["niche_id"]
    assert all(
        row["id"] != ids["niche_id"] for row in client.get("/api/niches", headers=headers).json()
    )
    for path, key in (
        ("/api/expense-categories", "category_id"),
        ("/api/events", "event_id"),
        ("/api/audit-logs", "audit_id"),
    ):
        data = client.get(path, headers=headers).json()
        items = data["items"] if isinstance(data, dict) else data
        assert all(row["id"] != ids[key] for row in items)
    for path, key in (
        ("/api/users", "user_id"),
        ("/api/accounts", "account_id"),
        ("/api/niches", "niche_id"),
        ("/api/phones", "phone_id"),
        ("/api/groups", "group_id"),
        ("/api/bots", "bot_id"),
        ("/api/expenses", "expense_id"),
        ("/api/campaigns", "campaign_id"),
        ("/api/sales", "sale_id"),
        ("/api/alerts", "alert_id"),
        ("/api/events", "event_id"),
        ("/api/audit-logs", "audit_id"),
        ("/api/expense-categories", "category_id"),
    ):
        data = client.get(path, headers=headers).json()
        items = data["items"] if isinstance(data, dict) else data
        assert any(str(row["id"]) == str(b_ids[key]) for row in items), path

    # Um ajudante da mesma conta compartilha a operação, mas mantém autoria própria.
    helper = add_user(
        session_factory,
        email="ajudante@teste.com",
        role="admin",
        tenant_id=b.tenant_id,
        is_platform_admin=False,
    )
    helper_headers = auth_header(
        create_access_token(str(helper.id), session_version=helper.session_version)
    )
    assert client.get(f"/api/bots/{b_ids['bot_id']}", headers=helper_headers).status_code == 200
    assert (
        client.patch(
            f"/api/bots/{b_ids['bot_id']}", headers=helper_headers, json={"name": "Compartilhado"}
        ).status_code
        == 200
    )
    with session_factory() as session:
        audit = session.scalar(
            select(AuditLog)
            .where(AuditLog.entity_id == str(b_ids["bot_id"]))
            .order_by(AuditLog.id.desc())
        )
        assert audit.user_id == helper.id and audit.tenant_id == b.tenant_id


def test_criar_conta_e_usuario_sem_escalar_privilegios(client, session_factory, operations):
    (a, _, _), (b, _, _) = operations
    with session_factory.begin() as session:
        session.get(User, a.id).is_platform_admin = True
    headers = auth_header(create_access_token(str(a.id), session_version=a.session_version))
    payload = {
        "name": "Cliente novo",
        "admin_name": "Cliente",
        "admin_email": "novo@teste.com",
        "admin_password": "senha-segura",
    }
    created = client.post("/api/platform/tenants", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert not created.json()["is_internal"] and created.json()["users_count"] == 1
    assert payload["admin_password"] not in created.text
    assert client.post("/api/platform/tenants", headers=headers, json=payload).status_code == 409
    with session_factory() as session:
        admin = session.scalar(select(User).where(User.email == payload["admin_email"]))
        assert admin.role == "admin" and not admin.is_platform_admin
        assert str(admin.tenant_id) == created.json()["id"]
    b_headers = auth_header(create_access_token(str(b.id), session_version=b.session_version))
    created_user = client.post(
        "/api/users",
        headers=b_headers,
        json={"email": "ajudante2@teste.com", "password": "senha-segura", "role": "admin"},
    )
    assert created_user.status_code == 201 and not created_user.json()["is_platform_admin"]
    assert created_user.json()["tenant"]["id"] == str(b.tenant_id)
    for field, value in (("tenant_id", str(a.tenant_id)), ("is_platform_admin", True)):
        assert (
            client.patch(f"/api/users/{b.id}", headers=b_headers, json={field: value}).status_code
            == 422
        )


def test_platform_permissoes_e_suspensao(client, session_factory, operations):
    (a, ids, _), (b, _, _) = operations
    headers = auth_header(create_access_token(str(b.id), session_version=b.session_version))
    for method, path, body in (
        ("GET", "/api/platform/plans", None),
        ("POST", "/api/platform/plans", {"code": "novo", "name": "Novo"}),
        ("PATCH", f"/api/platform/plans/{uuid4()}", {"price": "100.00"}),
        ("PATCH", f"/api/platform/tenants/{a.tenant_id}/subscription", {"status": "active"}),
        ("GET", f"/api/platform/tenants/{a.tenant_id}/subscription/events", None),
        ("GET", "/api/platform/metrics", None),
        ("GET", "/api/platform/tenants", None),
        (
            "POST",
            "/api/platform/tenants",
            {
                "name": "Cliente",
                "admin_name": "Cliente",
                "admin_email": "novo@teste.com",
                "admin_password": "senha-segura",
            },
        ),
        ("PATCH", f"/api/platform/tenants/{a.tenant_id}", {"status": "suspended"}),
    ):
        assert client.request(method, path, headers=headers, json=body).status_code == 403
    with session_factory.begin() as session:
        session.get(User, a.id).is_platform_admin = True
    platform_headers = auth_header(
        create_access_token(str(a.id), session_version=a.session_version)
    )
    assert "SENTINELA" not in client.get("/api/auth/me", headers=headers).text
    assert client.get("/api/auth/me", headers=headers).json()["tenant"]["id"] == str(b.tenant_id)
    response = client.patch(
        f"/api/platform/tenants/{b.tenant_id}",
        headers=platform_headers,
        json={"status": "suspended"},
    )
    assert response.status_code == 200, response.text
    with session_factory() as session:
        assert session.get(Bot, ids["bot_id"]).status == "active"
        assert all(
            bot.status == "paused"
            for bot in session.scalars(select(Bot).where(Bot.owner_id == b.tenant_id))
        )
    login = client.post("/api/auth/login", json={"email": b.email, "password": "senha-segura"})
    assert login.status_code == 403 and login.json()["error"]["code"] == "TENANT_SUSPENDED"
    assert client.get("/api/auth/me", headers=headers).status_code == 403
    refresh = create_refresh_token(str(b.id), session_version=b.session_version)
    response = client.post(
        "/api/auth/refresh", headers={"cookie": f"{REFRESH_COOKIE_NAME}={refresh}"}
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "TENANT_SUSPENDED"
    assert (
        client.patch(
            f"/api/platform/tenants/{a.tenant_id}",
            headers=platform_headers,
            json={"status": "suspended"},
        ).status_code
        == 409
    )
