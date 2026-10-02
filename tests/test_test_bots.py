# ruff: noqa: F401, F811
from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from core import config_provider, relogio, repositories
from core.bot_settings import BotSettings
from core.metrics import MetricFilters, _event_conditions, _sales_conditions
from core.models import Bot, BotConfigBackup, Click, Envio, Oferta, Sale, PlatformAccount
from tests.test_api import client, session_factory
from tests.test_bots_api import admin_context, create_bot
from tests.test_worker_config import _active_bot, _patch_sessions, _reset_cache
from worker.monitor import _freio_anti_ban


def test_create_import_restore(client, session_factory):
    admin, headers, catalog = admin_context(client, session_factory)
    source = create_bot(
        client,
        headers,
        name="Produção",
        slug="producao",
        catalog=catalog,
        group_ids=catalog["group_ids"],
        account_ids=catalog["account_ids"],
    )
    source_settings = source["settings"]
    source_settings["attribution"] = {"ml_tag": "producao"}
    client.patch(f"/api/bots/{source['id']}", headers=headers, json={"settings": source_settings})
    response = client.post(
        "/api/bots/test",
        headers=headers,
        json={
            "name": "Teste",
            "source_bot_id": source["id"],
            "phone_id": str(catalog["phone_id"]),
            "group_ids": [str(catalog["group_ids"][0])],
        },
    )
    assert response.status_code == 201, response.text
    test = response.json()
    assert test["is_test"] and test["status"] == "paused"
    assert test["test_source_bot_id"] == source["id"]
    assert test["settings"]["attribution"]["ml_tag"] is None
    assert test["settings"]["filters"] == source["settings"]["filters"]
    assert test["message_template"] == source["message_template"]
    assert test["niche_id"] == source["niche_id"]
    assert test["account_ids"] == source["account_ids"]
    changed = test["settings"]
    changed["filters"]["preco_minimo"] = 111
    assert (
        client.patch(
            f"/api/bots/{test['id']}",
            headers=headers,
            json={"settings": changed, "message_template": "{nome} teste {url}"},
        ).status_code
        == 200
    )
    imported = client.post(
        f"/api/bots/{test['id']}/import-config",
        headers=headers,
        json={"target_bot_id": source["id"]},
    )
    assert imported.status_code == 200, imported.text
    target = imported.json()
    assert target["settings"]["filters"]["preco_minimo"] == 111
    assert target["settings"]["attribution"]["ml_tag"] == "producao"
    assert target["message_template"] == "{nome} teste {url}"
    for field in ["phone_id", "group_ids", "account_ids", "niche_id", "slug", "name", "status"]:
        assert target[field] == source[field]
    archived = client.get(f"/api/bots/{test['id']}", headers=headers).json()
    assert archived["status"] == "disabled" and archived["archived_at"]
    assert test["id"] not in [
        bot["id"] for bot in client.get("/api/bots", headers=headers).json()["items"]
    ]
    assert test["id"] in [
        bot["id"]
        for bot in client.get(
            "/api/bots?include_archived=true&is_test=true", headers=headers
        ).json()["items"]
    ]
    backups = client.get(f"/api/bots/{source['id']}/config-backups", headers=headers).json()[
        "items"
    ]
    assert backups[0]["reason"] == "import_from_test" and backups[0]["source_bot_name"] == "Teste"
    with session_factory() as session:
        backup = session.get(BotConfigBackup, UUID(backups[0]["id"]))
        assert (
            backup.settings == source_settings
            and backup.message_template == source["message_template"]
        )
    restored = client.post(
        f"/api/bots/{source['id']}/config-backups/{backups[0]['id']}/restore", headers=headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["settings"] == source_settings
    with session_factory() as session:
        backups_db = list(
            session.scalars(
                select(BotConfigBackup)
                .where(BotConfigBackup.bot_id == UUID(source["id"]))
                .order_by(BotConfigBackup.created_at.desc())
            )
        )
        assert len(backups_db) == 2 and backups_db[0].reason == "restore"
        assert backups_db[0].settings["filters"]["preco_minimo"] == 111
    for path, payload in [
        (f"/api/bots/{test['id']}/activate", None),
        (f"/api/bots/{test['id']}", {"status": "active"}),
    ]:
        result = (
            client.patch(path, headers=headers, json=payload)
            if payload
            else client.post(path, headers=headers)
        )
        assert result.status_code == 409


def test_import_conflicts_and_archive(client, session_factory):
    _, headers, _ = admin_context(client, session_factory)
    prod = create_bot(client, headers, name="Produção", slug="prod")
    test = client.post("/api/bots/test", headers=headers, json={"name": "Teste"}).json()
    test2 = client.post("/api/bots/test", headers=headers, json={"name": "Teste"}).json()
    assert test2["slug"] != test["slug"]
    for source, target in [(prod, prod), (test, test2)]:
        assert (
            client.post(
                f"/api/bots/{source['id']}/import-config",
                headers=headers,
                json={"target_bot_id": target["id"]},
            ).status_code
            == 409
        )
    assert client.post(f"/api/bots/{prod['id']}/archive", headers=headers).status_code == 409
    assert client.post(f"/api/bots/{test2['id']}/archive", headers=headers).status_code == 200
    assert (
        client.post(
            f"/api/bots/{test2['id']}/import-config",
            headers=headers,
            json={"target_bot_id": prod["id"]},
        ).status_code
        == 409
    )
    with session_factory.begin() as session:
        session.get(Bot, UUID(prod["id"])).archived_at = datetime.now(timezone.utc)
    assert (
        client.post(
            f"/api/bots/{test['id']}/import-config",
            headers=headers,
            json={"target_bot_id": prod["id"]},
        ).status_code
        == 409
    )
    assert client.post(f"/api/bots/{test2['id']}/duplicate", headers=headers).status_code == 409
    assert (
        client.post(
            "/api/bots/test", headers=headers, json={"name": "Falha", "source_bot_id": test2["id"]}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "control",
    [
        {"intervalo_minutos_entre_ofertas": 5},
        {"max_ofertas_por_rajada": 1, "pausa_entre_rajadas_minutos": 35},
        {"max_ofertas_globais_por_hora": 1},
        {"max_ofertas_globais_por_dia": 1},
    ],
)
@pytest.mark.parametrize("sender_test", [True, False])
def test_freio_scope(session_factory, control, sender_test):
    prod, _ = _active_bot(session_factory)
    test_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            Bot(
                id=test_id,
                owner_id=prod.owner_id,
                slug="teste",
                name="Teste",
                settings=BotSettings().model_dump(mode="json"),
                is_test=True,
            )
        )
        session.flush()
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)
        oferta = Oferta(nome="Oferta", preco=10, url=str(uuid4()))
        session.add(oferta)
        session.flush()
        sender_id = test_id if sender_test else prod.id
        session.add_all(
            [
                Envio(
                    oferta_id=oferta.id,
                    bot_id=sender_id,
                    grupo=g,
                    status="sucesso",
                    enviado_em=relogio.agora_banco(),
                )
                for g in ["grupo", "grupo2"]
            ]
        )
    runtime = config_provider.BotRuntime(
        id=prod.id if sender_test else test_id,
        slug="bot",
        nome="Bot",
        niche_slug=None,
        phone_number=None,
        evolution_instance=None,
        group_ids=(),
        settings=BotSettings(),
        account_ids=(),
        is_test=not sender_test,
    )
    with session_factory() as session, config_provider.usar_bot_runtime(runtime):
        assert _freio_anti_ban(session, control, "outro")[0]
        assert not _freio_anti_ban(session, {"max_ofertas_por_hora": 1}, "grupo")[0]
        assert not _freio_anti_ban(session, {"max_ofertas_por_dia": 1}, "grupo")[0]
        assert (
            repositories.contar_envios_desde(session, relogio.agora_banco() - timedelta(hours=1))
            == 1
        )
    own = replace(runtime, id=sender_id, is_test=sender_test)
    with session_factory() as session, config_provider.usar_bot_runtime(own):
        ok, reason = _freio_anti_ban(session, control, "outro")
        assert not ok
        if sender_test:
            assert "bot de teste" in reason


