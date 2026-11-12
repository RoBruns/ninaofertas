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
    cupons.limpar_cache_cupons_meli()
    monkeypatch.setattr(CupomScraper, "_scrape_cupons_meli", lambda self: [])
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


def test_parse_cupons_meli_html_monta_container():
    html = """
    <div data-campaign="14548284">25% OFF acima de R$79 limite R$40 HOJENOML</div>
    <a href="/x?coupon_campaign_id=14548284">Conferir</a>
    <script>"campaign_id":14066237,"discount":"20% OFF"</script>
    """
    itens = cupons.parse_cupons_meli_html(html)
    ids = {i["campaign_id"] for i in itens}
    assert ids == {"14548284", "14066237"}
    url = cupons.url_container_meli("14548284")
    assert url == (
        "https://lista.mercadolivre.com.br/_Container_14548284?coupon_campaign_id=14548284"
    )
    assert "meli.la" not in url
    um = next(i for i in itens if i["campaign_id"] == "14548284")
    assert "25% OFF" in (um["beneficio"] or "")
    assert "acima de R$79" in (um["beneficio"] or "")


def test_parse_cupons_meli_titulo_com_loja_e_json():
    html = """
    <script type="application/json">
    {"coupons":[{"coupon_campaign_id":"14548284","title":"30% OFF","subtitle":"em LIQUIDA"}]}
    </script>
    <div>outro {"campaign_id":99887766,"label":"15% OFF em Beleza"}</div>
    """
    itens = {i["campaign_id"]: i for i in cupons.parse_cupons_meli_html(html)}
    assert itens["14548284"]["beneficio"] == "30% OFF em LIQUIDA"
    assert itens["99887766"]["beneficio"] == "15% OFF em Beleza"


def test_meli_manual_sem_titulo_herda_do_scrape(monkeypatch):
    cupons.limpar_cache_cupons_meli()
    url = cupons.url_container_meli("14548284")
    scrape = [
        OfertaCapturada(
            nome="30% OFF em LIQUIDA",
            preco=0,
            loja="Mercado Livre",
            url=url,
            categoria="cupom",
            sku="cupom:scrape1",
            beneficio="30% OFF em LIQUIDA",
        )
    ]
    monkeypatch.setattr(CupomScraper, "_scrape_cupons_meli", lambda self: scrape)
    monkeypatch.setattr(
        cupons,
        "load_filtros",
        lambda: {"cupons_meli": [{"url": url}]},
    )
    out = CupomScraper()._meli()
    assert len(out) == 1
    assert out[0].beneficio == "30% OFF em LIQUIDA"


def test_meli_scrape_une_com_manual(monkeypatch):
    cupons.limpar_cache_cupons_meli()
    scrape = [
        OfertaCapturada(
            nome="25% OFF",
            preco=0,
            loja="Mercado Livre",
            url=cupons.url_container_meli("14548284"),
            categoria="cupom",
            sku="cupom:scrape1",
            beneficio="25% OFF",
        )
    ]
    monkeypatch.setattr(CupomScraper, "_scrape_cupons_meli", lambda self: scrape)
    monkeypatch.setattr(
        cupons,
        "load_filtros",
        lambda: {
            "cupons_meli": [
                {
                    "url": "https://meli.la/manual",
                    "titulo": "Cupom manual",
                    "codigo": "MANUAL1",
                }
            ]
        },
    )
    out = CupomScraper()._meli()
    assert len(out) == 2
    assert any("_Container_14548284" in o.url for o in out)
    assert any(o.url.endswith("/manual") for o in out)


def test_meli_scrape_captcha_vira_vazio(monkeypatch):
    class _Resp:
        status_code = 200
        url = "https://www.mercadolivre.com.br/account-verification"
        text = "<html>captcha</html>"

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _Resp()

    cupons.limpar_cache_cupons_meli()
    monkeypatch.setattr(cupons.httpx, "Client", _Client)
    monkeypatch.setattr(
        "core.platforms.affiliate._ml_auth",
        lambda: (
            None,
            type("A", (), {"cookie": "ssid=x", "account_id": None, "account_tag": ""})(),
        ),
    )
    assert CupomScraper()._scrape_cupons_meli() == []


