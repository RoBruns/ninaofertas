"""Caracterização das regras atuais de reenvio."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core import repositories
from core.models import Base, Oferta
from worker.dedup import deve_enviar


@pytest.fixture
def oferta_e_sessao() -> tuple[Oferta, Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine)
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

    enviar, _ = deve_enviar(session, oferta.id, 100.0, 15.0, nome=oferta.nome)

    assert enviar is True


def test_repetida_nao_envia(oferta_e_sessao: tuple[Oferta, Session]) -> None:
    oferta, session = oferta_e_sessao
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 100.0, "sucesso")

    enviar, _ = deve_enviar(session, oferta.id, 100.0, 15.0, grupo="grupo")

    assert enviar is False


def test_preco_caiu_o_suficiente_reenvia(oferta_e_sessao: tuple[Oferta, Session]) -> None:
    oferta, session = oferta_e_sessao
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 100.0, "sucesso")

    enviar, _ = deve_enviar(session, oferta.id, 80.0, 15.0, grupo="grupo")

    assert enviar is True


def test_preco_caiu_de_menos_nao_reenvia(oferta_e_sessao: tuple[Oferta, Session]) -> None:
    oferta, session = oferta_e_sessao
    repositories.registrar_envio(session, oferta.id, "grupo", "mensagem", 100.0, "sucesso")

    enviar, _ = deve_enviar(session, oferta.id, 90.0, 15.0, grupo="grupo")

    assert enviar is False
