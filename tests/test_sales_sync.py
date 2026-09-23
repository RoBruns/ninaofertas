# ruff: noqa: E402, F401, F811

from __future__ import annotations

import base64
import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("CREDENTIALS_KEY", base64.b64encode(b"s" * 32).decode())

from core import db
from core.credentials import store_credential
from core.importers.mercadolivre import parse_dashboard
from core.importers.shopee import fetch_conversion_report
from core.models import Command, Event, Platform, PlatformAccount, PlatformCredential, Sale, User
from core.sales_sync import sync_account
from tests.test_api import add_user, auth_header, client, login, session_factory
from worker import channels, commands, monitor
from worker.main import _registrar_jobs

FIXTURES = Path(__file__).parent / "fixtures"


def _patch_sessions(monkeypatch: pytest.MonkeyPatch, factory: sessionmaker[Session]) -> None:
    @contextmanager
    def get_test_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db, "get_session", get_test_session)


def _account(
    factory: sessionmaker[Session], slug: str, credential_kind: str, credential_value: str
) -> PlatformAccount:
    owner = add_user(factory, email=f"{slug}-{uuid4()}@example.com", role="admin")
    account_id = uuid4()
    with factory.begin() as session:
        platform = Platform(
            slug=slug,
            name=slug,
            is_active=True,
            capabilities={
                "commission_api": slug == "shopee",
                "commission_scrape": slug == "mercadolivre",
            },
        )
        session.add(platform)
        session.flush()
        account = PlatformAccount(
            id=account_id,
            owner_id=owner.id,
            platform_id=platform.id,
            label="Principal",
            external_id="app-fixture" if slug == "shopee" else None,
            status="active",
            config={},
        )
        session.add(account)
        session.flush()
        store_credential(session, account.id, credential_kind, credential_value)
    with factory() as session:
        return session.get(PlatformAccount, account_id)


class ShopeePagesClient:
    calls: list[bytes] = []
    pages: list[dict] = []

    def __init__(self, **_kwargs: object) -> None:
        self.index = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        content = bytes(kwargs["content"])
        self.calls.append(content)
        page = self.pages[self.index]
        self.index += 1
        return httpx.Response(200, json=page, request=httpx.Request("POST", url))


def test_shopee_pagina_mapeia_status_sub_id_e_decimais(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fixture = json.loads((FIXTURES / "shopee_conversion_report.json").read_text(encoding="utf-8"))
    ShopeePagesClient.calls = []
    ShopeePagesClient.pages = fixture["pages"]
    monkeypatch.setattr("core.importers.shopee.httpx.Client", ShopeePagesClient)
    caplog.set_level(logging.WARNING)

    rows = fetch_conversion_report(
        "app-fixture",
        "secret-fixture",
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 20, tzinfo=timezone.utc),
    )

    assert len(rows) == 4
    assert b'scrollId: \\"scroll-page-2\\"' in ShopeePagesClient.calls[1]
    assert rows[0].gross_amount == Decimal("190.60")
    assert rows[0].commission == Decimal("21.10")
    assert rows[0].quantity == 3
    assert rows[0].product_name == "Cafeteira +1"
    assert rows[0].sub_id == "bot-casa-grupo-1"
    assert [row.status for row in rows] == ["confirmed", "cancelled", "pending", "pending"]
    assert "NEW_STATUS_FROM_PLATFORM" in caplog.text


def test_ml_fixture_real_extrai_oito_vendas_e_purchase_id_nao_e_chave() -> None:
    html = (FIXTURES / "ml_dashboard.html").read_text(encoding="utf-8")
    rows, meta = parse_dashboard(html)

    assert len(rows) == 8
    assert sum((row.commission for row in rows), Decimal("0.00")) == Decimal("238.30")
    assert sum((row.gross_amount for row in rows), Decimal("0.00")) == Decimal("3198.80")
    assert meta["commission_total"] == Decimal("238.30")
    assert meta["sales_total"] == Decimal("3198.80")
    without_purchase_id = [row for row in rows if "purchaseId" not in row.raw]
    assert len(without_purchase_id) == 3
    assert all(row.external_id for row in without_purchase_id)
    assert rows[0].ordered_at == datetime(2026, 9, 22, 3, tzinfo=timezone.utc)


