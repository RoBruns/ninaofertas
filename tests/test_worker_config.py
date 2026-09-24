# ruff: noqa: E402, F401, F811

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core import config_provider, db
from core.alerts import DETECTORS, detect_alerts
from core.models import Alert, AutomationRun, Bot, BotGroup, Command, Envio, Event, Oferta
from core.seed import run_seed
from core.settings import settings
from tests.test_api import add_user, session_factory
from tests.test_bots_api import add_catalog, safe_settings
from worker import channels, commands, main as worker_main, monitor

ROOT = Path(__file__).resolve().parents[1]


def _reset_cache() -> None:
    config_provider._cache = None
    config_provider._cache_at = 0.0


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


def _active_bot(
    factory: sessionmaker[Session],
    *,
    slug: str = "casa",
    settings: dict | None = None,
) -> tuple[Bot, dict[str, object]]:
    owner = add_user(factory, email=f"{slug}-{uuid4()}@example.com", role="admin")
    catalog = add_catalog(factory, owner.id)
    with factory.begin() as session:
        bot = Bot(
            id=uuid4(),
            owner_id=owner.id,
            name=f"Bot {slug}",
            slug=slug,
            niche_id=catalog["niche_id"],
            phone_id=catalog["phone_id"],
            status="active",
            settings=settings or safe_settings(),
        )
        session.add(bot)
        session.flush()
        session.add_all(
            BotGroup(bot_id=bot.id, group_id=group_id, is_active=True)
            for group_id in catalog["group_ids"]
        )
    return bot, catalog


def test_banco_vazio_preserva_exatamente_os_dois_canais_legados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(channels, "bots_ativos", lambda: [])
    monkeypatch.setenv("WHATSAPP_GROUP_ID", "grupo-casa")
    monkeypatch.setenv("WHATSAPP_GROUP_ID_AUTO", "grupo-auto")

    assert channels.canais_ativos() == ("achadinhos",)
    for canal, arquivo, nome, grupo in (
        ("achadinhos", "config.json", "Achadinhos da Nina", "grupo-casa"),
        ("auto", "config.auto.json", "Nina Ofertas", "grupo-auto"),
    ):
        esperado = json.loads((ROOT / arquivo).read_text(encoding="utf-8"))
        with channels.usar_canal(canal):
            assert channels.nome_canal() == nome
            assert channels.grupo_whatsapp() == grupo
            assert channels.load_filtros() == esperado


