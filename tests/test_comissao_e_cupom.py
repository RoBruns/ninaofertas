"""Piso de comissão estimada, prioridade suave e cupom afiliado."""
# ruff: noqa: F811
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core import config_provider
from core.bot_settings import BotSettings
from core.platforms.affiliate import link_rastreado
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


def test_mercado_livre_preferido_mantem_shopee_na_reserva():
    baixa = _oferta(nome="baixa", url="https://s.shopee.com.br/baixa", preco=10, comissao_pct=0.03)
    alta = _oferta(nome="alta", url="https://s.shopee.com.br/alta", preco=80, comissao_pct=0.03)
    ml = _oferta(loja="Mercado Livre", nome="ml", url="https://www.mercadolivre.com.br/ml")
    cupom = _oferta(categoria="cupom", nome="cupom", url="https://s.shopee.com.br/cupom")
    resultado = _ordenar_envio(
        [baixa, ml, alta, cupom], 1, "Mercado Livre", "novidades", empilhar=True
    )
    assert [o.nome for o in resultado] == ["ml", "alta", "baixa", "cupom"]


def test_sem_venda_indireta_cupom_nao_rouba_a_vaga():
    produto = _oferta(nome="panela", url="https://s.shopee.com.br/panela")
    cupom = _oferta(categoria="cupom", nome="cupom", url="https://s.shopee.com.br/cupom")
    ml = _oferta(
        categoria="cupom",
        loja="Mercado Livre",
        nome="mlcupom",
        url="https://meli.la/abc",
    )
    so_shopee = _ordenar_envio([produto, cupom], 1, "Shopee", "novidades")
    assert [o.nome for o in so_shopee] == ["panela", "cupom"]
    com_ml = _ordenar_envio([produto, ml], 1, "Shopee", "novidades")
    assert [o.nome for o in com_ml] == ["panela", "mlcupom"]


def test_venda_indireta_poe_o_cupom_da_loja_prioritaria_na_frente():
    assert BotSettings().content.cupom_venda_indireta is False
    produto = _oferta(nome="panela", url="https://s.shopee.com.br/panela")
    shopee = _oferta(categoria="cupom", nome="shopee", url="https://s.shopee.com.br/cupom")
    ml = _oferta(
        categoria="cupom",
        loja="Mercado Livre",
        nome="mlcupom",
        url="https://www.mercadolivre.com.br/cupons",
    )
    desligado = _ordenar_envio([produto, shopee, ml], 2, "Mercado Livre", cupom_indireta=False)
    assert [o.nome for o in desligado] == ["panela", "shopee", "mlcupom"]
    ligado = _ordenar_envio(
        [produto, shopee, ml], 2, "Mercado Livre", cupom_indireta=True
    )
    assert [o.nome for o in ligado] == ["mlcupom", "shopee", "panela"]
    assert not link_rastreado("Mercado Livre", "https://www.mercadolivre.com.br/cupons")
    assert link_rastreado("Mercado Livre", "https://meli.la/abc")


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
    assert CupomScraper()._parse_shopee({"voucherCode": "NINA10", "discountPercentage": 20}) is None


def test_meli_manual_ignora_pagina_generica_e_lista_vazia(monkeypatch):
    monkeypatch.setattr(cupons, "load_filtros", lambda: {"cupons_meli": []})
    assert CupomScraper()._meli() == []
    monkeypatch.setattr(
        cupons,
        "load_filtros",
        lambda: {
            "cupons_meli": [
                {"url": "https://www.mercadolivre.com.br/cupons", "titulo": "genérico"},
                {
                    "url": "https://www.mercadolivre.com.br/oferta/MLB1",
                    "titulo": "20% OFF",
                    "codigo": "CASA20",
                },
            ]
        },
    )
    out = CupomScraper()._meli()
    assert len(out) == 1
    assert out[0].url.endswith("/MLB1")
    assert out[0].codigo_cupom == "CASA20"


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


def _preparar_duas_lojas(monkeypatch, session_factory, ofertas, filtros_extra=None):
    runtime, enviados = _preparar(
        monkeypatch,
        session_factory,
        ofertas,
        {"prioridade_loja": "mercado_livre", **(filtros_extra or {})},
    )
    monkeypatch.setattr(
        monitor,
        "_SLUG_POR_LOJA",
        {"Shopee": "shopee", "Mercado Livre": "mercadolivre"},
    )
    monkeypatch.setattr(
        monitor, "platforms_with_usable_credentials", lambda _ids: {"shopee", "mercadolivre"}
    )
    return runtime, enviados