def test_ml_cancelamento_e_status_desconhecido_sao_tolerados(
    caplog: pytest.LogCaptureFixture,
) -> None:
    html = (FIXTURES / "ml_dashboard.html").read_text(encoding="utf-8")
    canceled_id = "2000018590788880"
    html = html.replace('"status": "IN_REVIEW"', '"status": "NOVO_STATUS"', 1).replace(
        '"canceledOrders": {"item_list": []',
        f'"canceledOrders": {{"item_list": [{{"id": "{canceled_id}"}}]',
    )
    caplog.set_level(logging.WARNING)

    rows, _ = parse_dashboard(html)
    assert rows[0].status == "cancelled"
    assert "NOVO_STATUS" not in caplog.text

    unknown_html = html.replace(
        f'"canceledOrders": {{"item_list": [{{"id": "{canceled_id}"}}]',
        '"canceledOrders": {"item_list": []',
    )
    rows, _ = parse_dashboard(unknown_html)
    assert rows[0].status == "pending"
    assert "NOVO_STATUS" in caplog.text


class MLDashboardClient:
    html = ""
    headers: dict[str, str] = {}
    ranges: list[str] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).headers = dict(kwargs.get("headers") or {})

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        params = dict(kwargs.get("params") or {})
        type(self).ranges.append(str(params.get("filter_time_range") or ""))
        return httpx.Response(200, text=self.html, request=httpx.Request("GET", url))


def test_ml_reimporta_sem_duplicar_e_atualiza_status(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    sentinel = "SENTINELA-cookie-ml-nao-vazar"
    account = _account(session_factory, "mercadolivre", "cookie", sentinel)
    _patch_sessions(monkeypatch, session_factory)
    MLDashboardClient.html = (FIXTURES / "ml_dashboard.html").read_text(encoding="utf-8")
    MLDashboardClient.ranges = []
    monkeypatch.setattr("core.sales_sync.httpx.Client", MLDashboardClient)
    monkeypatch.setattr("core.sales_sync.time.sleep", lambda _seconds: None)

    first = sync_account(account.id)
    second = sync_account(account.id)
    assert first.imported == 8
    assert second.imported == 0
    assert len(MLDashboardClient.ranges) == 28
    assert all(
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T00:00:00\.000-03:00--"
            r"\d{4}-\d{2}-\d{2}T00:00:00\.000-03:00",
            value,
        )
        for value in MLDashboardClient.ranges
    )
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 8

    MLDashboardClient.html = MLDashboardClient.html.replace(
        '"status": "IN_REVIEW"', '"status": "APPROVED"', 1
    )
    changed = sync_account(account.id)
    assert changed.imported == 1
    with session_factory() as session:
        sale = session.scalar(select(Sale).where(Sale.external_id == "2000018590788880"))
        assert sale.status == "confirmed"
        assert sale.source == "scrape"
    assert MLDashboardClient.headers["Cookie"] == sentinel


