# ruff: noqa: E402, F401, F811

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from api.routers.sales import recognized_revenue_statement
from core.models import (
    Bot,
    Campaign,
    ExpenseCategory,
    GroupJoin,
    Niche,
    Platform,
    PlatformAccount,
    Sale,
)
from tests.test_api import (
    add_user,
    assert_error,
    auth_header,
    client,
    login,
    session_factory,
)


def _headers(
    test_client: object, factory: sessionmaker[Session], role: str = "admin"
) -> tuple[object, dict[str, str]]:
    user = add_user(factory, email=f"{role}@example.com", role=role)
    token = str(login(test_client, user.email)["access_token"])
    return user, auth_header(token)


def _catalog(factory: sessionmaker[Session], owner_id: object) -> dict[str, object]:
    bot_id = uuid4()
    account_id = uuid4()
    with factory.begin() as session:
        niche = Niche(owner_id=owner_id, slug="casa", name="Casa")
        shopee = Platform(
            slug="shopee",
            name="Shopee",
            is_active=True,
            capabilities={"commission_api": True},
        )
        ml = Platform(
            slug="mercadolivre",
            name="Mercado Livre",
            is_active=True,
            capabilities={"commission_api": False},
        )
        session.add_all([niche, shopee, ml])
        session.flush()
        bot = Bot(
            id=bot_id,
            owner_id=owner_id,
            name="Bot Casa",
            slug="bot-casa",
            status="active",
            settings={},
        )
        session.add(bot)
        session.flush()
        campaign = Campaign(
            id=uuid4(), owner_id=owner_id, name="Meta Casa", bot_id=bot_id, status="active"
        )
        category = ExpenseCategory(owner_id=owner_id, slug="trafego", name="Trafego")
        account = PlatformAccount(
            id=account_id,
            owner_id=owner_id,
            platform_id=ml.id,
            label="ML",
            status="active",
            config={},
        )
        session.add_all([campaign, category, account])
        session.flush()
        result = {
            "niche_id": niche.id,
            "shopee_id": shopee.id,
            "ml_id": ml.id,
            "bot_id": bot_id,
            "campaign_id": campaign.id,
            "category_id": category.id,
            "ml_account_id": account_id,
        }
    return result


def _sales_csv(rows: list[str]) -> bytes:
    header = "order_id,product_name,quantity,gross_amount,commission,status,ordered_at,bot_id\n"
    return (header + "\n".join(rows) + "\n").encode()


def _import(
    test_client: object, headers: dict[str, str], platform_id: int, csv_data: bytes
) -> object:
    return test_client.post(
        "/api/sales/import",
        headers=headers,
        data={"platform_id": str(platform_id)},
        files={"file": ("sales.csv", csv_data, "text/csv")},
    )


