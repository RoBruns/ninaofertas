# ruff: noqa: E402, F401, F811

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from core.models import (
    Bot,
    Campaign,
    Click,
    Envio,
    Expense,
    ExpenseCategory,
    Group,
    GroupJoin,
    Niche,
    Oferta,
    Phone,
    Platform,
    PlatformAccount,
    Sale,
)
from core.metrics import MetricFilters, calculate_spend_by_category
from tests.test_api import add_user, auth_header, client, login, session_factory

# Consultas SQL que o /api/metrics/overview pode fazer. O número é constante (não
# cresce com o volume de dados): 11 sem as tabelas legadas, 13 com `ofertas`/`envios`
# presentes, como em produção (checagem de existência + envios do período atual e
# do anterior). Uma de folga; qualquer N+1 estoura na hora.
OVERVIEW_QUERY_BUDGET = 14


def _auth(test_client: object, factory: sessionmaker[Session], role: str = "viewer"):
    user = add_user(factory, email=f"metrics-{role}@example.com", role=role)
    token = str(login(test_client, user.email)["access_token"])
    return user, auth_header(token)


def _sale(
    owner_id: UUID,
    platform_id: int,
    account_id: UUID,
    bot_id: UUID,
    group_id: UUID,
    external_id: str,
    status: str,
    gross: str,
    commission: str,
    ordered_at: datetime,
    buyer_hash: str | None,
) -> Sale:
    return Sale(
        id=uuid4(),
        owner_id=owner_id,
        account_id=account_id,
        platform_id=platform_id,
        external_id=external_id,
        bot_id=bot_id,
        group_id=group_id,
        quantity=1,
        gross_amount=Decimal(gross),
        commission=Decimal(commission),
        status=status,
        buyer_hash=buyer_hash,
        ordered_at=ordered_at,
        source="manual",
    )


