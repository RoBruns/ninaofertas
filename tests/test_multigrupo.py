# ruff: noqa: F401, F811
"""Bot com vários grupos: a mesma oferta vai para todos, e o freio conta 1 por oferta.

Bug de produção (2026-09-29): com um ciclo por (bot, grupo) e o freio por número,
o primeiro grupo sempre perdia a vez — 208 envios no Cozinha, zero no Achadinhos.
Decisão do usuário (ADR-021): mesma oferta em todos os grupos, 1 slot do freio
por oferta.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core import config_provider, relogio, repositories
from core.models import Envio, Oferta
from core.platforms.affiliate import AffiliateLink
from core.platforms.base import OfertaCapturada
from tests.test_api import session_factory
from tests.test_bots_api import safe_settings
from tests.test_worker_config import _active_bot, _patch_sessions, _reset_cache
from worker import monitor


def _preparar(monkeypatch: pytest.MonkeyPatch, factory: sessionmaker[Session], ofertas):
    _patch_sessions(monkeypatch, factory)
    settings = safe_settings()
    settings["content"]["baseline_ciclos"] = 0  # sem os ciclos de baseline do bot novo
    bot, catalog = _active_bot(factory, settings=settings)
    _reset_cache()
    runtime = config_provider.bots_ativos(ttl=0)[0]
    with factory.begin() as session:
        Oferta.__table__.create(session.connection(), checkfirst=True)
        Envio.__table__.create(session.connection(), checkfirst=True)

    fonte = type("Fonte", (), {"nome_fonte": "Teste", "executar": lambda self: list(ofertas)})()
    enviados: list[tuple[str, str]] = []
    monkeypatch.setattr(monitor, "FONTES", [fonte])
    monkeypatch.setattr(monitor, "_SLUG_POR_LOJA", {"Shopee": "shopee"})
    monkeypatch.setattr(monitor, "platforms_with_usable_credentials", lambda _ids: {"shopee"})
    monkeypatch.setattr(monitor, "passa_nos_filtros", lambda *_a: (True, ""))
    monkeypatch.setattr(monitor.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        monitor.affiliate,
        "garantir_afiliado",
        lambda _loja, url, **kw: AffiliateLink(f"{url}?grupo={kw.get('group_id')}", None),
    )
    monkeypatch.setattr(
        monitor.whatsapp,
        "enviar_mensagem",
        lambda _msg, imagem=None, grupo=None: enviados.append((grupo, _msg)) or True,
    )
    return runtime, enviados


def _oferta(nome: str) -> OfertaCapturada:
    return OfertaCapturada(
        nome=nome, preco=100.0, preco_anterior=200.0, loja="Shopee",
        url=f"https://shopee.com.br/{nome.replace(' ', '-')}",
    )


def test_mesma_oferta_vai_para_os_dois_grupos_primeiro_quem_esperou_mais(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> None:
    runtime, enviados = _preparar(monkeypatch, session_factory, [_oferta("Panela de pressao")])
    grupo_a, grupo_b = runtime.group_ids
    # grupo_a recebeu há pouco; grupo_b nunca recebeu -> grupo_b vai primeiro.
    with session_factory.begin() as session:
        antiga = repositories.upsert_oferta(
            session, {"nome": "antiga", "preco": 10.0, "loja": "Shopee", "url": "https://x/antiga"}
        )
        repositories.registrar_envio(session, antiga.id, grupo_a, "m", 10.0, "sucesso")
        session.execute(
            Envio.__table__.update().values(enviado_em=relogio.agora_banco() - timedelta(hours=2))
        )

    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()

    assert [grupo for grupo, _ in enviados] == [grupo_b, grupo_a]
    with session_factory() as session:
        grupos = set(
            session.scalars(
                select(Envio.grupo).join(Oferta).where(
                    Oferta.nome == "Panela de pressao", Envio.status == "sucesso"
                )
            )
        )
    assert grupos == {grupo_a, grupo_b}


def test_freio_conta_uma_vez_por_oferta_e_nao_por_grupo(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> None:
    runtime, enviados = _preparar(
        monkeypatch, session_factory, [_oferta("Air fryer"), _oferta("Liquidificador")]
    )
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()

    # Uma oferta nos 2 grupos = 2 mensagens, mas 1 slot do freio.
    assert len(enviados) == 2
    with session_factory() as session:
        desde = relogio.agora_banco() - timedelta(hours=1)
        assert repositories.contar_envios_desde(session, desde) == 1
        for grupo in runtime.group_ids:
            assert repositories.contar_envios_desde(session, desde, grupo=grupo) == 1

    # O intervalo entre ofertas (5 min) barra a próxima oferta, não a 2ª mensagem.
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()
    assert len(enviados) == 2


def test_falha_num_grupo_nao_impede_o_outro(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> None:
    runtime, enviados = _preparar(monkeypatch, session_factory, [_oferta("Chaleira")])
    grupo_a, grupo_b = runtime.group_ids

    def envio(_msg, imagem=None, grupo=None):
        enviados.append((grupo, _msg))
        return grupo != grupo_a

    monkeypatch.setattr(monitor.whatsapp, "enviar_mensagem", envio)
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()

    assert {grupo for grupo, _ in enviados} == {grupo_a, grupo_b}
    with session_factory() as session:
        status = dict(session.execute(select(Envio.grupo, Envio.status)).all())
    assert status[grupo_b] == "sucesso"
    assert status[grupo_a] != "sucesso"