def test_ml_sessao_expirada_invalida_credencial_sem_vazar(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "SENTINELA-cookie-expirado-nao-vazar"
    account = _account(session_factory, "mercadolivre", "cookie", sentinel)
    _patch_sessions(monkeypatch, session_factory)
    MLDashboardClient.html = "<html>login</html>"
    monkeypatch.setattr("core.sales_sync.httpx.Client", MLDashboardClient)
    caplog.set_level(logging.DEBUG)

    result = sync_account(account.id)
    assert result.auth_expired is True
    with session_factory() as session:
        credential = session.scalar(select(PlatformCredential))
        event = session.scalar(select(Event).where(Event.type == "auth_expired"))
        assert credential.status == "invalid"
        assert event is not None
        serialized = json.dumps(
            {"last_error": credential.last_error, "event": event.detail}, default=str
        )
    assert sentinel not in serialized
    assert sentinel not in caplog.text


def test_ml_truncado_emite_event(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    account = _account(session_factory, "mercadolivre", "cookie", "cookie-seguro")
    _patch_sessions(monkeypatch, session_factory)
    MLDashboardClient.html = (
        (FIXTURES / "ml_dashboard.html")
        .read_text(encoding="utf-8")
        .replace(
            '"total_results": 8, "order_by": "ORD_DATE_CREATED"',
            '"total_results": 11, "order_by": "ORD_DATE_CREATED"',
        )
    )
    monkeypatch.setattr("core.sales_sync.httpx.Client", MLDashboardClient)
    monkeypatch.setattr("core.sales_sync.time.sleep", lambda _seconds: None)

    sync_account(account.id)
    with session_factory() as session:
        events = list(session.scalars(select(Event).where(Event.type == "ml_sales_truncated")))
    assert len(events) == 14
    assert events[0].detail["total_results"] == 11
    assert events[0].detail["items"] == 8


def test_endpoint_sync_aceita_capacidade_de_scrape(
    client: object,
    session_factory: sessionmaker[Session],
) -> None:
    account = _account(session_factory, "mercadolivre", "cookie", "cookie-seguro")
    with session_factory() as session:
        owner = session.get(User, account.owner_id)
    headers = auth_header(str(login(client, owner.email)["access_token"]))

    response = client.post(
        "/api/sales/sync",
        headers=headers,
        json={"account_id": str(account.id)},
    )
    assert response.status_code == 202
    with session_factory() as session:
        command = session.get(Command, response.json()["command_id"])
    assert command.type == "commission_import"
    assert command.payload == {"account_id": str(account.id)}


def test_comando_de_importacao_falho_nao_impede_ciclo_de_ofertas(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    capfd: pytest.CaptureFixture[str],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    account_id = uuid4()
    with session_factory.begin() as session:
        session.add_all(
            [
                Command(
                    type="commission_import",
                    payload={"account_id": str(account_id)},
                    status="pending",
                ),
                Command(type="reload_config", payload={}, status="pending"),
            ]
        )
    sentinel = "SENTINELA-cookie-comando-nao-vazar"
    monkeypatch.setattr(
        commands,
        "sync_account",
        lambda _id: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )

    cycle_ran: list[bool] = []
    monkeypatch.setattr(channels, "bot_atual", lambda: None)
    monkeypatch.setattr(monitor, "bot_atual", lambda: None)
    monkeypatch.setattr(
        monitor,
        "_executar_ciclo",
        lambda: cycle_ran.append(True) or (0, 0, False),
    )
    monkeypatch.setattr(monitor.telemetry, "iniciar_ciclo", lambda *_args: None)
    monkeypatch.setattr(monitor.telemetry, "finalizar_ciclo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor.telemetry, "heartbeat", lambda *_args: None)

    monitor.ciclo()
    with session_factory() as session:
        stored_commands = list(session.scalars(select(Command).order_by(Command.id)))
        event = session.scalar(select(Event).where(Event.type == "commission_import_failed"))
    captured = capfd.readouterr()
    assert [command.status for command in stored_commands] == ["failed", "done"]
    assert event is not None
    assert cycle_ran == [True]
    assert sentinel not in captured.out + captured.err
    assert sentinel not in str(stored_commands[0].result)
    assert sentinel not in event.message
    assert sentinel not in json.dumps(event.detail)


class SchedulerSpy:
    def __init__(self) -> None:
        self.jobs: list[tuple[object, str, dict[str, object]]] = []

    def add_job(self, function: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append((function, trigger, kwargs))


def test_job_diario_registrado_as_seis_com_max_instances_um() -> None:
    scheduler = SchedulerSpy()
    _registrar_jobs(scheduler, ("achadinhos",), datetime(2026, 9, 23, 5, 0))
    daily = next(job for job in scheduler.jobs if job[2]["id"] == "sales-sync-daily")
    assert daily[1] == "cron"
    assert daily[2]["hour"] == 6
    assert daily[2]["minute"] == 0
    assert daily[2]["max_instances"] == 1
