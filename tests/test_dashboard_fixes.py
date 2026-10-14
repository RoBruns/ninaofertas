# ruff: noqa: F401, F811
"""Regressões da auditoria do dashboard, usando somente o Postgres de teste."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.alerts import DETECTORS, detect_alerts, detect_sales_sync_stale
from core.metrics import MetricFilters
from core.models import Alert, AuditLog, AutomationRun, Bot, BotGroup, Event, Expense, Sale, User
from core.sales_sync import SyncResult, sync_account, sync_all_active_accounts
from tests.test_api import add_user, auth_header, client, login, session_factory
from tests.test_bots_api import safe_settings
from tests.test_metrics_api import _dataset, _overview
from tests.test_sales_sync import FIXTURES, MLDashboardClient, _account, _patch_sessions


def authenticate(client, factory):
    user = add_user(factory, email="dashboard-fixes@example.com", role="admin")
    return user, auth_header(str(login(client, user.email)["access_token"]))


@pytest.mark.parametrize("path,model", [("/api/events", Event), ("/api/audit-logs", AuditLog)])
def test_dia_inclusivo_em_brasilia_e_datetime_compativel(client, session_factory, path, model):
    user, headers = authenticate(client, session_factory)
    instants = ["2026-10-13T02:59:59+00:00", "2026-10-13T03:00:00+00:00",
                "2026-10-14T02:59:59+00:00", "2026-10-14T03:00:00+00:00"]
    with session_factory.begin() as session:
        for index, instant in enumerate(instants):
            values = {"tenant_id": user.tenant_id, "created_at": datetime.fromisoformat(instant)}
            if model is Event:
                values.update(level="info", type="boundary", message=str(index))
            else:
                values.update(user_id=user.id, entity_type="boundary", entity_id=str(index), action="update")
            session.add(model(**values))
    kind = {"type": "boundary"} if model is Event else {"entity_type": "boundary"}
    response = client.get(path, headers=headers, params={"from": "2026-10-13", "to": "2026-10-13", **kind})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    response = client.get(path, headers=headers, params={"from": instants[1], "to": instants[1], **kind})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1  # Datetime mantém o limite inclusivo original.


def test_saude_usa_concluida_e_avisa_running_travado(client, session_factory):
    user, headers = authenticate(client, session_factory)
    bot_id = uuid4()
    now = datetime.now(timezone.utc)
    with session_factory.begin() as session:
        session.add(Bot(id=bot_id, owner_id=user.id, name="Saúde", slug="saude", status="active", settings=safe_settings()))
        session.flush()
        session.add_all([
            AutomationRun(bot_id=bot_id, kind="cycle", status="success", started_at=now - timedelta(seconds=60), finished_at=now),
            AutomationRun(bot_id=bot_id, kind="cycle", status="running", started_at=now),
        ])
    url = f"/api/bots/{bot_id}/health"
    response = client.get(url, headers=headers)
    assert response.json()["status"] == "ok"
    assert response.json()["last_run_status"] == "success"
    assert response.json()["message"] == "Última execução concluída sem alertas"
    with session_factory.begin() as session:
        concluida = session.scalar(select(AutomationRun).where(AutomationRun.status == "success"))
        concluida.started_at = now - timedelta(seconds=1000)
        run = session.scalar(select(AutomationRun).where(AutomationRun.status == "running"))
        run.started_at = now - timedelta(seconds=901)
    assert client.get(url, headers=headers).json()["status"] == "warning"
    with session_factory.begin() as session:
        bot = session.get(Bot, bot_id)
        settings = safe_settings()
        settings["schedule"]["check_interval"] = 600
        bot.settings = settings
    assert client.get(url, headers=headers).json()["status"] == "ok"


def test_saude_ignora_running_orfao_de_worker_reiniciado(client, session_factory):
    user, headers = authenticate(client, session_factory)
    bot_id = uuid4()
    now = datetime.now(timezone.utc)
    with session_factory.begin() as session:
        session.add(Bot(id=bot_id, owner_id=user.id, name="Órfão", slug="orfao", status="active", settings=safe_settings()))
        session.flush()
        session.add_all([
            # Worker reiniciado no deploy de semanas atrás: ficou "running" para sempre.
            AutomationRun(bot_id=bot_id, kind="cycle", status="running", started_at=now - timedelta(days=19)),
            AutomationRun(bot_id=bot_id, kind="cycle", status="success", started_at=now - timedelta(seconds=60), finished_at=now),
        ])
    response = client.get(f"/api/bots/{bot_id}/health", headers=headers)
    assert response.json()["status"] == "ok", response.json()


def test_sync_sem_vendas_registra_historico_e_resolve_alerta(client, session_factory, monkeypatch):
    account = _account(session_factory, "mercadolivre", "cookie", "segredo-de-teste")
    _patch_sessions(monkeypatch, session_factory)
    detector = next(d for d in DETECTORS if d.name == "sales_sync_stale")
    detect_alerts(detectors=[detector])
    monkeypatch.setattr("core.sales_sync._sync_ml", lambda *_args: SyncResult(imported=0, skipped=4))
    sync_account(account.id)
    sync_all_active_accounts()
    detect_alerts(detectors=[detector])
    with session_factory() as session:
        assert detect_sales_sync_stale(session, datetime.now(timezone.utc)) == []
        assert session.scalar(select(Alert.status)) == "resolved"
        assert session.scalar(select(func.count()).select_from(Sale)) == 0
        owner = session.get(User, account.owner_id)
        email = owner.email
    headers = auth_header(str(login(client, email)["access_token"]))
    history = client.get("/api/sales/imports", headers=headers).json()
    assert {entry["source"] for entry in history} == {"sync_manual", "sync_automatic"}
    assert all(entry["account_id"] == str(account.id) and entry["skipped"] == 4 for entry in history)
    monkeypatch.setattr("core.sales_sync._sync_ml", lambda *_args: SyncResult(auth_expired=True))
    sync_account(account.id)
    assert len(client.get("/api/sales/imports", headers=headers).json()) == 2


@pytest.mark.parametrize("granularity,end,dates", [
    ("day", "2026-09-22", ["2026-09-20", "2026-09-21", "2026-09-22"]),
    ("week", "2026-10-01", ["2026-09-14", "2026-09-21", "2026-09-28"]),
    ("month", "2026-11-02", ["2026-09-01", "2026-10-01", "2026-11-01"]),
])
def test_timeseries_preenche_periodos_e_agrupa_data_local(client, session_factory, granularity, end, dates):
    user, headers = authenticate(client, session_factory)
    ids = _dataset(session_factory, user.id)
    with session_factory.begin() as session:
        session.add(Sale(owner_id=user.id, platform_id=ids["platform1"], external_id="boundary-sale",
                         gross_amount=Decimal("7"), commission=Decimal("1"), status="confirmed",
                         ordered_at=datetime(2026, 9, 22, 2, tzinfo=timezone.utc), source="manual"))
    response = client.get("/api/metrics/timeseries", headers=headers, params={
        "from": "2026-09-20", "to": end, "metric": "revenue", "granularity": granularity})
    assert response.status_code == 200, response.text
    points = response.json()["points"]
    assert [p["date"] for p in points] == dates
    assert sum(Decimal(p["value"]) for p in points) == Decimal("357")
    if granularity == "day":
        assert points[-1]["value"] == "0.00"
        assert points[1]["value"] == "7.00"


def test_quebras_sem_totais_duplicados_e_com_sem_atribuicao(client, session_factory):
    user, headers = authenticate(client, session_factory)
    ids = _dataset(session_factory, user.id)
    with session_factory.begin() as session:
        session.add_all([
            Sale(owner_id=user.id, platform_id=ids["platform1"], external_id="unassigned",
                 gross_amount=Decimal("20"), commission=Decimal("2"), status="confirmed",
                 ordered_at=datetime(2026, 9, 20, 12, tzinfo=timezone.utc), source="manual"),
            Expense(owner_id=user.id, description="Sem bot", amount=Decimal("12"), incurred_on=date(2026, 9, 20), source="manual"),
        ])
    params = {"from": "2026-09-20", "to": "2026-09-20"}
    def items(dimension):
        response = client.get(f"/api/metrics/by-{dimension}", headers=headers, params=params)
        assert response.status_code == 200, response.text
        return response.json()["items"]
    assert all(row["spend"] is None and row["profit"] is None for row in items("group"))
    assert all(row["sends"] is None for row in items("platform"))
    assert all(row["revenue"] is None for row in items("campaign"))
    bots = items("bot")
    unassigned = next(row for row in bots if row["id"] is None)
    assert unassigned["name"] == "Sem atribuição"
    assert unassigned["spend"] == "12.00"
    overview = _overview(client, headers)["kpis"]
    for metric in ["revenue", "commission", "spend", "profit"]:
        assert sum(Decimal(row[metric]) for row in bots) == Decimal(overview[metric]["value"])


def test_linhas_de_teste_tem_envios_reais_e_selo(client, session_factory):
    user, headers = authenticate(client, session_factory)
    ids = _dataset(session_factory, user.id)
    with session_factory.begin() as session:
        session.get(Bot, ids["bot1"]).is_test = True
        session.add(BotGroup(bot_id=ids["bot1"], group_id=ids["group1"], is_active=True))
    params = {"from": "2026-09-20", "to": "2026-09-20"}
    assert _overview(client, headers)["kpis"]["sends"]["value"] == 2
    for dimension, key in [("bot", "bot1"), ("group", "group1")]:
        response = client.get(f"/api/metrics/by-{dimension}", headers=headers, params=params)
        assert response.status_code == 200, response.text
        row = next(row for row in response.json()["items"] if row["id"] == str(ids[key]))
        assert row["sends"] == 3
        assert row["is_test"] is True


def test_ml_concilia_comissao_e_deduplica_por_data(session_factory, monkeypatch):
    account = _account(session_factory, "mercadolivre", "cookie", "segredo-de-teste")
    _patch_sessions(monkeypatch, session_factory)
    MLDashboardClient.html = (FIXTURES / "ml_dashboard.html").read_text(encoding="utf8")
    monkeypatch.setattr("core.sales_sync.httpx.Client", MLDashboardClient)
    monkeypatch.setattr("core.sales_sync.time.sleep", lambda _: None)
    from core.importers.mercadolivre import parse_dashboard
    rows, meta = parse_dashboard(MLDashboardClient.html)
    meta["commission_total"] = sum((row.commission for row in rows), Decimal("0"))
    meta["sales_total"] = Decimal("1889.00")  # Bruto diferente, comissão igual.
    monkeypatch.setattr("core.sales_sync.parse_dashboard", lambda _: (rows, meta))
    sync_account(account.id)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Event).where(Event.type == "ml_reconciliation_mismatch")) == 0
    meta["commission_total"] += Decimal("1")
    sync_account(account.id)
    sync_account(account.id)
    with session_factory() as session:
        events = list(session.scalars(select(Event).where(Event.type == "ml_reconciliation_mismatch")))
        assert len(events) == len({event.detail["date"] for event in events}) == 14
    detector = next(d for d in DETECTORS if d.name == "ml_reconciliation_mismatch")
    detect_alerts(detectors=[detector])
    detect_alerts(detectors=[detector])
    with session_factory.begin() as session:
        alerts = list(session.scalars(select(Alert)))
        assert len(alerts) == 14
        assert len({alert.dedup_key for alert in alerts}) == 14
        for alert in alerts:
            alert.status = "resolved"
    detect_alerts(detectors=[detector])
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 14


def test_comparacao_periodo_parcial_usa_mesmo_trecho_decorrido():
    end = datetime(2026, 10, 13, 15, tzinfo=timezone.utc)
    for start, delta in [(date(2026, 10, 13), 1), (date(2026, 10, 7), 7)]:
        filters = MetricFilters(start, date(2026, 10, 13), end_at=end)
        assert filters.previous.end_utc == end - timedelta(days=delta)
        assert filters.end_utc - filters.start_utc == filters.previous.end_utc - filters.previous.start_utc


def test_overview_compara_ate_mesmo_horario_do_dia_anterior(client, session_factory, monkeypatch):
    user, headers = authenticate(client, session_factory)
    ids = _dataset(session_factory, user.id)
    with session_factory.begin() as session:
        for day in [19, 20]:
            session.add(Sale(owner_id=user.id, platform_id=ids["platform1"], external_id=f"late-{day}",
                             gross_amount=Decimal("1000"), commission=Decimal("100"), status="confirmed",
                             ordered_at=datetime(2026, 9, day, 18, tzinfo=timezone.utc), source="manual"))
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 20, 16, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr("api.routers.metrics.datetime", FrozenDatetime)
    kpis = _overview(client, headers)["kpis"]
    assert kpis["revenue"]["value"] == "250.00"  # Venda às 23h30 locais ainda não ocorreu.
    assert kpis["revenue"]["previous"] == "50.00"
