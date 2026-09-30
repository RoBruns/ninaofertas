# ruff: noqa: F811
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from core import config_provider
from core.bot_settings import BotSettings
from core.models import Envio
from core.platforms import affiliate, mercadolivre
from core.platforms.base import OfertaCapturada
from core.platforms.mercadolivre import _beneficio_cupom
from tests.test_api import session_factory  # noqa: F401
from tests.test_multigrupo import _preparar
from worker import monitor
from worker.filters import passa_nos_filtros
from worker.formatter import montar_mensagem


def _oferta(**changes: object) -> OfertaCapturada:
    values: dict[str, object] = {
        "nome": "Produto sem palavra do nicho",
        "preco": 100.0,
        "preco_anterior": 200.0,
        "loja": "Mercado Livre",
        "url": "https://meli.la/oferta",
    }
    values.update(changes)
    return OfertaCapturada(**values)  # type: ignore[arg-type]


def test_cupom_ml_so_aceita_codigo_digitavel() -> None:
    assert _beneficio_cupom({"couponCode": "nina10"}) == "NINA10"
    assert _beneficio_cupom({"coupon_code": "HTTP"}) is None
    assert _beneficio_cupom({"components": [{"type": "promotions", "text": "R$ 100 OFF"}]}) is None
    assert "Cupom" not in montar_mensagem(_oferta(codigo_cupom="R$ 100 OFF"))
    assert "NINA10" in montar_mensagem(_oferta(codigo_cupom="nina10"))


def test_filtros_ml_e_origem_categoria_sao_opcoes_independentes() -> None:
    filtros = {"palavras_chave": ["cozinha"], "desconto_minimo": 15, "max_vendas": 20}
    oferta = _oferta(desconto=10.0, vendas=30)
    assert not passa_nos_filtros(oferta, filtros)[0]
    filtros["ml_ignora_desconto_e_vendas"] = True
    assert not passa_nos_filtros(oferta, filtros)[0]
    filtros["ml_categoria_dispensa_nicho"] = True
    assert not passa_nos_filtros(oferta, filtros)[0]
    oferta.origem_categoria_meli = True
    assert passa_nos_filtros(oferta, filtros)[0]
    assert not passa_nos_filtros(_oferta(loja="Shopee", desconto=10.0, vendas=30), filtros)[0]


def test_bloqueio_normaliza_acentos() -> None:
    filtros = {"palavras_chave": ["camera", "papel"], "bloquear_produtos": ["câmera", "papel higiênico"]}
    assert not passa_nos_filtros(_oferta(nome="Câmera de segurança Wi-Fi"), filtros)[0]
    assert not passa_nos_filtros(_oferta(nome="Camera IP"), filtros)[0]
    assert not passa_nos_filtros(_oferta(nome="papel higiênico"), filtros)[0]


def test_settings_novos_default_e_round_trip_legado() -> None:
    assert BotSettings().filters.uma_loja_por_ciclo is False
    assert BotSettings().filters.ml_ignora_desconto_e_vendas is False
    assert BotSettings().filters.ml_categoria_dispensa_nicho is False
    legacy = {"preco_minimo": 20, "uma_loja_por_ciclo": True}
    assert BotSettings.model_validate(legacy).model_dump() == legacy


# --- Envio, avisos e alternância de loja (ciclo real do worker) ---------------------------


def test_oferta_sem_link_de_afiliado_nao_e_enviada(monkeypatch, session_factory) -> None:
    oferta = OfertaCapturada(
        nome="Panela", preco=100.0, preco_anterior=200.0, loja="Shopee",
        url="https://shopee.com.br/panela",
    )
    runtime, enviados = _preparar(monkeypatch, session_factory, [oferta])
    # A conversão falhou: garantir_afiliado devolve a URL original, sem marca de afiliado.
    monkeypatch.setattr(monitor.affiliate, "link_rastreado", _link_real)
    monkeypatch.setattr(
        monitor.affiliate, "garantir_afiliado",
        lambda _loja, url, **_kw: affiliate.AffiliateLink(url, None),
    )
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()
    assert enviados == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Envio).where(Envio.status != "visto")) == 0

    # Com o link afiliado, a mesma oferta sai.
    monkeypatch.setattr(
        monitor.affiliate, "garantir_afiliado",
        lambda _loja, _url, **_kw: affiliate.AffiliateLink("https://s.shopee.com.br/abc", None),
    )
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()
    assert len(enviados) == 2


