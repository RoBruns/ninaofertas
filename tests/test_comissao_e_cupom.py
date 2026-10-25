"""Piso de comissão estimada e cupom da Shopee que antes quebrava na captura."""
# ruff: noqa: F811
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core import config_provider
from core.bot_settings import BotSettings
from core.platforms.base import OfertaCapturada
from core.platforms.shopee import _comissao_fracao
from worker.filters import passa_nos_filtros
from worker.monitor import _ordenar_envio, _prioridade_do_ciclo
from worker.sources import cupons
from worker.sources.cupons import CupomScraper, _cupom_explicito
from tests.test_api import session_factory  # noqa: F401
from tests.test_multigrupo import _preparar
from worker import monitor


def _oferta(**campos) -> OfertaCapturada:
    base = {
        "nome": "Organizador de cozinha",
        "preco": 100,
        "loja": "Shopee",
        "url": "https://s.shopee.com.br/produto",
    }
    base.update(campos)
    return OfertaCapturada(**base)


def test_taxa_maior_que_um_vira_fracao():
    assert _comissao_fracao("0.03") == 0.03
    assert _comissao_fracao(3) == 0.03
    assert _comissao_fracao(None) is None


def test_piso_de_comissao_em_reais():
    piso = {"comissao_minima_reais": 1}
    barata = _oferta(preco=10, comissao_pct=0.03)
    boa = _oferta(preco=80, comissao_pct=0.03)
    assert passa_nos_filtros(barata, piso) == (
        False,
        "comissão estimada R$0.30 abaixo do mínimo R$1.00",
    )
    assert passa_nos_filtros(boa, piso)[0]
    assert passa_nos_filtros(_oferta(loja="Mercado Livre", preco=10), piso)[0]
    assert passa_nos_filtros(barata, {"comissao_minima_reais": 0})[0]


def test_comissao_maior_vai_na_frente_da_mesma_loja():
    baixa = _oferta(nome="baixa", url="https://s.shopee.com.br/baixa", preco=10, comissao_pct=0.03)
    alta = _oferta(nome="alta", url="https://s.shopee.com.br/alta", preco=80, comissao_pct=0.03)
    sem = _oferta(nome="sem", url="https://s.shopee.com.br/sem")
    ml = _oferta(loja="Mercado Livre", nome="ml", url="https://www.mercadolivre.com.br/ml")
    resultado = _ordenar_envio([baixa, ml, sem, alta], 1, "Shopee", "novidades")
    assert [o.nome for o in resultado] == ["alta", "ml", "baixa", "sem"]


def test_prioridade_loja_padrao_e_rejeita_valor_estranho():
    assert BotSettings().filters.prioridade_loja == "alternar"
    with pytest.raises(ValidationError):
        BotSettings.model_validate({"filters": {"prioridade_loja": "amazon"}})
    escolhida = BotSettings.model_validate({"filters": {"prioridade_loja": "mercado_livre"}})
    assert escolhida.filters.prioridade_loja == "mercado_livre"


def test_alternar_revez_e_mercado_livre_empilha():
    assert _prioridade_do_ciclo({}, 1) == ("Shopee", False)
    assert _prioridade_do_ciclo({}, 2) == ("Mercado Livre", False)
    assert _prioridade_do_ciclo({"prioridade_loja": "mercado_livre"}, 1) == (
        "Mercado Livre",
        True,
    )
    assert _prioridade_do_ciclo({"prioridade_loja": "shopee"}, 2) == ("Shopee", True)