def test_worker_archive_and_reload(monkeypatch, session_factory):
    prod, _ = _active_bot(session_factory)
    _patch_sessions(monkeypatch, session_factory)
    _reset_cache()
    first = config_provider.bots_ativos()
    assert len(first) == 1
    with session_factory.begin() as session:
        bot = session.get(Bot, prod.id)
        settings = dict(bot.settings)
        settings["filters"] = {**settings["filters"], "preco_minimo": 123}
        bot.settings = settings
    assert config_provider.bots_ativos(ttl=0)[0].settings.filters.preco_minimo == 123
    with session_factory.begin() as session:
        session.get(Bot, prod.id).archived_at = datetime.now(timezone.utc)
    assert config_provider.bots_ativos(ttl=0) == []
    _reset_cache()


def test_metrics_test_scope(session_factory):
    prod, catalog = _active_bot(session_factory)
    test_id = uuid4()
    now = datetime.now(timezone.utc)
    with session_factory.begin() as session:
        session.add(
            Bot(
                id=test_id,
                owner_id=prod.owner_id,
                slug="teste",
                name="Teste",
                is_test=True,
                settings={},
            )
        )
        session.flush()
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)
        platform_id = session.scalar(select(PlatformAccount.platform_id).limit(1))
        for bot_id in [prod.id, test_id, None]:
            session.add(
                Envio(
                    bot_id=bot_id,
                    group_id=catalog["group_ids"][0],
                    enviado_em=relogio.agora_banco(),
                    status="sucesso",
                )
            )
            session.add(
                Click(
                    bot_id=bot_id,
                    group_id=catalog["group_ids"][0],
                    sub_id=str(uuid4()),
                    clicked_at=now,
                )
            )
            session.add(
                Sale(
                    owner_id=prod.owner_id,
                    bot_id=bot_id,
                    platform_id=platform_id,
                    external_id=str(uuid4()),
                    gross_amount=10,
                    commission=1,
                    source="manual",
                    ordered_at=now,
                )
            )
    today = relogio.agora_banco().date()
    with session_factory() as session:
        for bot_id, expected in [(None, 2), (test_id, 1)]:
            filters = MetricFilters(from_date=today, to_date=today, bot_id=bot_id)
            for model in [Envio, Click]:
                conditions, _ = _event_conditions(model, prod.owner_id, filters, "teste")
                assert len(list(session.scalars(select(model).where(*conditions)))) == expected
            conditions, _ = _sales_conditions(prod.owner_id, filters)
            assert len(list(session.scalars(select(Sale).where(*conditions)))) == expected