_link_real = affiliate.link_rastreado


def test_aviso_de_createlink_sai_uma_vez_por_ciclo(monkeypatch) -> None:
    avisos: list[str] = []
    monkeypatch.setattr(affiliate.logger, "warning", avisos.append)
    auth = affiliate._MLAuth(None, "", "")
    affiliate.reset_aviso_ciclo()
    for _ in range(3):
        assert affiliate._converter_mercadolivre_com_tag("https://ml/x", "", auth, None) is None
    assert len(avisos) == 1
    affiliate.reset_aviso_ciclo()
    affiliate._converter_mercadolivre_com_tag("https://ml/x", "", auth, None)
    assert len(avisos) == 2


@pytest.mark.parametrize("cookie", ["ssid=abc; _csrf=x", ""])
def test_busca_do_ml_usa_o_cookie_da_conta_vinculada(monkeypatch, cookie: str) -> None:
    usados: list[dict] = []

    class _Client:
        def __init__(self, *, headers, **_kw):
            usados.append(dict(headers))

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(mercadolivre.httpx, "Client", _Client)
    monkeypatch.setattr(affiliate, "_ml_auth", lambda: (None, affiliate._MLAuth(None, "tag", cookie)))
    scraper = mercadolivre.MercadoLivreScraper()
    monkeypatch.setattr(scraper, "_buscar_ofertas_categoria", lambda *_a: [])
    monkeypatch.setattr(scraper, "_buscar_lista_termos", lambda *_a: [])
    scraper.buscar()
    headers = {k.lower(): v for k, v in usados[0].items()}
    assert headers.get("cookie") == (cookie or None)


def _lojas_por_ciclo(monkeypatch, session_factory, filtros_extra) -> list[set[str]]:
    ofertas = [
        OfertaCapturada(nome="Panela", preco=100.0, loja="Shopee", url="https://shopee.com.br/p"),
        OfertaCapturada(nome="Caneca", preco=100.0, loja="Mercado Livre", url="https://ml.com/c"),
    ]
    runtime, _enviados = _preparar(monkeypatch, session_factory, ofertas, filtros_extra)
    monkeypatch.setattr(
        monitor, "_SLUG_POR_LOJA", {"Shopee": "shopee", "Mercado Livre": "mercadolivre"}
    )
    monkeypatch.setattr(
        monitor, "platforms_with_usable_credentials", lambda _ids: {"shopee", "mercadolivre"}
    )
    avaliadas: list[str] = []

    def filtro(oferta, _filtros):
        avaliadas.append(oferta.loja)
        return False, "teste"

    monkeypatch.setattr(monitor, "passa_nos_filtros", filtro)
    ciclos: list[set[str]] = []
    for _ in range(2):
        avaliadas.clear()
        with config_provider.usar_bot_runtime(runtime):
            monitor.ciclo()
        ciclos.append(set(avaliadas))
    return ciclos


def test_uma_loja_por_ciclo_alterna_e_exclui_a_outra(monkeypatch, session_factory) -> None:
    primeiro, segundo = _lojas_por_ciclo(monkeypatch, session_factory, {"uma_loja_por_ciclo": True})
    assert len(primeiro) == 1 and len(segundo) == 1
    assert primeiro | segundo == {"Shopee", "Mercado Livre"}


def test_sem_a_opcao_as_duas_lojas_entram_no_ciclo(monkeypatch, session_factory) -> None:
    primeiro, segundo = _lojas_por_ciclo(monkeypatch, session_factory, {})
    assert primeiro == segundo == {"Shopee", "Mercado Livre"}
