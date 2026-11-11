# ruff: noqa: F401, F811
"""Caracterização das regras atuais de reenvio."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from core import repositories
from core.models import Envio, Group, Oferta
from tests.test_api import add_user, session_factory  # noqa: F401
from worker.dedup import deve_enviar


@pytest.fixture
def oferta_e_sessao(session_factory) -> tuple[Oferta, Session]:
    owner = add_user(session_factory, email="dedup@teste.com")
    session = session_factory()
    Oferta.__table__.create(session.connection(), checkfirst=True)
    Envio.__table__.create(session.connection(), checkfirst=True)
    session.info["tenant_id"] = owner.tenant_id
    session.add(Group(owner_id=owner.tenant_id, whatsapp_id="grupo", name="Grupo"))
    oferta = Oferta(
        nome="Air fryer para cozinha",
        preco=100.0,
        loja="Shopee",
        url="https://example.test/produto",
        sku="sku-1",
    )
    session.add(oferta)
    session.flush()
    try:
        yield oferta, session
    finally:
        session.close()


def test_primeira_vez_envia(oferta_e_sessao: tuple[Oferta, Session]) -> None:
    oferta, session = oferta_e_sessao

    enviar, _ = deve_enviar(
        session, oferta.id, 100.0, 15.0, nome=oferta.nome, tenant_id=session.info["tenant_id"]
    )

    assert enviar is True


def test_repetida_nao_envia(oferta_e_sessao: tuple[Oferta, Session]) -> None:
    oferta, session = oferta_e_sessao
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 100.0, "sucesso")

    enviar, _ = deve_enviar(
        session, oferta.id, 100.0, 15.0, grupo="grupo", tenant_id=session.info["tenant_id"]
    )

    assert enviar is False


def test_preco_caiu_o_suficiente_reenvia(oferta_e_sessao: tuple[Oferta, Session]) -> None:
    oferta, session = oferta_e_sessao
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 100.0, "sucesso")

    enviar, _ = deve_enviar(
        session, oferta.id, 80.0, 15.0, grupo="grupo", tenant_id=session.info["tenant_id"]
    )

    assert enviar is True


def test_preco_caiu_de_menos_nao_reenvia(oferta_e_sessao: tuple[Oferta, Session]) -> None:
    oferta, session = oferta_e_sessao
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 100.0, "sucesso")

    enviar, _ = deve_enviar(
        session, oferta.id, 90.0, 15.0, grupo="grupo", tenant_id=session.info["tenant_id"]
    )

    assert enviar is False


def test_cupom_mesmo_dia_nao_reenvia(oferta_e_sessao: tuple[Oferta, Session], monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from core import relogio
    from worker import dedup as dedup_mod

    oferta, session = oferta_e_sessao
    br = ZoneInfo("America/Sao_Paulo")
    agora = datetime(2026, 11, 10, 15, 0, tzinfo=br)
    monkeypatch.setattr(relogio, "agora_br", lambda: agora)
    monkeypatch.setattr(dedup_mod, "_mesmo_dia_brasilia", lambda _quando: True)
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 0.0, "sucesso")

    enviar, motivo = deve_enviar(
        session,
        oferta.id,
        0.0,
        15.0,
        grupo="grupo",
        categoria="cupom",
        tenant_id=session.info["tenant_id"],
    )

    assert enviar is False
    assert "hoje" in motivo


def test_cupom_outro_dia_reenvia(oferta_e_sessao: tuple[Oferta, Session], monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from core import relogio
    from worker import dedup as dedup_mod

    oferta, session = oferta_e_sessao
    br = ZoneInfo("America/Sao_Paulo")
    agora = datetime(2026, 11, 11, 10, 0, tzinfo=br)
    monkeypatch.setattr(relogio, "agora_br", lambda: agora)
    monkeypatch.setattr(dedup_mod, "_mesmo_dia_brasilia", lambda _quando: False)
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 0.0, "sucesso")

    enviar, motivo = deve_enviar(
        session,
        oferta.id,
        0.0,
        15.0,
        grupo="grupo",
        categoria="cupom",
        tenant_id=session.info["tenant_id"],
    )

    assert enviar is True
    assert "novo dia" in motivo