def test_postgres_sem_bots_preserva_config_legado(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    _reset_cache()
    monkeypatch.setenv("WHATSAPP_GROUP_ID", "grupo-casa")
    monkeypatch.setenv("WHATSAPP_GROUP_ID_AUTO", "grupo-auto")

    assert config_provider.bots_ativos(ttl=0) == []
    for canal, arquivo, grupo in (
        ("achadinhos", "config.json", "grupo-casa"),
        ("auto", "config.auto.json", "grupo-auto"),
    ):
        with channels.usar_canal(canal):
            assert channels.grupo_whatsapp() == grupo
            assert channels.load_filtros() == json.loads(
                (ROOT / arquivo).read_text(encoding="utf-8")
            )


def test_seed_pausado_nao_tira_worker_do_legado(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    test_url = session_factory.kw["bind"].url.render_as_string(hide_password=False)
    monkeypatch.setattr(settings, "database_url", test_url)
    monkeypatch.setenv("ADMIN_EMAIL", "seed-worker@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-de-teste")
    monkeypatch.setenv("WHATSAPP_GROUP_ID", "grupo-legado")
    run_seed()
    _patch_sessions(monkeypatch, session_factory)
    _reset_cache()

    with session_factory() as session:
        assert list(session.scalars(select(Bot.status).order_by(Bot.slug))) == [
            "paused",
            "paused",
        ]
    assert channels.canais_ativos() == tuple(
        key for key, value in channels.CANAIS.items() if value.get("ativo", True)
    )
    with channels.usar_canal("achadinhos"):
        assert channels.grupo_whatsapp() == "grupo-legado"


def test_bots_ativos_banco_inacessivel_retorna_vazio(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_cache()
    monkeypatch.setattr(config_provider, "_carregar", lambda: (_ for _ in ()).throw(OSError("off")))
    assert config_provider.bots_ativos(ttl=0) == []


def test_tabelas_ausentes_nao_propagam(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_cache()

    @contextmanager
    def missing_tables():
        raise RuntimeError("relation bots does not exist")
        yield

    monkeypatch.setattr(db, "get_session", missing_tables)
    assert config_provider.bots_ativos(ttl=0) == []


def test_falha_de_telemetria_nao_impede_ciclo(monkeypatch: pytest.MonkeyPatch) -> None:
    executou = []
    monkeypatch.setattr(commands, "drenar_comandos", lambda: None)
    monkeypatch.setattr(channels, "bot_atual", lambda: None)
    monkeypatch.setattr(monitor, "bot_atual", lambda: None)
    monkeypatch.setattr(
        monitor,
        "_executar_ciclo",
        lambda: (executou.append(True) or (0, 0, False)),
    )

    def falha(*_args, **_kwargs):
        raise RuntimeError("telemetria fora")

    monkeypatch.setattr(monitor.telemetry, "iniciar_ciclo", falha)
    monkeypatch.setattr(monitor.telemetry, "finalizar_ciclo", falha)
    monkeypatch.setattr(monitor.telemetry, "heartbeat", falha)
    monitor.ciclo()
    assert executou == [True]


def test_settings_do_banco_e_ttl_sem_sleep(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    bot, _ = _active_bot(session_factory)
    clock = [100.0]
    monkeypatch.setattr(config_provider.time, "monotonic", lambda: clock[0])
    _reset_cache()

    runtime = config_provider.bots_ativos(ttl=30)[0]
    token = f"db:{runtime.id}:{runtime.group_ids[0]}"
    with channels.usar_canal(token):
        assert channels.load_filtros()["preco_minimo"] == 25

    with session_factory.begin() as session:
        stored = session.get(Bot, bot.id)
        changed = dict(stored.settings)
        changed["filters"] = dict(changed["filters"], preco_minimo=77)
        stored.settings = changed

    assert config_provider.bots_ativos(ttl=30)[0].settings.filters.preco_minimo == 25
    clock[0] += 31
    assert config_provider.bots_ativos(ttl=30)[0].settings.filters.preco_minimo == 77


def test_settings_invalido_isola_apenas_um_bot(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    valid, _ = _active_bot(session_factory, slug="valido")
    invalid, _ = _active_bot(session_factory, slug="invalido")
    with session_factory.begin() as session:
        stored = session.get(Bot, invalid.id)
        broken = dict(stored.settings)
        broken["pacing"] = dict(broken["pacing"], max_ofertas_por_ciclo=0)
        stored.settings = broken
    _reset_cache()

    runtimes = config_provider.bots_ativos(ttl=0)
    assert [runtime.id for runtime in runtimes] == [valid.id]


def test_bot_ativo_sem_grupo_e_ignorado_emite_evento_e_um_alerta(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    bot, _ = _active_bot(session_factory, slug="incompleto")
    with session_factory.begin() as session:
        session.query(BotGroup).filter(BotGroup.bot_id == bot.id).delete()
    _reset_cache()

    assert config_provider.bots_ativos(ttl=0) == []
    assert config_provider.bots_ativos(ttl=0) == []
    detector = next(item for item in DETECTORS if item.name == "bot_not_runnable")
    detect_alerts(detectors=[detector])
    detect_alerts(detectors=[detector])

    with session_factory() as session:
        events = list(
            session.scalars(select(Event).where(Event.type == "bot_not_runnable"))
        )
        alerts = list(
            session.scalars(select(Alert).where(Alert.type == "bot_not_runnable"))
        )
    assert len(events) == 2
    assert all(event.level == "warning" for event in events)
    assert len(alerts) == 1
    assert alerts[0].dedup_key == f"bot_not_runnable:{bot.id}"


def test_apenas_bots_rodaveis_viram_canais_e_zero_rodaveis_usa_legado(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    runnable, _ = _active_bot(session_factory, slug="rodavel")
    broken, _ = _active_bot(session_factory, slug="sem-grupo")
    with session_factory.begin() as session:
        session.query(BotGroup).filter(BotGroup.bot_id == broken.id).delete()
    _reset_cache()

    canais = channels.canais_ativos()
    assert len(canais) == 2
    assert all(canal.startswith(f"db:{runnable.id}:") for canal in canais)

    with session_factory.begin() as session:
        session.query(BotGroup).filter(BotGroup.bot_id == runnable.id).delete()
    _reset_cache()
    assert channels.canais_ativos() == tuple(
        key for key, value in channels.CANAIS.items() if value.get("ativo", True)
    )


def test_job_de_banco_volta_a_executar_legado_quando_fica_sem_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ciclos: list[str] = []

    @contextmanager
    def canal_em_teste(canal: str):
        ciclos.append(canal)
        yield

    monkeypatch.setattr(worker_main, "canais_ativos", lambda: ("achadinhos",))
    monkeypatch.setattr(worker_main, "usar_canal", canal_em_teste)
    monkeypatch.setattr(worker_main.monitor, "ciclo", lambda: None)
    worker_main._database_mode = True

    worker_main._ciclos_banco()

    assert ciclos == ["achadinhos"]
    assert worker_main._database_mode is False


def test_drenagem_falha_nao_bloqueia_proximo_comando(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    bot, _ = _active_bot(session_factory)
    with session_factory.begin() as session:
        session.add_all(
            [
                Command(bot_id=bot.id, type="pause", payload={}, status="pending"),
                Command(bot_id=bot.id, type="desconhecido", payload={}, status="pending"),
                Command(bot_id=bot.id, type="reload_config", payload={}, status="pending"),
            ]
        )

    commands.drenar_comandos()

    with session_factory() as session:
        assert session.get(Bot, bot.id).status == "paused"
        statuses = list(session.scalars(select(Command.status).order_by(Command.id)))
    assert statuses == ["done", "failed", "done"]


def test_ciclo_grava_automation_run(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    _patch_sessions(monkeypatch, session_factory)
    _active_bot(session_factory)
    _reset_cache()
    runtime = config_provider.bots_ativos(ttl=0)[0]
    token = f"db:{runtime.id}:{runtime.group_ids[0]}"
    monkeypatch.setattr(monitor, "FONTES", [])
    # Em produção ofertas/envios sempre existem (ADR-012: as migrations não as
    # criam). O ciclo consulta envios (grupo_ja_enviou), então o teste as cria.
    with session_factory.begin() as session:
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)

    with channels.usar_canal(token):
        monitor.ciclo()

    with session_factory() as session:
        run = session.scalar(select(AutomationRun).where(AutomationRun.bot_id == runtime.id))
    assert run is not None
    assert run.status == "success"
    assert run.offers_found == 0