def test_despesa_manual_completa_preserva_centavos_e_viewer_nao_cria(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    admin, headers = _headers(client, session_factory)
    catalog = _catalog(session_factory, admin.id)
    payload = {
        "description": "Anuncio Meta",
        "amount": "1234.56",
        "incurred_on": "2026-09-20",
        "category_id": catalog["category_id"],
        "platform_id": catalog["shopee_id"],
        "campaign_id": str(catalog["campaign_id"]),
        "bot_id": str(catalog["bot_id"]),
        "niche_id": catalog["niche_id"],
        "notes": "Todos os campos do produto",
    }
    created = client.post("/api/expenses", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["amount"] == "1234.56"
    listed = client.get("/api/expenses", headers=headers)
    assert listed.json()["items"][0]["amount"] == "1234.56"

    negative = client.post(
        "/api/expenses",
        headers=headers,
        json={"description": "Invalida", "amount": "-0.01", "incurred_on": "2026-09-20"},
    )
    assert_error(negative, 422, "VALIDATION_ERROR")
    assert "amount deve ser >= 0" in negative.text

    viewer, viewer_headers = _headers(client, session_factory, "viewer")
    denied = client.post(
        "/api/expenses",
        headers=viewer_headers,
        json={"description": "Negada", "amount": "1.00", "incurred_on": "2026-09-20"},
    )
    assert viewer.id
    assert_error(denied, 403, "FORBIDDEN")


def test_importacao_idempotente_e_atualiza_status_sem_duplicar(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    admin, headers = _headers(client, session_factory)
    catalog = _catalog(session_factory, admin.id)
    pending = _sales_csv(
        [f"ORDER-1,Produto,1,100.00,10.25,pending,2026-09-10T12:00:00Z,{catalog['bot_id']}"]
    )
    first = _import(client, headers, int(catalog["shopee_id"]), pending)
    second = _import(client, headers, int(catalog["shopee_id"]), pending)
    assert first.status_code == second.status_code == 200
    assert first.json() == {"imported": 1, "skipped": 0, "errors": []}
    assert second.json() == {"imported": 0, "skipped": 1, "errors": []}

    confirmed = pending.replace(b",pending,", b",confirmed,")
    updated = _import(client, headers, int(catalog["shopee_id"]), confirmed)
    assert updated.status_code == 200, updated.text
    assert updated.json()["imported"] == 1
    with session_factory() as session:
        sales = list(session.scalars(select(Sale)))
        assert len(sales) == 1
        assert sales[0].status == "confirmed"
        assert sales[0].commission == Decimal("10.25")


def test_csv_com_erro_na_linha_tres_nao_importa_nada(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    admin, headers = _headers(client, session_factory)
    catalog = _catalog(session_factory, admin.id)
    csv_data = _sales_csv(
        [
            f"A,Um,1,10.00,1.00,pending,2026-09-01T10:00:00Z,{catalog['bot_id']}",
            f"B,Dois,1,INVALIDO,2.00,pending,2026-09-02T10:00:00Z,{catalog['bot_id']}",
            f"C,Tres,1,30.00,3.00,pending,2026-09-03T10:00:00Z,{catalog['bot_id']}",
            f"D,Quatro,1,40.00,4.00,pending,2026-09-04T10:00:00Z,{catalog['bot_id']}",
            f"E,Cinco,1,50.00,5.00,pending,2026-09-05T10:00:00Z,{catalog['bot_id']}",
        ]
    )
    response = _import(client, headers, int(catalog["shopee_id"]), csv_data)
    assert_error(response, 422, "VALIDATION_ERROR")
    assert "line_3" in response.json()["error"]["fields"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 0


def test_cancelada_nao_e_receita_filtros_combinam_e_sync_sem_api_e_util(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    admin, headers = _headers(client, session_factory)
    catalog = _catalog(session_factory, admin.id)
    bot_id = catalog["bot_id"]
    with session_factory.begin() as session:
        common = {
            "owner_id": admin.id,
            "platform_id": catalog["shopee_id"],
            "bot_id": bot_id,
            "quantity": 1,
            "gross_amount": Decimal("100.00"),
            "ordered_at": datetime(2026, 9, 10, 12, tzinfo=timezone.utc),
            "source": "csv_import",
        }
        session.add_all(
            [
                Sale(
                    id=uuid4(),
                    external_id="CONFIRMED",
                    commission=Decimal("10.00"),
                    status="confirmed",
                    **common,
                ),
                Sale(
                    id=uuid4(),
                    external_id="CANCELLED",
                    commission=Decimal("999.00"),
                    status="cancelled",
                    **common,
                ),
            ]
        )
    with session_factory() as session:
        assert session.scalar(recognized_revenue_statement(admin.id)) == Decimal("10.00")

    filtered = client.get(
        "/api/sales",
        headers=headers,
        params={
            "from": date(2026, 9, 10).isoformat(),
            "to": date(2026, 9, 10).isoformat(),
            "platform_id": catalog["shopee_id"],
            "bot_id": str(bot_id),
            "status": "confirmed",
        },
    )
    assert filtered.status_code == 200
    assert [item["external_id"] for item in filtered.json()["items"]] == ["CONFIRMED"]

    unsupported = client.post(
        "/api/sales/sync",
        headers=headers,
        json={"account_id": str(catalog["ml_account_id"])},
    )
    assert unsupported.status_code == 501
    assert "CSV" in unsupported.json()["error"]["message"]


def test_metricas_de_campanha_devolvem_null_sem_entradas(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    admin, headers = _headers(client, session_factory)
    catalog = _catalog(session_factory, admin.id)
    expense = client.post(
        "/api/expenses",
        headers=headers,
        json={
            "description": "Trafego da campanha",
            "amount": "100.00",
            "incurred_on": "2026-09-10",
            "campaign_id": str(catalog["campaign_id"]),
        },
    )
    assert expense.status_code == 201, expense.text
    no_joins = client.get(
        f"/api/campaigns/{catalog['campaign_id']}/metrics",
        headers=headers,
        params={"from": "2026-09-01", "to": "2026-09-30"},
    )
    assert no_joins.status_code == 200
    assert no_joins.json() == {
        "campaign_id": str(catalog["campaign_id"]),
        "spend": "100.00",
        "group_joins": 0,
        "cost_per_join": None,
    }
    with session_factory.begin() as session:
        session.add_all(
            [
                GroupJoin(
                    campaign_id=catalog["campaign_id"],
                    joined_at=datetime(2026, 9, day, tzinfo=timezone.utc),
                    source="manual",
                )
                for day in (11, 12)
            ]
        )
    metrics = client.get(f"/api/campaigns/{catalog['campaign_id']}/metrics", headers=headers)
    assert metrics.json()["cost_per_join"] == "50.00"


def test_openapi_expoe_rotas_da_fase_oito(client: object) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    expected = {
        "/api/expenses",
        "/api/expense-categories",
        "/api/expenses/import",
        "/api/campaigns",
        "/api/campaigns/{campaign_id}/metrics",
        "/api/sales",
        "/api/sales/import",
        "/api/sales/sync",
        "/api/sales/imports",
    }
    assert expected <= set(paths)