def _dataset(factory: sessionmaker[Session], owner_id: UUID) -> dict[str, object]:
    ids = {
        name: uuid4()
        for name in (
            "phone1",
            "phone2",
            "bot1",
            "bot2",
            "group1",
            "group2",
            "account1",
            "account2",
            "campaign1",
            "campaign2",
        )
    }
    with factory.begin() as session:
        # O banco vazio de testes preserva a regra das migrations e nao cria as
        # tabelas legadas. Este teste as materializa como existem em producao.
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)
        niche1 = Niche(owner_id=owner_id, slug="casa", name="Casa")
        niche2 = Niche(owner_id=owner_id, slug="tech", name="Tecnologia")
        platform1 = Platform(slug="shopee", name="Shopee", is_active=True, capabilities={})
        platform2 = Platform(
            slug="mercadolivre", name="Mercado Livre", is_active=True, capabilities={}
        )
        session.add_all([niche1, niche2, platform1, platform2])
        session.flush()
        ids.update(
            niche1=niche1.id, niche2=niche2.id, platform1=platform1.id, platform2=platform2.id
        )
        session.add_all(
            [
                Phone(
                    id=ids["phone1"],
                    owner_id=owner_id,
                    label="P1",
                    number="551100000001",
                    status="connected",
                ),
                Phone(
                    id=ids["phone2"],
                    owner_id=owner_id,
                    label="P2",
                    number="551100000002",
                    status="connected",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                Bot(
                    id=ids["bot1"],
                    owner_id=owner_id,
                    name="Bot Casa",
                    slug="casa",
                    niche_id=niche1.id,
                    phone_id=ids["phone1"],
                    status="active",
                    settings={},
                ),
                Bot(
                    id=ids["bot2"],
                    owner_id=owner_id,
                    name="Bot Tech",
                    slug="tech",
                    niche_id=niche2.id,
                    phone_id=ids["phone2"],
                    status="active",
                    settings={},
                ),
                Group(
                    id=ids["group1"],
                    owner_id=owner_id,
                    phone_id=ids["phone1"],
                    whatsapp_id="g1@g.us",
                    name="Grupo Casa",
                    status="active",
                ),
                Group(
                    id=ids["group2"],
                    owner_id=owner_id,
                    phone_id=ids["phone2"],
                    whatsapp_id="g2@g.us",
                    name="Grupo Tech",
                    status="active",
                ),
                PlatformAccount(
                    id=ids["account1"],
                    owner_id=owner_id,
                    platform_id=platform1.id,
                    label="Shopee 1",
                    status="active",
                    config={},
                ),
                PlatformAccount(
                    id=ids["account2"],
                    owner_id=owner_id,
                    platform_id=platform2.id,
                    label="ML 1",
                    status="active",
                    config={},
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                Campaign(
                    id=ids["campaign1"],
                    owner_id=owner_id,
                    name="Campanha Casa",
                    bot_id=ids["bot1"],
                    niche_id=niche1.id,
                    status="active",
                ),
                Campaign(
                    id=ids["campaign2"],
                    owner_id=owner_id,
                    name="Campanha Tech",
                    bot_id=ids["bot2"],
                    niche_id=niche2.id,
                    status="active",
                ),
            ]
        )
        traffic = ExpenseCategory(owner_id=owner_id, slug="trafego", name="Trafego")
        infra = ExpenseCategory(owner_id=owner_id, slug="infra", name="Infra")
        centavos = ExpenseCategory(owner_id=owner_id, slug="centavos", name="Centavos")
        session.add_all([traffic, infra, centavos])
        session.flush()
        ids.update(traffic=traffic.id, infra=infra.id)
        current = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)
        session.add_all(
            [
                _sale(
                    owner_id,
                    platform1.id,
                    ids["account1"],
                    ids["bot1"],
                    ids["group1"],
                    "confirmed",
                    "confirmed",
                    "100.00",
                    "10.00",
                    datetime(2026, 9, 21, 2, 30, tzinfo=timezone.utc),
                    "buyer-a",
                ),
                _sale(
                    owner_id,
                    platform1.id,
                    ids["account1"],
                    ids["bot1"],
                    ids["group1"],
                    "paid",
                    "paid",
                    "50.00",
                    "5.00",
                    current,
                    "buyer-b",
                ),
                _sale(
                    owner_id,
                    platform1.id,
                    ids["account1"],
                    ids["bot1"],
                    ids["group1"],
                    "pending",
                    "pending",
                    "999.00",
                    "3.00",
                    current,
                    None,
                ),
                _sale(
                    owner_id,
                    platform1.id,
                    ids["account1"],
                    ids["bot1"],
                    ids["group1"],
                    "cancelled",
                    "cancelled",
                    "999.00",
                    "999.00",
                    current,
                    "ignored",
                ),
                _sale(
                    owner_id,
                    platform2.id,
                    ids["account2"],
                    ids["bot2"],
                    ids["group2"],
                    "other",
                    "confirmed",
                    "200.00",
                    "20.00",
                    current,
                    None,
                ),
                _sale(
                    owner_id,
                    platform1.id,
                    ids["account1"],
                    ids["bot1"],
                    ids["group1"],
                    "previous",
                    "confirmed",
                    "50.00",
                    "5.00",
                    datetime(2026, 9, 19, 15, tzinfo=timezone.utc),
                    "previous-buyer",
                ),
            ]
        )
        expense_rows = [
            (
                "Trafego casa",
                "30.10",
                traffic.id,
                ids["campaign1"],
                ids["bot1"],
                platform1.id,
                niche1.id,
                date(2026, 9, 20),
            ),
            (
                "Infra casa",
                "10.20",
                infra.id,
                None,
                ids["bot1"],
                platform1.id,
                niche1.id,
                date(2026, 9, 20),
            ),
            (
                "Centavo A",
                "0.10",
                centavos.id,
                None,
                ids["bot1"],
                platform1.id,
                niche1.id,
                date(2026, 9, 20),
            ),
            (
                "Centavo B",
                "0.20",
                centavos.id,
                None,
                ids["bot1"],
                platform1.id,
                niche1.id,
                date(2026, 9, 20),
            ),
            (
                "Trafego tech",
                "60.00",
                traffic.id,
                ids["campaign2"],
                ids["bot2"],
                platform2.id,
                niche2.id,
                date(2026, 9, 20),
            ),
            (
                "Anterior",
                "10.00",
                traffic.id,
                ids["campaign1"],
                ids["bot1"],
                platform1.id,
                niche1.id,
                date(2026, 9, 19),
            ),
        ]
        for (
            description,
            amount,
            category_id,
            campaign_id,
            bot_id,
            platform_id,
            niche_id,
            incurred_on,
        ) in expense_rows:
            session.add(
                Expense(
                    id=uuid4(),
                    owner_id=owner_id,
                    description=description,
                    amount=Decimal(amount),
                    incurred_on=incurred_on,
                    category_id=category_id,
                    campaign_id=campaign_id,
                    bot_id=bot_id,
                    platform_id=platform_id,
                    niche_id=niche_id,
                    source="manual",
                )
            )
        for index in range(3):
            first = index < 2
            session.add(
                GroupJoin(
                    group_id=ids["group1"] if first else ids["group2"],
                    bot_id=ids["bot1"] if first else ids["bot2"],
                    campaign_id=ids["campaign1"] if first else ids["campaign2"],
                    joined_at=current,
                    source="manual",
                )
            )
        for index in range(10):
            first = index < 4
            session.add(
                Click(
                    sub_id=f"click-{index}",
                    bot_id=ids["bot1"] if first else ids["bot2"],
                    group_id=ids["group1"] if first else ids["group2"],
                    clicked_at=current,
                )
            )
        oferta = Oferta(nome="Oferta", preco=10, url="https://example.test/oferta")
        session.add(oferta)
        session.flush()
        for index in range(6):
            success = index < 5
            first = index < 3
            session.add(
                Envio(
                    oferta_id=oferta.id,
                    enviado_em=current.replace(tzinfo=None),
                    grupo="g",
                    mensagem="m",
                    status="sucesso" if success else "erro",
                    bot_id=ids["bot1"] if first else ids["bot2"],
                    group_id=ids["group1"] if first else ids["group2"],
                )
            )
    return ids


def _overview(test_client: object, headers: dict[str, str], **params: object) -> dict[str, object]:
    response = test_client.get(
        "/api/metrics/overview",
        headers=headers,
        params={"from": "2026-09-20", "to": "2026-09-20", **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_overview_confere_todas_as_formulas_previous_e_fuso(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    user, headers = _auth(client, session_factory)
    _dataset(session_factory, user.id)
    # Desempenho medido pelo que o código controla: o número de consultas.
    # Tempo de relógio aqui inclui a rede até o banco (~150 ms por ida e volta
    # pelo túnel local, ~1 ms dentro da Railway), então só diz onde o teste
    # rodou. O orçamento de consultas pega a regressão real (N+1).
    consultas = {"n": 0}

    def _contar(*_args: object, **_kwargs: object) -> None:
        consultas["n"] += 1

    engine = session_factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", _contar)
    started_at = perf_counter()
    try:
        body = _overview(client, headers)
    finally:
        event.remove(engine, "before_cursor_execute", _contar)
    overview_seconds = perf_counter() - started_at
    assert consultas["n"] <= OVERVIEW_QUERY_BUDGET, (
        f"overview fez {consultas['n']} consultas; orçamento é {OVERVIEW_QUERY_BUDGET}"
    )
    # Com o banco na mesma rede (deploy), vale também o tempo de relógio.
    if os.getenv("METRICS_LATENCY_CHECK") == "1":
        assert overview_seconds < 0.5
    kpis = body["kpis"]
    assert body["period"] == {"from": "2026-09-20", "to": "2026-09-20"}
    assert kpis["revenue"]["value"] == "350.00"
    assert kpis["commission"]["value"] == "35.00"
    assert kpis["commission_pending"]["value"] == "3.00"
    assert kpis["orders"]["value"] == 3
    assert kpis["buyers"]["value"] == 2
    assert kpis["spend"]["value"] == "100.60"
    assert kpis["traffic_spend"]["value"] == "90.10"
    assert kpis["profit"]["value"] == "-65.60"
    assert Decimal(str(kpis["roi"]["value"])) == Decimal("-0.6521")
    assert Decimal(str(kpis["roas"]["value"])) == Decimal("3.8846")
    assert kpis["cost_per_sale"]["value"] == "33.53"
    assert kpis["cost_per_buyer"]["value"] == "50.30"
    assert kpis["cost_per_join"]["value"] == "30.03"
    assert kpis["group_joins"]["value"] == 3
    assert kpis["sends"]["value"] == 5
    assert kpis["clicks"]["value"] == 10
    assert Decimal(str(kpis["conversion"]["value"])) == Decimal("0.3000")
    assert kpis["revenue"]["previous"] == "50.00"
    assert kpis["revenue"]["change_pct"] == 600.0

    with session_factory() as session:
        categories, _warnings = calculate_spend_by_category(
            session,
            user.id,
            MetricFilters(from_date=date(2026, 9, 20), to_date=date(2026, 9, 20)),
        )
    assert categories["centavos"] == Decimal("0.30")

    series = client.get(
        "/api/metrics/timeseries",
        headers=headers,
        params={
            "from": "2026-09-20",
            "to": "2026-09-20",
            "metric": "revenue",
            "granularity": "day",
        },
    )
    assert series.status_code == 200, series.text
    assert series.json()["points"] == [{"date": "2026-09-20", "value": "350.00"}]


def test_zero_em_todos_os_denominadores_e_dados_ausentes_sao_null(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    _user, headers = _auth(client, session_factory)
    body = _overview(client, headers)
    kpis = body["kpis"]
    for metric in ("roi", "roas", "cost_per_sale", "cost_per_buyer", "cost_per_join", "conversion"):
        assert kpis[metric]["value"] is None
    assert kpis["buyers"]["value"] is None
    assert kpis["clicks"]["value"] is None
    assert kpis["revenue"]["previous"] is None
    assert kpis["revenue"]["change_pct"] is None
    assert any("buyer_hash" in warning for warning in body["warnings"])
    assert any("cliques" in warning for warning in body["warnings"])


def test_filtros_isolados_combinados_warnings_breakdown_e_viewer(
    client: object, session_factory: sessionmaker[Session]
) -> None:
    user, headers = _auth(client, session_factory, role="viewer")
    ids = _dataset(session_factory, user.id)
    cases = (
        ({"bot_id": ids["bot1"]}, "150.00", "40.60"),
        ({"platform_id": ids["platform1"]}, "150.00", "40.60"),
        ({"account_id": ids["account1"]}, "150.00", "100.60"),
        ({"group_id": ids["group1"]}, "150.00", "100.60"),
        ({"campaign_id": ids["campaign1"]}, "350.00", "30.10"),
        ({"niche_id": ids["niche1"]}, "150.00", "40.60"),
        ({"phone_id": ids["phone1"]}, "150.00", "40.60"),
    )
    for params, revenue, spend in cases:
        body = _overview(client, headers, **params)
        assert body["kpis"]["revenue"]["value"] == revenue
        assert body["kpis"]["spend"]["value"] == spend
    ignored = _overview(client, headers, group_id=ids["group1"])
    assert any("group_id" in warning and "despesas" in warning for warning in ignored["warnings"])
    combined = _overview(client, headers, bot_id=ids["bot1"], platform_id=ids["platform2"])
    assert combined["kpis"]["revenue"]["value"] == "0.00"
    assert combined["kpis"]["spend"]["value"] == "0.00"
    without_buyer = _overview(client, headers, bot_id=ids["bot2"])
    assert without_buyer["kpis"]["orders"]["value"] == 1
    assert without_buyer["kpis"]["buyers"]["value"] is None
    assert without_buyer["kpis"]["cost_per_buyer"]["value"] is None
    assert any("buyer_hash" in warning for warning in without_buyer["warnings"])

    breakdown = client.get(
        "/api/metrics/by-bot",
        headers=headers,
        params={"from": "2026-09-20", "to": "2026-09-20"},
    )
    assert breakdown.status_code == 200, breakdown.text
    items = breakdown.json()["items"]
    assert [item["name"] for item in items] == ["Bot Tech", "Bot Casa"]
    assert [item["profit"] for item in items] == ["-40.00", "-25.60"]

    funnel = client.get(
        "/api/metrics/funnel",
        headers=headers,
        params={"from": "2026-09-20", "to": "2026-09-20"},
    )
    assert funnel.status_code == 200
    assert funnel.json()["sends"] == 5