def test_mercado_livre_na_frente_e_shopee_de_reserva():
    baixa = _oferta(nome="baixa", url="https://s.shopee.com.br/baixa", preco=10, comissao_pct=0.03)
    alta = _oferta(nome="alta", url="https://s.shopee.com.br/alta", preco=80, comissao_pct=0.03)
    ml = _oferta(loja="Mercado Livre", nome="ml", url="https://www.mercadolivre.com.br/ml")
    cupom = _oferta(categoria="cupom", nome="cupom", url="https://s.shopee.com.br/cupom")
    resultado = _ordenar_envio(
        [baixa, ml, alta, cupom], 1, "Mercado Livre", "novidades", empilhar=True
    )
    assert [o.nome for o in resultado] == ["cupom", "ml", "alta", "baixa"]


def test_cupom_shopee_na_frente_em_qualquer_ciclo():
    produto = _oferta(nome="panela", url="https://s.shopee.com.br/panela")
    cupom = _oferta(categoria="cupom", nome="cupom", url="https://s.shopee.com.br/cupom")
    ml = _oferta(
        categoria="cupom",
        loja="Mercado Livre",
        nome="mlcupom",
        url="https://www.mercadolivre.com.br/cupom",
    )
    so_shopee = _ordenar_envio([produto, cupom], 1, "Shopee", "novidades")
    assert so_shopee[0].categoria == "cupom"
    com_ml = _ordenar_envio([produto, ml], 1, "Shopee", "novidades")
    assert [o.nome for o in com_ml] == ["panela", "mlcupom"]


def test_parse_voucher_shopee():
    oferta = CupomScraper()._parse_shopee(
        {
            "offerLink": "https://s.shopee.com.br/abc",
            "voucherCode": "nina10",
            "discountPercentage": 20,
            "minSpend": 99,
        }
    )
    assert oferta is not None
    assert oferta.categoria == "cupom"
    assert oferta.codigo_cupom == "NINA10"
    assert oferta.nome == "20% OFF em R$99: NINA10"


def test_fallback_ignora_campanha_sem_codigo_ou_desconto():
    assert not _cupom_explicito({"offerName": "20% OFF na Shopee"})
    assert _cupom_explicito({"offerName": "Use NINA10 agora"})
    assert _cupom_explicito({"offerName": "desconto", "discountValue": 15})


def test_voucher_invalido_nao_derruba_os_outros(monkeypatch):
    scraper = CupomScraper()
    ruim = {
        "offerLink": "https://s.shopee.com.br/ruim",
        "voucherCode": "RUIM10",
        "discountValue": 10,
    }
    bom = {
        "offerLink": "https://s.shopee.com.br/bom",
        "voucherCode": "NINA10",
        "discountValue": 20,
    }
    monkeypatch.setattr(cupons, "credenciais_shopee_do_bot", lambda: (None, "app", "secret"))
    monkeypatch.setattr(scraper, "_shopee_voucher_nodes", lambda: [ruim, bom])
    chamadas = {"n": 0}
    real = cupons._linha_beneficio

    def explode(desc, codigo):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("quebrado")
        return real(desc, codigo)

    monkeypatch.setattr(cupons, "_linha_beneficio", explode)
    out = scraper._shopee()
    assert [o.codigo_cupom for o in out] == ["NINA10"]


def test_teto_de_cupom_nao_cala_o_produto(monkeypatch, session_factory):
    cupom = OfertaCapturada(
        nome="20% OFF",
        preco=0,
        loja="Shopee",
        url="https://s.shopee.com.br/cupom",
        categoria="cupom",
        codigo_cupom="NINA10",
    )
    produto = OfertaCapturada(
        nome="Panela",
        preco=80,
        loja="Shopee",
        url="https://s.shopee.com.br/panela",
        comissao_pct=0.05,
    )
    _runtime, enviados = _preparar(monkeypatch, session_factory, [cupom, produto])
    monkeypatch.setattr(monitor.repositories, "contar_cupons_hoje", lambda *_a, **_k: 2)
    with config_provider.usar_bot_runtime(_runtime):
        monitor.ciclo()
    assert enviados
    assert all("Panela" in mensagem for _, mensagem in enviados)
    assert all("NINA10" not in mensagem for _, mensagem in enviados)
