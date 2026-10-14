# ruff: noqa: F401, F811
"""Freio por conta e recado opt-in, sem chamadas ao WhatsApp real."""

from dataclasses import replace
from datetime import timedelta

from sqlalchemy import select

from core import config_provider, relogio, repositories
from core.bot_settings import BotSettings
from core.models import Envio, Group, Oferta, Tenant
from tests.runtime_helpers import runtime_do_config
from tests.test_api import session_factory
from tests.test_tenant_isolation import operations
from tests.test_worker_config import _patch_sessions
from worker import channels, monitor, promo_instagram


def runtime(operation, *, recado=False, teste=False):
    user, ids, _ = operation
    settings = BotSettings(
        content={"recado_instagram": recado},
        schedule={"quiet_hours": {"start": "00:00", "end": "00:00"}},
    )
    return replace(
        runtime_do_config("config.json"),
        id=ids["bot_id"],
        owner_id=user.tenant_id,
        settings=settings,
        group_ids=(f"{user.email[0]}-{ids['group_id']}@g.us",),
        is_test=teste,
    )


def sends_for_a(factory, operations):
    a, ids, _ = operations[0]
    now = relogio.agora_banco()
    with factory.begin() as session:
        group = session.get(Group, ids["group_id"])
        for index, bot_id in enumerate((ids["bot_id"], None)):
            offer = Oferta(
                nome="Teste",
                preco=10,
                url=f"https://teste/{index}",
                categoria="cupom" if index else "produto",
            )
            session.add(offer)
            session.flush()
            session.add(
                Envio(
                    oferta_id=offer.id,
                    bot_id=bot_id,
                    group_id=group.id,
                    grupo=group.whatsapp_id,
                    status="sucesso",
                    enviado_em=now - timedelta(minutes=10),
                )
            )
    return now


def test_teto_da_conta_a_nao_freia_b_e_legado_so_conta_para_a(session_factory, operations):
    now = sends_for_a(session_factory, operations)
    ra, rb = runtime(operations[0]), runtime(operations[1])
    with session_factory() as session:
        for r, count in ((ra, 2), (rb, 0)):
            assert (
                repositories.contar_envios_desde(
                    session, now - timedelta(hours=1), tenant_id=r.owner_id, excluir_bots_teste=True
                )
                == count
            )
        assert repositories.minutos_desde_ultimo_envio(session, tenant_id=rb.owner_id) is None
        assert repositories.minutos_desde_ultimo_envio(session, tenant_id=ra.owner_id) is not None
        with config_provider.usar_bot_runtime(ra):
            assert not monitor._freio_anti_ban(
                session, {"max_ofertas_globais_por_dia": 2}, ra.group_ids[0]
            )[0]
        with config_provider.usar_bot_runtime(rb):
            assert monitor._freio_anti_ban(
                session, {"max_ofertas_globais_por_dia": 2}, rb.group_ids[0]
            )[0]


def test_uma_conta_mesmo_resultado_do_freio_anterior(session_factory, operations, monkeypatch):
    now = sends_for_a(session_factory, operations)
    monkeypatch.setattr(relogio, "agora_banco", lambda: now)
    ra = runtime(operations[0])
    scenarios = [
        {},
        {"intervalo_minutos_entre_ofertas": 15},
        {"intervalo_minutos_entre_ofertas": 5},
        {
            "max_ofertas_por_rajada": 2,
            "janela_rajada_minutos": 15,
            "pausa_entre_rajadas_minutos": 35,
        },
        {"max_ofertas_globais_por_hora": 2},
        {"max_ofertas_globais_por_hora": 3},
        {"max_ofertas_globais_por_dia": 2},
        {"max_ofertas_globais_por_dia": 0},
        {"max_ofertas_por_hora": 2},
        {"max_ofertas_por_dia": 2},
        {"max_ofertas_por_dia": 0},
    ]
    with session_factory() as session:
        # Resultados caracterizados antes da S1c para uma única conta.
        expected = [True, False, True, False, False, True, False, True, False, False, True]
        for settings, before in zip(scenarios, expected, strict=True):
            with config_provider.usar_bot_runtime(ra):
                after = monitor._freio_anti_ban(session, settings, ra.group_ids[0])
            assert before == after[0]
        # Teste mantém escopo próprio; os envios legados da conta não entram.
        assert (
            repositories.contar_envios_desde(session, now - timedelta(hours=1), escopo_bot_id=ra.id, tenant_id=ra.owner_id)
            == 1
        )


def test_recado_por_bot_e_intervalo_independente_da_outra_conta(
    session_factory, operations, monkeypatch, tmp_path
):
    _patch_sessions(monkeypatch, session_factory)
    sends_for_a(session_factory, operations)
    # Oferta recém enviada pela conta A não adia recado da conta B.
    with session_factory.begin() as session:
        for envio in session.scalars(select(Envio)):
            envio.enviado_em = relogio.agora_banco()
    ra, rb = runtime(operations[0], recado=False), runtime(operations[1], recado=True)
    monkeypatch.setattr(channels, "bots_ativos", lambda: [ra, rb])
    monkeypatch.setattr(promo_instagram.time, "sleep", lambda _: None)
    foto = tmp_path / "vo.jpg"
    foto.write_bytes(b"foto")
    monkeypatch.setattr(promo_instagram, "FOTO", foto)
    sent = []
    monkeypatch.setattr(
        promo_instagram.whatsapp,
        "enviar_mensagem",
        lambda mensagem, **kw: sent.append((mensagem, kw)) or True,
    )
    promo_instagram.ciclo()
    assert len(sent) == 1 and sent[0][0] == promo_instagram.MENSAGEM
    assert sent[0][1]["grupo"] == rb.group_ids[0]
    with session_factory() as session:
        envio = session.scalar(select(Envio).join(Oferta).where(Oferta.sku == promo_instagram.SKU))
        assert envio.bot_id == rb.id and envio.group_id == operations[1][1]["group_id"]
    promo_instagram.ciclo()
    assert len(sent) == 1  # continua respeitando as quatro horas


def test_worker_ignora_conta_suspensa_mesmo_com_bot_ativo(session_factory, operations, monkeypatch):
    _patch_sessions(monkeypatch, session_factory)
    b = operations[1][0]
    with session_factory.begin() as session:
        session.get(Tenant, b.tenant_id).status = "suspended"
    loaded = config_provider._carregar()
    assert len(loaded) == 1 and loaded[0].owner_id == operations[0][0].tenant_id


def test_flag_da_migracao_preserva_runtime_de_settings_planos():
    original = {
        "preco_minimo": 77,
        "intervalo_minutos_entre_ofertas": 11,
        "quiet_hours": {"start": "01:00", "end": "09:00"},
        "aceitar_cupons": False,
    }
    before = runtime_do_config("config.json")
    before = replace(before, settings=BotSettings.model_validate(original))
    after = replace(
        before,
        settings=BotSettings.model_validate({**original, "content": {"recado_instagram": True}}),
    )
    with config_provider.usar_bot_runtime(before):
        previous = config_provider.load_filtros_runtime()
    with config_provider.usar_bot_runtime(after):
        current = config_provider.load_filtros_runtime()
    assert current == {**previous, "recado_instagram": True}
    assert after.settings.content.recado_instagram is True