def test_prioridade_meli_falha_afiliado_libera_reserva_no_mesmo_ciclo(
    monkeypatch, session_factory
):
    from core.platforms.affiliate import AffiliateLink

    ml_a = OfertaCapturada(
        nome="ML A", preco=100.0, loja="Mercado Livre", url="https://produto.mercadolivre.com.br/a"
    )
    ml_b = OfertaCapturada(
        nome="ML B", preco=100.0, loja="Mercado Livre", url="https://produto.mercadolivre.com.br/b"
    )
    shopee = OfertaCapturada(
        nome="Shopee boa", preco=80.0, loja="Shopee", url="https://shopee.com.br/boa"
    )
    runtime, enviados = _preparar_duas_lojas(
        monkeypatch, session_factory, [ml_a, ml_b, shopee]
    )
    tentativas: list[str] = []

    def garantir(loja, url, **_kw):
        tentativas.append(loja)
        if "mercado" in loja.lower():
            return AffiliateLink(url)
        return AffiliateLink("https://s.shopee.com.br/ok", None)

    monkeypatch.setattr(monitor.affiliate, "garantir_afiliado", garantir)
    monkeypatch.setattr(monitor.affiliate, "link_rastreado", link_rastreado)
    monkeypatch.setattr(monitor.affiliate, "plataforma_bloqueada_no_ciclo", lambda _s: False)
    monkeypatch.setattr(monitor.affiliate, "reset_aviso_ciclo", lambda: None)

    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()

    assert any("Shopee boa" in mensagem for _, mensagem in enviados)
    # Uma falha MELI basta: não varre a segunda oferta da preferida.
    assert tentativas.count("Mercado Livre") == 1
    assert "Shopee" in tentativas


def test_falha_afiliado_nao_retenta_no_ciclo_seguinte(monkeypatch, session_factory):
    from core.platforms.affiliate import AffiliateLink
    from sqlalchemy import func, select
    from core.models import Envio

    ml = OfertaCapturada(
        nome="ML sem link",
        preco=100.0,
        loja="Mercado Livre",
        url="https://produto.mercadolivre.com.br/x",
    )
    runtime, enviados = _preparar_duas_lojas(monkeypatch, session_factory, [ml])
    chamadas = {"n": 0}

    def garantir(_loja, url, **_kw):
        chamadas["n"] += 1
        return AffiliateLink(url)

    monkeypatch.setattr(monitor.affiliate, "garantir_afiliado", garantir)
    monkeypatch.setattr(monitor.affiliate, "link_rastreado", link_rastreado)
    monkeypatch.setattr(monitor.affiliate, "plataforma_bloqueada_no_ciclo", lambda _s: False)
    monkeypatch.setattr(monitor.affiliate, "reset_aviso_ciclo", lambda: None)

    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()
        monitor.ciclo()

    assert enviados == []
    assert chamadas["n"] == 1
    with session_factory() as session:
        vistos = session.scalar(
            select(func.count())
            .select_from(Envio)
            .where(Envio.status == "visto", Envio.mensagem == "afiliado")
        )
    assert vistos and vistos >= 1


def test_cache_meli_reusa_link_no_mesmo_ciclo(monkeypatch):
    from core.platforms import affiliate

    chamadas = {"n": 0}
    auth = affiliate._MLAuth(None, "tag-bot", "cookie=1")

    def converter(url, tag, _auth, _runtime):
        chamadas["n"] += 1
        return f"https://meli.la/{tag}"

    monkeypatch.setattr(affiliate, "_ml_auth", lambda: (None, auth))
    monkeypatch.setattr(affiliate, "_converter_mercadolivre_com_tag", converter)
    affiliate.reset_aviso_ciclo()
    primeiro = affiliate.garantir_afiliado("Mercado Livre", "https://produto.mercadolivre.com.br/x")
    segundo = affiliate.garantir_afiliado("Mercado Livre", "https://produto.mercadolivre.com.br/x")
    assert primeiro == segundo == "https://meli.la/tag-bot"
    assert chamadas["n"] == 1
    affiliate.reset_aviso_ciclo()
    affiliate.garantir_afiliado("Mercado Livre", "https://produto.mercadolivre.com.br/x")
    assert chamadas["n"] == 2


def test_401_bloqueia_restante_da_plataforma_no_ciclo(monkeypatch, session_factory):
    from core.platforms import affiliate
    from core.platforms.affiliate import AffiliateLink

    ml_a = OfertaCapturada(
        nome="ML A", preco=100.0, loja="Mercado Livre", url="https://produto.mercadolivre.com.br/a"
    )
    ml_b = OfertaCapturada(
        nome="ML B", preco=100.0, loja="Mercado Livre", url="https://produto.mercadolivre.com.br/b"
    )
    shopee = OfertaCapturada(
        nome="Shopee ok", preco=80.0, loja="Shopee", url="https://shopee.com.br/ok"
    )
    runtime, enviados = _preparar_duas_lojas(monkeypatch, session_factory, [ml_a, ml_b, shopee])
    affiliate.reset_aviso_ciclo()
    tentativas: list[str] = []

    def garantir(loja, url, **_kw):
        tentativas.append(f"{loja}|{url}")
        if "mercado" in loja.lower():
            affiliate._bloquear_plataforma("mercadolivre")
            return AffiliateLink(url)
        return AffiliateLink("https://s.shopee.com.br/ok", None)

    monkeypatch.setattr(monitor.affiliate, "garantir_afiliado", garantir)
    # Mantém o bloqueio real entre ofertas do ciclo.
    monkeypatch.setattr(
        monitor.affiliate,
        "plataforma_bloqueada_no_ciclo",
        affiliate.plataforma_bloqueada_no_ciclo,
    )
    monkeypatch.setattr(monitor.affiliate, "link_rastreado", link_rastreado)

    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()

    assert any("Shopee ok" in mensagem for _, mensagem in enviados)
    meli_tentadas = [t for t in tentativas if t.startswith("Mercado Livre")]
    assert len(meli_tentadas) == 1