def test_test_create_overrides_and_ownership(client, session_factory):
    _, headers, catalog = admin_context(client, session_factory)
    source = create_bot(
        client,
        headers,
        name="Origem",
        slug="origem",
        catalog=catalog,
        account_ids=catalog["account_ids"],
    )
    result = client.post(
        "/api/bots/test",
        headers=headers,
        json={
            "name": "Sem vínculos herdados",
            "source_bot_id": source["id"],
            "account_ids": [],
            "niche_id": None,
        },
    )
    assert result.status_code == 201
    assert result.json()["account_ids"] == [] and result.json()["niche_id"] is None
    assert result.json()["phone_id"] is None and result.json()["group_ids"] == []
    assert (
        client.post(
            "/api/bots/test", headers=headers, json={"name": "Inválido", "phone_id": str(uuid4())}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/bots/test",
            headers=headers,
            json={"name": "Inválido", "group_ids": [str(uuid4())]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/bots/test",
            headers=headers,
            json={"name": "Inválido", "account_ids": [str(uuid4())]},
        ).status_code
        == 404
    )
    duplicate = client.post(f"/api/bots/{result.json()['id']}/duplicate", headers=headers)
    assert duplicate.status_code == 201 and duplicate.json()["is_test"]
    assert client.delete(f"/api/bots/{result.json()['id']}", headers=headers).status_code == 409


def test_legacy_configuration_copy():
    from api.routers.bots import _copy_config

    config = _copy_config(
        {"preco_minimo": 77, "intervalo_minutos_entre_ofertas": 10}, {"ml_tag": None}
    )
    assert config["filters"]["preco_minimo"] == 77
    assert config["pacing"]["intervalo_minutos_entre_ofertas"] == 10
    assert config["attribution"]["ml_tag"] is None


def test_legacy_sends_and_coupon_group_protection(session_factory):
    prod, _ = _active_bot(session_factory)
    test_id = uuid4()
    with session_factory.begin() as session:
        session.add(
            Bot(
                id=test_id,
                owner_id=prod.owner_id,
                slug="teste",
                name="Teste",
                is_test=True,
                settings={},
            )
        )
        session.flush()
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)
        coupon = Oferta(nome="Cupom", preco=10, categoria="cupom")
        session.add(coupon)
        session.flush()
        session.add(
            Envio(
                oferta_id=coupon.id,
                bot_id=None,
                status="sucesso",
                grupo="legado",
                enviado_em=relogio.agora_banco(),
            )
        )
        session.add(
            Envio(
                oferta_id=coupon.id,
                bot_id=test_id,
                status="sucesso",
                grupo="real",
                enviado_em=relogio.agora_banco(),
            )
        )
    runtime = config_provider.BotRuntime(
        id=prod.id,
        slug="prod",
        nome="Produção",
        niche_slug=None,
        phone_number=None,
        evolution_instance=None,
        group_ids=(),
        settings=BotSettings(),
        account_ids=(),
    )
    from core.platforms.base import OfertaCapturada

    offer = OfertaCapturada(nome="Cupom", preco=10, url="url", loja="Shopee", categoria="cupom")
    with session_factory() as session, config_provider.usar_bot_runtime(runtime):
        assert (
            repositories.contar_envios_desde(
                session, relogio.inicio_do_dia_banco(), excluir_bots_teste=True
            )
            == 1
        )
        assert not _freio_anti_ban(session, {"intervalo_minutos_entre_ofertas": 5}, "outro")[0]
        assert not _freio_anti_ban(session, {"max_cupons_por_dia": 1}, "real", offer)[0]
        assert _freio_anti_ban(session, {"max_cupons_por_dia": 1}, "outro", offer)[0]


def test_test_baseline_even_in_production_groups(monkeypatch, session_factory):
    from tests.test_multigrupo import _preparar, _oferta
    from worker import monitor

    runtime, enviados = _preparar(monkeypatch, session_factory, [_oferta("Panela de teste")])
    settings = runtime.settings.model_copy(
        update={"content": runtime.settings.content.model_copy(update={"baseline_ciclos": 2})}
    )
    runtime = replace(runtime, is_test=True, settings=settings)
    with session_factory.begin() as session:
        session.get(Bot, runtime.id).is_test = True
        old = Oferta(nome="Antiga", preco=10, url="https://antiga")
        session.add(old)
        session.flush()
        for group in runtime.group_ids:
            session.add(
                Envio(
                    oferta_id=old.id,
                    grupo=group,
                    status="sucesso",
                    enviado_em=relogio.agora_banco() - timedelta(hours=2),
                )
            )
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()
        monitor.ciclo()
    assert enviados == []
    from worker.telemetry import quantidade_baselines

    assert quantidade_baselines(runtime.id) == 2
