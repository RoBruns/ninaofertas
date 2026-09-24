# ruff: noqa: F401, F811
"""Fase 10: alertas e observabilidade contra Postgres real."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core import db
from core.alerts import (
    DETECTORS,
    Detector,
    cleanup_events,
    detect_alerts,
    detect_auth_expired,
    detect_auth_expiring,
    detect_automation_failing,
    detect_bot_offline,
    detect_group_inaccessible,
    detect_ml_reconciliation_mismatch,
    detect_ml_sales_truncated,
    detect_recurring_error,
    detect_sales_sync_stale,
    detect_send_failed,
    detect_traffic_spend_stale,
)
from core.models import (
    Alert,
    AuditLog,
    AutomationRun,
    Bot,
    BotGroup,
    Envio,
    Event,
    Expense,
    ExpenseCategory,
    Group,
    Oferta,
    Platform,
    PlatformAccount,
    PlatformCredential,
    Sale,
)
from tests.test_api import add_user, auth_header, client, login, session_factory
from tests.test_bots_api import safe_settings


def _auth_detector():
    return next(detector for detector in DETECTORS if detector.name == "auth_expired")


def _credential(
    factory: sessionmaker[Session], owner_id: object, *, status: str = "expired"
) -> object:
    account_id = uuid4()
    credential_id = uuid4()
    with factory.begin() as session:
        platform = Platform(
            slug=f"ml-{account_id}",
            name="Mercado Livre",
            is_active=True,
            capabilities={"commission_scrape": True},
        )
        session.add(platform)
        session.flush()
        session.add(
            PlatformAccount(
                id=account_id,
                owner_id=owner_id,
                platform_id=platform.id,
                label="Conta ML",
                status="active",
                config={},
            )
        )
        session.flush()
        session.add(
            PlatformCredential(
                id=credential_id,
                account_id=account_id,
                kind="cookie",
                ciphertext=b"teste",
                status=status,
            )
        )
    return credential_id


def test_dedup_auto_resolve_reabertura_e_concorrencia(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db, "_SessionFactory", session_factory)
    admin = add_user(session_factory, email="alerts-admin@example.com", role="admin")
    credential_id = _credential(session_factory, admin.id)
    detector = (_auth_detector(),)
    started = datetime.now(timezone.utc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: detect_alerts(now=started, detectors=detector), range(2)))
    for offset in range(1, 5):
        detect_alerts(now=started + timedelta(seconds=offset), detectors=detector)

    with session_factory() as session:
        alerts = list(session.scalars(select(Alert)))
        assert len(alerts) == 1
        assert alerts[0].status == "open"
        assert alerts[0].last_seen_at == started + timedelta(seconds=4)
        credential = session.get(PlatformCredential, credential_id)
        assert credential is not None
        credential.status = "valid"
        session.commit()

    detect_alerts(now=started + timedelta(seconds=5), detectors=detector)
    with session_factory.begin() as session:
        assert session.scalar(select(Alert.status)) == "resolved"
        credential = session.get(PlatformCredential, credential_id)
        assert credential is not None
        credential.status = "expired"

    detect_alerts(now=started + timedelta(seconds=6), detectors=detector)
    broken = Detector(
        "broken",
        ("broken",),
        lambda _session, _now: (_ for _ in ()).throw(RuntimeError("falha isolada")),
    )
    detect_alerts(now=started + timedelta(seconds=7), detectors=(broken, *detector))
    with session_factory() as session:
        alerts = list(session.scalars(select(Alert).order_by(Alert.first_seen_at)))
        assert [alert.status for alert in alerts] == ["resolved", "open"]
        assert alerts[-1].last_seen_at == started + timedelta(seconds=7)


def test_events_redaction_filters_retention_and_role_permissions(
    client: object,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "_SessionFactory", session_factory)
    viewer = add_user(session_factory, email="alerts-viewer@example.com", role="viewer")
    operator = add_user(session_factory, email="alerts-operator@example.com", role="operator")
    admin = add_user(session_factory, email="alerts-owner@example.com", role="admin")
    now = datetime.now(timezone.utc)
    alert_ids = {viewer.role: uuid4(), operator.role: uuid4(), admin.role: uuid4()}
    admin_warning_id = uuid4()
    with session_factory.begin() as session:
        for user in (viewer, operator, admin):
            session.add(
                Alert(
                    id=alert_ids[user.role],
                    owner_id=user.id,
                    type="manual_test",
                    severity="critical" if user.role == "admin" else "warning",
                    title="Teste",
                    status="open",
                    dedup_key=f"manual:{user.id}",
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        session.add(
            Alert(
                id=admin_warning_id,
                owner_id=admin.id,
                type="warning_test",
                severity="warning",
                title="Aviso",
                status="open",
                dedup_key="manual:admin-warning",
                first_seen_at=now + timedelta(seconds=1),
                last_seen_at=now + timedelta(seconds=1),
            )
        )
        session.add_all(
            [
                Event(
                    level="error",
                    type="secret_test",
                    message="Falha tecnica",
                    detail={"cookie": "SENTINELA", "nested": {"token": "SENTINELA"}},
                    created_at=now,
                ),
                Event(
                    level="info",
                    type="old",
                    message="Antigo",
                    created_at=now - timedelta(days=31),
                ),
            ]
        )

    headers = {
        user.role: auth_header(str(login(client, user.email)["access_token"]))
        for user in (viewer, operator, admin)
    }
    listing = client.get("/api/events?level=error&type=secret_test", headers=headers["viewer"])
    assert listing.status_code == 200
    assert "SENTINELA" not in listing.text
    assert listing.json()["items"][0]["detail"] == {
        "cookie": "***",
        "nested": {"token": "***"},
    }
    assert client.get("/api/alerts", headers=headers["viewer"]).status_code == 200
    admin_listing = client.get("/api/alerts", headers=headers["admin"])
    assert [item["severity"] for item in admin_listing.json()["items"]] == [
        "critical",
        "warning",
    ]
    system_status = client.get("/api/system/status", headers=headers["admin"])
    assert system_status.status_code == 200
    assert system_status.json()["open_alerts"] == {"critical": 1, "warning": 1}
    assert (
        client.post(
            f"/api/alerts/{alert_ids['viewer']}/acknowledge", headers=headers["viewer"]
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/alerts/{alert_ids['operator']}/acknowledge", headers=headers["operator"]
        ).status_code
        == 200
    )
    resolved = client.post(f"/api/alerts/{alert_ids['admin']}/resolve", headers=headers["admin"])
    assert resolved.status_code == 200
    with session_factory() as session:
        assert session.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "alert", AuditLog.entity_id == str(alert_ids["admin"])
            )
        )

    assert cleanup_events(now=now) == 1
    with session_factory() as session:
        assert list(session.scalars(select(Event.type))) == ["secret_test"]


def test_cada_detector_dispara_e_ignora_caso_saudavel(
    session_factory: sessionmaker[Session],
) -> None:
    """Cobre os onze detectores com um caso positivo e um controle negativo."""
    now = datetime.now(timezone.utc)
    owner = add_user(session_factory, email="detectors@example.com", role="admin")
    healthy_owner = add_user(session_factory, email="healthy@example.com", role="admin")
    stale_bot_id, healthy_bot_id = uuid4(), uuid4()
    failing_bot_id, okay_bot_id = uuid4(), uuid4()
    bad_group_id, good_group_id = uuid4(), uuid4()
    stale_account_id, fresh_account_id = uuid4(), uuid4()

    engine = session_factory.kw["bind"]
    Oferta.__table__.create(engine, checkfirst=True)
    Envio.__table__.create(engine, checkfirst=True)
    with session_factory.begin() as session:
        platform = Platform(
            slug="detector-platform",
            name="Detector",
            is_active=True,
            capabilities={"commission_api": True},
        )
        session.add(platform)
        session.flush()
        session.add_all(
            [
                Bot(
                    id=stale_bot_id,
                    owner_id=owner.id,
                    name="Parado",
                    slug="parado",
                    status="active",
                    settings=safe_settings(),
                    created_at=now - timedelta(hours=1),
                ),
                Bot(
                    id=healthy_bot_id,
                    owner_id=owner.id,
                    name="Saudavel",
                    slug="saudavel",
                    status="active",
                    settings=safe_settings(),
                    created_at=now,
                ),
                Bot(
                    id=failing_bot_id,
                    owner_id=owner.id,
                    name="Falhando",
                    slug="falhando",
                    status="active",
                    settings=safe_settings(),
                    created_at=now,
                ),
                Bot(
                    id=okay_bot_id,
                    owner_id=owner.id,
                    name="Controle",
                    slug="controle",
                    status="active",
                    settings=safe_settings(),
                    created_at=now,
                ),
            ]
        )
        session.add_all(
            [
                Group(
                    id=bad_group_id,
                    owner_id=owner.id,
                    whatsapp_id="bad@g.us",
                    name="Ruim",
                    status="inaccessible",
                ),
                Group(
                    id=good_group_id,
                    owner_id=owner.id,
                    whatsapp_id="good@g.us",
                    name="Bom",
                    status="active",
                    is_announce=False,
                    bot_is_admin=True,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                BotGroup(bot_id=stale_bot_id, group_id=bad_group_id, is_active=True),
                BotGroup(bot_id=healthy_bot_id, group_id=good_group_id, is_active=True),
                PlatformAccount(
                    id=stale_account_id,
                    owner_id=owner.id,
                    platform_id=platform.id,
                    label="Stale",
                    status="active",
                    config={},
                ),
                PlatformAccount(
                    id=fresh_account_id,
                    owner_id=owner.id,
                    platform_id=platform.id,
                    label="Fresh",
                    status="active",
                    config={},
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                PlatformCredential(
                    account_id=stale_account_id,
                    kind="cookie",
                    ciphertext=b"x",
                    status="expired",
                ),
                PlatformCredential(
                    account_id=fresh_account_id,
                    kind="cookie",
                    ciphertext=b"x",
                    status="valid",
                ),
                PlatformCredential(
                    account_id=stale_account_id,
                    kind="oauth_token",
                    ciphertext=b"x",
                    status="expiring",
                    expires_at=now + timedelta(hours=12),
                ),
                PlatformCredential(
                    account_id=fresh_account_id,
                    kind="oauth_token",
                    ciphertext=b"x",
                    status="expiring",
                    expires_at=now + timedelta(hours=72),
                ),
            ]
        )
        for index in range(3):
            session.add(
                AutomationRun(
                    bot_id=failing_bot_id,
                    kind="cycle",
                    status="failed",
                    started_at=now - timedelta(minutes=index),
                )
            )
        session.add_all(
            [
                AutomationRun(
                    bot_id=okay_bot_id,
                    kind="cycle",
                    status="failed",
                    started_at=now,
                ),
                AutomationRun(
                    bot_id=okay_bot_id,
                    kind="cycle",
                    status="success",
                    started_at=now - timedelta(minutes=1),
                ),
                AutomationRun(
                    bot_id=healthy_bot_id,
                    kind="cycle",
                    status="success",
                    started_at=now,
                ),
            ]
        )
        session.add_all(
            [Envio(group_id=bad_group_id, status="falha", enviado_em=now) for _ in range(3)]
            + [Envio(group_id=good_group_id, status="falha", enviado_em=now) for _ in range(2)]
        )
        session.add_all(
            [
                Event(
                    bot_id=failing_bot_id,
                    level="error",
                    type="platform_error",
                    message="erro",
                    created_at=now,
                )
                for _ in range(10)
            ]
            + [
                Event(
                    bot_id=okay_bot_id,
                    level="error",
                    type="rare_error",
                    message="erro",
                    created_at=now,
                )
                for _ in range(9)
            ]
            + [
                Event(
                    entity_type="platform_account",
                    entity_id=str(stale_account_id),
                    level="warning",
                    type="ml_sales_truncated",
                    message="truncado",
                    detail={"date": "2026-09-22"},
                    created_at=now,
                ),
                Event(
                    entity_type="platform_account",
                    entity_id=str(stale_account_id),
                    level="warning",
                    type="ml_reconciliation_mismatch",
                    message="divergente",
                    created_at=now,
                ),
                Event(
                    entity_type="platform_account",
                    entity_id=str(fresh_account_id),
                    level="warning",
                    type="ml_sales_truncated",
                    message="antigo",
                    created_at=now - timedelta(days=2),
                ),
            ]
        )
        session.add(
            Sale(
                owner_id=owner.id,
                account_id=fresh_account_id,
                platform_id=platform.id,
                external_id="fresh-sale",
                gross_amount=10,
                commission=1,
                status="confirmed",
                ordered_at=now,
                source="api",
                imported_at=now,
            )
        )
        old_category = ExpenseCategory(owner_id=owner.id, slug="trafego", name="Trafego")
        recent_category = ExpenseCategory(owner_id=healthy_owner.id, slug="trafego", name="Trafego")
        session.add_all([old_category, recent_category])
        session.flush()
        session.add_all(
            [
                Expense(
                    owner_id=owner.id,
                    description="Antigo",
                    amount=10,
                    incurred_on=(now - timedelta(days=10)).date(),
                    category_id=old_category.id,
                    source="manual",
                ),
                Expense(
                    owner_id=healthy_owner.id,
                    description="Recente",
                    amount=10,
                    incurred_on=now.date(),
                    category_id=recent_category.id,
                    source="manual",
                ),
            ]
        )

    with session_factory() as session:
        assert {item.entity_id for item in detect_bot_offline(session, now)} == {str(stale_bot_id)}
        assert {item.entity_id for item in detect_automation_failing(session, now)} == {
            str(failing_bot_id)
        }
        assert len(detect_auth_expired(session, now)) == 1
        assert len(detect_auth_expiring(session, now)) == 1
        assert {item.entity_id for item in detect_send_failed(session, now)} == {str(bad_group_id)}
        assert {item.entity_id for item in detect_group_inaccessible(session, now)} == {
            str(bad_group_id)
        }
        assert [item.entity_id for item in detect_recurring_error(session, now)] == [
            "platform_error"
        ]
        assert {item.entity_id for item in detect_sales_sync_stale(session, now)} == {
            str(stale_account_id)
        }
        assert [item.owner_id for item in detect_traffic_spend_stale(session, now)] == [owner.id]
        assert len(detect_ml_sales_truncated(session, now)) == 1
        assert len(detect_ml_reconciliation_mismatch(session, now)) == 1


def test_bot_offline_legado_sem_bot(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = add_user(session_factory, email="legacy-alert@example.com", role="admin")
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("core.alerts.settings.check_interval", 60)
    with session_factory.begin() as session:
        session.add(
            AutomationRun(
                bot_id=None,
                kind="cycle",
                status="success",
                started_at=now - timedelta(minutes=4),
            )
        )
    with session_factory() as session:
        result = detect_bot_offline(session, now)
    assert len(result) == 1
    assert result[0].owner_id == admin.id
    assert result[0].dedup_key == "bot_offline:legacy"