def test_create_link_container_vira_meli_la_e_111_nao_invalida(monkeypatch):
    import httpx
    from uuid import uuid4

    from core.platforms import affiliate

    container = cupons.url_container_meli("14548284")
    assert not link_rastreado("Mercado Livre", container)

    class _Ok:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return httpx.Response(200, request=httpx.Request("GET", "https://x"))

        def post(self, url, **kwargs):
            body = {"urls": [{"short_url": "https://meli.la/cupomML"}], "total_success": 1}
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    auth = affiliate._MLAuth(account_id=None, account_tag="nina-tag", cookie="ssid=ok;_csrf=tok")
    monkeypatch.setattr(affiliate.httpx, "Client", _Ok)
    converted = affiliate._converter_mercadolivre_com_tag(container, "nina-tag", auth, None)
    assert converted == "https://meli.la/cupomML"
    assert link_rastreado("Mercado Livre", converted)

    recusado = {
        "urls": [
            {
                "origin_url": container,
                "message": "URL not allowed in affiliates program",
                "error_code": 111,
            }
        ],
        "total_success": 0,
        "total_error": 1,
    }
    assert affiliate._create_link_url_recusada(recusado) is True

    invalidou = {"ok": False}

    def _mark(*a, **k):
        invalidou["ok"] = True

    class _Reject(_Ok):
        def post(self, url, **kwargs):
            return httpx.Response(200, json=recusado, request=httpx.Request("POST", url))

    monkeypatch.setattr(affiliate.httpx, "Client", _Reject)
    monkeypatch.setattr(affiliate, "mark_account_credentials_invalid", _mark)
    auth2 = affiliate._MLAuth(
        account_id=uuid4(), account_tag="nina-tag", cookie="ssid=ok;_csrf=tok"
    )
    assert affiliate._converter_mercadolivre_com_tag(container, "nina-tag", auth2, None) is None
    assert invalidou["ok"] is False


def test_cupom_card_meli_usa_asset_estatico(tmp_path, monkeypatch):
    from worker import cupom_card

    asset = tmp_path / "cupom_meli.png"
    asset.write_bytes(b"fake-png")
    monkeypatch.setattr(cupom_card, "_CUPOM_MELI_ASSET", asset)
    path = cupom_card.gerar_card(
        OfertaCapturada(
            nome="Cupom",
            preco=0,
            loja="Mercado Livre",
            url=cupons.url_container_meli("1"),
            categoria="cupom",
        )
    )
    assert path == str(asset)


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


def test_cadencia_de_cupom_nao_cala_o_produto(monkeypatch, session_factory):
    cupom = OfertaCapturada(
        nome="20% OFF",
        preco=0,
        loja="Shopee",
        url="https://s.shopee.com.br/cupom",
        categoria="cupom",
        codigo_cupom="NINA10",
        sku="cupom:nina10",
        beneficio="20% OFF",
    )
    produto = OfertaCapturada(
        nome="Panela",
        preco=80,
        loja="Shopee",
        url="https://s.shopee.com.br/panela",
        comissao_pct=0.05,
    )
    _runtime, enviados = _preparar(monkeypatch, session_factory, [cupom, produto])
    monkeypatch.setattr(monitor.repositories, "minutos_desde_ultimo_cupom", lambda *_a, **_k: 10.0)
    monkeypatch.setattr(monitor.repositories, "sku_ja_enviado", lambda *_a, **_k: True)
    with config_provider.usar_bot_runtime(_runtime):
        monitor.ciclo()
    assert enviados
    assert any("Panela" in mensagem for _, mensagem in enviados)
    assert all("NINA10" not in mensagem for _, mensagem in enviados)


def test_ciclo_envia_cupom_e_produto_juntos(monkeypatch, session_factory):
    cupom = OfertaCapturada(
        nome="20% OFF",
        preco=0,
        loja="Shopee",
        url="https://s.shopee.com.br/cupom",
        categoria="cupom",
        codigo_cupom="NINA10",
        sku="cupom:nina10-novo",
        beneficio="20% OFF",
    )
    produto = OfertaCapturada(
        nome="Panela",
        preco=80,
        loja="Shopee",
        url="https://s.shopee.com.br/panela",
        comissao_pct=0.05,
    )
    runtime, enviados = _preparar(monkeypatch, session_factory, [produto, cupom])
    monkeypatch.setattr(monitor.repositories, "minutos_desde_ultimo_cupom", lambda *_a, **_k: None)
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()
    textos = [mensagem for _, mensagem in enviados]
    assert any("NINA10" in t or "RESGATE" in t for t in textos)
    assert any("Panela" in t for t in textos)


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
