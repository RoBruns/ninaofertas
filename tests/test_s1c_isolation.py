# ruff: noqa: F401, F811
"""Regressões da auditoria S1c em Postgres, sem rede ou WhatsApp real."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from api.routers.platform import _response
from core import alerts, config_provider, relogio, repositories, sales_sync
from core.models import (
    Alert,
    AuditLog,
    AutomationRun,
    Bot,
    Command,
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
    Tenant,
    User,
)
from core.platforms.base import OfertaCapturada
from tests.test_api import add_user, auth_header, client, session_factory
from tests.test_tenant_isolation import operations
from tests.test_tenant_worker import runtime
from tests.test_worker_config import _patch_sessions
from api.security import create_access_token
from worker import channels, commands, dedup, monitor


def headers(user):
    return auth_header(create_access_token(str(user.id), session_version=user.session_version))


def test_jid_igual_nao_mistura_baseline_dedup_tetos_cupons_e_plataforma(
    session_factory, operations, monkeypatch
):
    a, aid, _ = operations[0]
    b, bid, _ = operations[1]
    jid = "compartilhado@g.us"
    now = relogio.agora_banco()
    with session_factory.begin() as session:
        for ids in (aid, bid):
            session.get(Group, ids["group_id"]).whatsapp_id = jid
        offer = Oferta(nome="Cupom", preco=100, url="https://cupom", sku="cupom", categoria="cupom")
        session.add(offer)
        session.flush()
        offer_id = offer.id
        # Inclui baseline e envios sem bot, mas vinculados ao grupo de B.
        for bot_id, status in (
            (bid["bot_id"], "visto"),
            (bid["bot_id"], "sucesso"),
            (None, "sucesso"),
        ):
            session.add(
                Envio(
                    oferta_id=offer_id,
                    grupo=jid,
                    bot_id=bot_id,
                    group_id=bid["group_id"],
                    status=status,
                    preco_enviado=100,
                    enviado_em=now,
                )
            )
    ra = replace(runtime(operations[0]), group_ids=(jid,))
    _patch_sessions(monkeypatch, session_factory)
    monkeypatch.setattr(channels, "bots_ativos", lambda: [ra])
    with session_factory.begin() as session, channels.usar_canal(f"db:{ra.id}:{jid}"):
        args = {"tenant_id": a.tenant_id, "grupo": jid}
        assert not repositories.ja_conhecida(session, offer_id, **args)
        assert repositories.ultimo_envio(session, offer_id, **args) is None
        assert not repositories.grupo_ja_enviou(session, **args)
        assert repositories.contar_envios_ultima_hora(session, **args) == 0
        assert repositories.contar_envios_hoje(session, **args) == 0
        assert repositories.contar_cupons_hoje(session, **args) == 0
        assert repositories.minutos_desde_ultimo_sku(session, "cupom", **args) is None
        assert not repositories.sku_ja_enviado(session, "cupom", **args)
        assert repositories.nomes_precos_enviados_recentes(session, **args) == []
        assert repositories.ordenar_grupos_por_ultimo_envio(
            session, (jid, "z@g.us"), tenant_id=a.tenant_id
        ) == (jid, "z@g.us")
        assert _response(session, session.get(Tenant, a.tenant_id)).successful_sends_30d == 0
        assert _response(session, session.get(Tenant, b.tenant_id)).successful_sends_30d == 2
        assert dedup.deve_enviar(session, offer_id, 100, 15, nome="Cupom", sku="cupom", **args)[0]
        captured = OfertaCapturada(
            nome="Cupom", preco=100, url="https://cupom", loja="Shopee", categoria="cupom"
        )
        assert monitor._freio_anti_ban(
            session,
            {"max_ofertas_por_hora": 1, "max_ofertas_por_dia": 1, "max_cupons_por_dia": 1},
            jid,
            captured,
        )[0]
        assert monitor._baseline_oferta(session, captured, {})
        assert repositories.ja_conhecida(session, offer_id, **args)
        # Mesmo teste/produção na conta A compartilham dedup e controles por grupo.
        test = Bot(id=uuid4(), owner_id=a.tenant_id, name="Teste", slug="teste", is_test=True)
        session.add(test)
        session.flush()
        repositories.registrar_envio(
            session, offer_id, jid, "m", 100, "sucesso", bot_id=aid["bot_id"]
        )
        rt = replace(ra, id=test.id, is_test=True)
        with config_provider.usar_bot_runtime(rt):
            assert not dedup.deve_enviar(session, offer_id, 100, 15, **args)[0]
            assert monitor._freio_anti_ban(session, {"max_ofertas_globais_por_hora": 1}, "outro")[0]
            assert not monitor._freio_anti_ban(session, {"max_ofertas_por_hora": 1}, jid)[0]


def test_consultas_exigem_tenant_e_freio_sem_runtime_bloqueia(session_factory, operations):
    with session_factory() as session:
        calls = (
            (repositories.ultimo_envio, (session, 1)),
            (repositories.ja_conhecida, (session, 1)),
            (repositories.grupo_ja_enviou, (session,)),
            (repositories.rejeitada_pelo_publico, (session, 1, "g", "motivo", None)),
            (repositories.contar_envios_desde, (session, relogio.agora_banco())),
            (repositories.ordenar_grupos_por_ultimo_envio, (session, ())),
            (repositories.contar_envios_ultima_hora, (session,)),
            (repositories.contar_envios_hoje, (session,)),
            (repositories.minutos_desde_ultimo_envio, (session,)),
            (repositories.contar_cupons_hoje, (session,)),
            (repositories.minutos_desde_ultimo_sku, (session, "sku")),
            (repositories.sku_ja_enviado, (session, "sku")),
            (repositories.nomes_precos_enviados_recentes, (session,)),
            (repositories._escopo_envios, (session.query(Envio), None, False)),
            (repositories.escopo_envios_conta, ()),
            (dedup.deve_enviar, (session, 1, 100, 15)),
        )
        for function, args in calls:
            with pytest.raises(TypeError, match="tenant_id"):
                function(*args)
            with pytest.raises(ValueError, match="tenant_id"):
                function(*args, tenant_id=None)
        with config_provider.usar_bot_runtime(None):
            assert monitor._freio_anti_ban(session, {}, "g") == (
                False,
                "freio: sem bot em execução",
            )


def test_admin_comum_nao_altera_acesso_nem_remove_platform_admin(client, session_factory):
    platform = add_user(
        session_factory, email="platform@teste.com", role="admin", is_platform_admin=True
    )
    admin = add_user(
        session_factory,
        email="admin@teste.com",
        tenant_id=platform.tenant_id,
        role="admin",
        is_platform_admin=False,
    )
    second = add_user(
        session_factory,
        email="second@teste.com",
        tenant_id=platform.tenant_id,
        role="admin",
        is_platform_admin=True,
    )
    endpoint = f"/api/users/{platform.id}"
    for changes in (
        {"email": "outro@teste.com"},
        {"password": "outra-senha"},
        {"role": "viewer"},
        {"is_active": False},
    ):
        assert client.patch(endpoint, headers=headers(admin), json=changes).status_code == 403
    assert client.delete(endpoint, headers=headers(admin)).status_code == 403
    assert client.patch(endpoint, headers=headers(admin), json={"name": "Dono"}).status_code == 200
    assert (
        client.patch(
            endpoint,
            headers=headers(second),
            json={"email": "novo@teste.com", "password": "senha-nova"},
        ).status_code
        == 200
    )
    assert client.delete(endpoint, headers=headers(second)).status_code == 204


def test_seed_garante_platform_admin_para_email_ja_existente(session_factory):
    from core.seed import _admin

    user = add_user(session_factory, email="dono@teste.com", role="admin", is_platform_admin=False)
    with session_factory.begin() as session:
        seeded = _admin(session, "DONO@teste.com", "senha-ignorada")
        assert seeded.id == user.id and seeded.is_platform_admin
        assert seeded.password_hash == user.password_hash
    with session_factory() as session:
        assert session.get(User, user.id).is_platform_admin


def test_vendas_e_despesas_csv_com_mesmo_external_id_coexistem(client, session_factory, operations):
    from tests.test_phase8_api import _sales_csv

    csv = _sales_csv(["pedido-comum,Panela,1,100,10,confirmed,2026-09-20T12:00:00Z,"])
    expenses = b"descricao;valor;data;external_id\nMeta;15.90;2026-09-10;pedido-comum\n"
    for user, ids, _ in operations:
        with session_factory() as session:
            platform_id = session.get(PlatformAccount, ids["account_id"]).platform_id
        for attempt in range(2):
            response = client.post(
                "/api/sales/import",
                headers=headers(user),
                data={"platform_id": platform_id},
                files={"file": ("vendas.csv", csv, "text/csv")},
            )
            assert response.status_code == 200, response.text
            assert response.json()["imported"] == (1 if attempt == 0 else 0)
            assert response.json()["skipped"] == attempt
            response = client.post(
                "/api/expenses/import",
                headers=headers(user),
                files={"file": ("gastos.csv", expenses, "text/csv")},
            )
            assert response.status_code == 200, response.text
            assert response.json()["imported"] == (1 if attempt == 0 else 0)
            assert response.json()["skipped"] == attempt
    with session_factory() as session:
        assert (
            len(session.scalars(select(Sale).where(Sale.external_id == "pedido-comum")).all()) == 2
        )
        assert (
            len(session.scalars(select(Expense).where(Expense.external_id == "pedido-comum")).all())
            == 2
        )


def test_sync_chave_por_conta_e_savepoint_pula_linha_ruim(session_factory, operations, monkeypatch):
    from core.importers.mercadolivre import parse_dashboard
    from tests.test_sales_sync import FIXTURES

    _patch_sessions(monkeypatch, session_factory)
    a, aid, _ = operations[0]
    b, bid, _ = operations[1]
    rows, _ = parse_dashboard((FIXTURES / "ml_dashboard.html").read_text(encoding="utf-8"))
    assert sales_sync._upsert(bid["account_id"], rows[:1], "scrape").imported == 1
    # Erro real de constraint, entre duas linhas boas; savepoint precisa recuperar a sessão.
    bad = replace(rows[0], external_id="ruim", gross_amount=None, line=99)
    foreign = replace(rows[0], external_id="referencia-b", bot_id=bid["bot_id"], line=100)
    result = sales_sync._upsert(aid["account_id"], [rows[0], bad, foreign, rows[1]], "scrape")
    assert (result.imported, result.skipped) == (2, 2)
    with session_factory() as session:
        assert (
            len(session.scalars(select(Sale).where(Sale.external_id == rows[0].external_id)).all())
            == 2
        )
        warnings = session.scalars(select(Event).where(Event.type == "sales_sync_row_failed")).all()
        assert len(warnings) == 2
        assert all(e.tenant_id == a.tenant_id and e.level == "warning" for e in warnings)
        assert {e.detail["line"] for e in warnings} == {99, 100}
        assert session.scalar(select(Sale.id).where(Sale.external_id == "ruim")) is None
    again = sales_sync._upsert(aid["account_id"], rows[:2], "scrape")
    assert (again.imported, again.skipped) == (0, 2)


def test_suspensao_ignora_sync_e_falha_comandos_sem_executar(
    session_factory, operations, monkeypatch
):
    _patch_sessions(monkeypatch, session_factory)
    a, aid, _ = operations[0]
    b, bid, _ = operations[1]
    with session_factory.begin() as session:
        session.get(Tenant, b.tenant_id).status = "suspended"
        platform = session.get(
            Platform, session.get(PlatformAccount, aid["account_id"]).platform_id
        )
        platform.capabilities = {"commission_scrape": True}
        for kind, payload, bot_id in (
            ("resume", {}, bid["bot_id"]),
            ("pause", {}, bid["bot_id"]),
            ("run_now", {}, bid["bot_id"]),
            ("reload_config", {}, None),
            ("sync_groups", {"phone_id": str(bid["phone_id"])}, None),
            ("commission_import", {"account_id": str(bid["account_id"])}, None),
        ):
            session.add(
                Command(
                    type=kind,
                    payload=payload,
                    bot_id=bot_id,
                    requested_by=b.id if kind == "reload_config" else None,
                    status="pending",
                )
            )
    calls = []
    monkeypatch.setattr(
        sales_sync, "sync_account", lambda account_id, **kw: calls.append(account_id)
    )
    sales_sync.sync_all_active_accounts()
    assert aid["account_id"] in calls and not set(calls) & set([bid["account_id"]])
    with pytest.raises(ValueError, match="conta suspensa"):
        sales_sync._load_account(bid["account_id"])
    monkeypatch.setattr(commands, "_executar", lambda *_: pytest.fail("comando suspenso executado"))
    commands.drenar_comandos()
    assert not commands.bot_esta_ativo(bid["bot_id"])
    with session_factory() as session:
        stored = session.scalars(select(Command)).all()
        assert len(stored) == 6
        assert all(
            c.status == "failed" and c.result == "conta suspensa" and c.finished_at for c in stored
        )


def test_detectores_ignoram_conta_suspensa(session_factory, operations):
    now = datetime.now(timezone.utc)
    with session_factory.begin() as session:
        for user, ids, _ in operations:
            bot = session.get(Bot, ids["bot_id"])
            bot.created_at = now - timedelta(days=4)
            group = session.get(Group, ids["group_id"])
            group.status = "inaccessible"
            account = session.get(PlatformAccount, ids["account_id"])
            session.get(Platform, account.platform_id).capabilities = {"commission_scrape": True}
            session.get(
                PlatformCredential,
                session.scalar(
                    select(PlatformCredential.id).where(PlatformCredential.account_id == account.id)
                ),
            ).status = "invalid"
            session.add(
                PlatformCredential(
                    account_id=account.id, kind="expiring-test", ciphertext=b"x", status="expiring"
                )
            )
            offer = Oferta(nome="Erro", preco=1, url=f"https://{user.id}")
            session.add(offer)
            session.flush()
            for _ in range(3):
                session.add(
                    AutomationRun(
                        bot_id=bot.id,
                        kind="cycle",
                        status="failed",
                        started_at=now - timedelta(hours=1),
                    )
                )
                session.add(
                    Envio(
                        oferta_id=offer.id,
                        bot_id=bot.id,
                        group_id=group.id,
                        grupo=group.whatsapp_id,
                        status="falha",
                        enviado_em=now,
                    )
                )
            for _ in range(10):
                session.add(
                    Event(
                        tenant_id=user.tenant_id,
                        entity_type="phone",
                        entity_id=str(ids["phone_id"]),
                        level="error",
                        type="recorrente",
                        message="erro",
                    )
                )
            for kind in ("ml_sales_truncated", "ml_reconciliation_mismatch", "bot_not_runnable"):
                session.add(
                    Event(
                        tenant_id=user.tenant_id,
                        bot_id=bot.id,
                        entity_type="platform_account",
                        entity_id=str(account.id),
                        level="warning",
                        type=kind,
                        message="teste",
                    )
                )
            category = ExpenseCategory(owner_id=user.tenant_id, slug="trafego", name="Tráfego")
            session.add(category)
            session.flush()
            session.add(
                Expense(
                    owner_id=user.tenant_id,
                    category_id=category.id,
                    amount=Decimal("10"),
                    description="Meta",
                    incurred_on=(now - timedelta(days=10)).date(),
                )
            )
            # Faz bot_not_runnable gerar condição, além de group_inaccessible.
            bot.phone_id = None
        session.get(Tenant, operations[1][0].tenant_id).status = "suspended"
    a = operations[0][0]
    with session_factory() as session:
        for detector in alerts.DETECTORS:
            conditions = detector.function(session, now)
            assert conditions, detector.name
            assert all(c.owner_id == a.tenant_id for c in conditions), detector.name


def test_auditoria_da_plataforma_pertence_a_conta_afetada(client, session_factory, operations):
    admin = add_user(session_factory, email="dono@teste.com", role="admin", is_platform_admin=True)
    a, aid, _ = operations[0]
    created = client.post(
        "/api/platform/tenants",
        headers=headers(admin),
        json={
            "name": "Nova",
            "admin_email": "nova@teste.com",
            "admin_password": "senha-segura",
            "admin_name": "Nova",
        },
    )
    assert created.status_code == 201, created.text
    for changes in ({"name": "Cliente"}, {"status": "suspended"}, {"status": "active"}):
        response = client.patch(
            f"/api/platform/tenants/{a.tenant_id}", headers=headers(admin), json=changes
        )
        assert response.status_code == 200, response.text
    with session_factory() as session:
        entries = session.scalars(select(AuditLog).where(AuditLog.user_id == admin.id)).all()
        assert len(entries) == 5
        assert str(entries[0].tenant_id) == created.json()["id"]
        assert all(e.tenant_id == a.tenant_id for e in entries[1:])
        pause = next(e for e in entries if e.action == "tenant_suspended")
        assert pause.entity_id == str(aid["bot_id"])
    audit = client.get("/api/audit-logs", headers=headers(a))
    assert audit.status_code == 200
    assert any(e["action"] == "tenant_suspended" for e in audit.json()["items"])
