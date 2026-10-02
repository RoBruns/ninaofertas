# ruff: noqa: F811
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from core import config_provider
from core.bot_settings import BotSettings
from core.platforms import affiliate, mercadolivre, shopee
from core.platforms.base import OfertaCapturada
from core.seed import _settings_from_config
from worker.filters import passa_nos_filtros
from worker.monitor import _ordenar_envio
from worker.ranking import pontuar
from tests.test_api import session_factory  # noqa: F401
from tests.test_multigrupo import _preparar
from worker import monitor


AMOSTRA = (Path(__file__).parent / "fixtures/ml_mais_vendidos_amostra.html").read_text(
    encoding="utf-8"
)


@pytest.fixture(autouse=True)
def _limpar_cache_mais_vendidos():
    mercadolivre._cache_mais_vendidos.clear()
    yield
    mercadolivre._cache_mais_vendidos.clear()


def oferta(**campos) -> OfertaCapturada:
    return OfertaCapturada(**{
        "nome": "Organizador de cozinha", "preco": 100, "loja": "Shopee",
        "url": "https://shopee.com.br/produto", **campos,
    })


def test_settings_defaults_validacao_e_legado():
    settings = BotSettings()
    assert settings.filters.origem_produtos == "novidades"
    assert settings.filters.min_vendas == 100
    for filtros in ({"origem_produtos": "outro"}, {"min_vendas": -1}):
        with pytest.raises(ValidationError):
            BotSettings.model_validate({"filters": filtros})
    legado = {"origem_produtos": "ambos", "min_vendas": 150, "max_vendas": 20}
    assert BotSettings.model_validate(legado).model_dump() == legado
    seeded = _settings_from_config(legado)
    assert seeded["filters"]["origem_produtos"] == "ambos"
    assert seeded["filters"]["min_vendas"] == 150


def test_parser_amostra_real():
    blocos = mercadolivre._extrair_mais_vendidos_json(AMOSTRA)
    assert list(blocos) == ["MLB5672", "MLB1430"]
    esperados = {
        "MLB5672": [(19.9, None), (76.41, 99), (47.99, 78.99)],
        "MLB1430": [(34.9, None), (59.9, 79.9), (59.99, 135.41)],
    }
    for categoria, cards in blocos.items():
        produtos = [mercadolivre._parse_card(card) for card in cards]
        assert [(p.preco, p.preco_anterior) for p in produtos] == esperados[categoria]
    assert mercadolivre._extrair_mais_vendidos_json("<html>vazio</html>") == {}
    assert mercadolivre._extrair_mais_vendidos_json(
        '"best_sellers_configuration":{"category":"MLB1"},"polycards":[inválido'
    ) == {}


def cliente_mock(monkeypatch, modulo, resposta):
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.side_effect = resposta
    monkeypatch.setattr(modulo.httpx, "Client", lambda **_kwargs: client)
    return client


@pytest.mark.parametrize("origem", ["novidades", "mais_vendidos", "ambos"])
def test_ml_fontes_categorias_e_posicoes(monkeypatch, origem):
    filtros = {"origem_produtos": origem, "categorias_meli": ["MLB1430", "MLB1574"]}
    monkeypatch.setattr(mercadolivre, "load_filtros", lambda: filtros)
    monkeypatch.setattr(affiliate, "_ml_auth", lambda: (None, affiliate._MLAuth(None, "", "")))
    raiz = mercadolivre.MAIS_VENDIDOS_URL
    client = cliente_mock(monkeypatch, mercadolivre, lambda url, **_kwargs: httpx.Response(
        200, text=AMOSTRA if url == raiz else "<html></html>", request=httpx.Request("GET", url)
    ))
    produtos = mercadolivre.MercadoLivreScraper().buscar()
    urls = [call.args[0] for call in client.get.call_args_list]
    if origem == "novidades":
        assert all("mais-vendidos" not in url for url in urls)
        assert mercadolivre.OFERTAS_URL in urls
        assert produtos == []
    else:
        assert raiz in urls
        assert raiz + "/MLB1574" in urls
        assert raiz + "/MLB1430" not in urls
        assert len(produtos) == 3
        assert [p.posicao_ranking for p in produtos] == [1, 2, 3]
        assert all(p.origem_mais_vendidos and p.origem_categoria_meli for p in produtos)
        assert [p.preco for p in produtos] == [34.9, 59.9, 59.99]
        assert (mercadolivre.OFERTAS_URL in urls) == (origem == "ambos")


def test_ml_mais_vendidos_em_cache_entre_ciclos(monkeypatch):
    monkeypatch.setattr(mercadolivre, "load_filtros", lambda: {
        "origem_produtos": "mais_vendidos", "categorias_meli": ["MLB1430"],
    })
    monkeypatch.setattr(affiliate, "_ml_auth", lambda: (None, affiliate._MLAuth(None, "", "")))
    raiz = mercadolivre.MAIS_VENDIDOS_URL
    client = cliente_mock(monkeypatch, mercadolivre, lambda url, **_kwargs: httpx.Response(
        200, text=AMOSTRA, request=httpx.Request("GET", url)
    ))
    primeiro = mercadolivre.MercadoLivreScraper().buscar()
    segundo = mercadolivre.MercadoLivreScraper().buscar()
    assert [p.sku for p in segundo] == [p.sku for p in primeiro] and primeiro
    assert client.get.call_args_list.count(((raiz,), {})) == 1

    # Depois do prazo, a página é buscada de novo.
    instante = mercadolivre._cache_mais_vendidos[raiz][0]
    mercadolivre._cache_mais_vendidos[raiz] = (
        instante - mercadolivre.MAIS_VENDIDOS_TTL_SEGUNDOS - 1,
        mercadolivre._cache_mais_vendidos[raiz][1],
    )
    mercadolivre.MercadoLivreScraper().buscar()
    assert client.get.call_args_list.count(((raiz,), {})) == 2


def test_ml_bloqueio_sem_excecao(monkeypatch):
    monkeypatch.setattr(mercadolivre, "load_filtros", lambda: {
        "origem_produtos": "mais_vendidos", "categorias_meli": ["MLB1574"],
    })
    monkeypatch.setattr(affiliate, "_ml_auth", lambda: (None, affiliate._MLAuth(None, "", "")))
    cliente_mock(monkeypatch, mercadolivre, lambda *_args, **_kwargs: httpx.Response(
        200, text="verificação", request=httpx.Request(
            "GET", "https://www.mercadolivre.com.br/gz/account-verification"
        )
    ))
    scraper = mercadolivre.MercadoLivreScraper()
    assert scraper.buscar() == []
    assert scraper._bloqueio_avisado is True


def test_ml_categoria_ausente_e_dedup_com_ofertas(monkeypatch):
    monkeypatch.setattr(mercadolivre, "load_filtros", lambda: {
        "origem_produtos": "ambos", "categorias_meli": ["MLB1430", "MLB1574"],
    })
    monkeypatch.setattr(affiliate, "_ml_auth", lambda: (None, affiliate._MLAuth(None, "", "")))
    raiz = mercadolivre.MAIS_VENDIDOS_URL
    blocos = mercadolivre._extrair_mais_vendidos_json(AMOSTRA)
    card = blocos["MLB5672"][1]
    fallback = json.dumps({
        "best_sellers_configuration": {"category": "MLB1574"}, "polycards": [card],
    })
    # A fonte atual também devolve produtos do ranking: nenhum pode duplicar.
    atuais = json.dumps({"items": [card, *blocos["MLB1430"]]}, separators=(",", ":"))

    def resposta(url, **_kwargs):
        html = AMOSTRA if url == raiz else fallback if url == raiz + "/MLB1574" else atuais
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    client = cliente_mock(monkeypatch, mercadolivre, resposta)
    produtos = mercadolivre.MercadoLivreScraper().buscar()
    assert len(produtos) == 4
    assert len({p.sku for p in produtos}) == 4
    assert all(p.origem_mais_vendidos for p in produtos)
    assert [p.posicao_ranking for p in produtos] == [1, 2, 3, 1]
    assert client.get.call_args_list.count(((raiz + "/MLB1574",), {})) == 1


@pytest.mark.parametrize("origem,sorts", [
    ("novidades", [1]), ("mais_vendidos", [2]), ("ambos", [1, 2]),
])
def test_shopee_queries_e_dedup(monkeypatch, origem, sorts):
    monkeypatch.setattr(shopee, "load_filtros", lambda: {
        "origem_produtos": origem, "termos_busca": ["organizador"],
    })
    scraper = shopee.ShopeeScraper()
    monkeypatch.setattr(scraper, "_load_auth", lambda: ("app", "secret"))
    queries = []

    def graphql(_client, query):
        queries.append(query)
        return {"productOfferV2": {"nodes": [{
            "itemId": 123, "productName": "Organizador", "priceMin": 100,
            "offerLink": "https://s.shopee.com.br/123",
            "sales": 15000 if "sortType: 2" in query else 2,
            "ratingStar": "4.8", "commissionRate": "0.03",
        }]}}

    monkeypatch.setattr(scraper, "_graphql", graphql)
    cliente_mock(monkeypatch, shopee, None)
    produtos = scraper.buscar()
    assert len(queries) == len(sorts)
    for query, sort in zip(queries, sorts, strict=True):
        assert f"sortType: {sort}" in query
        assert ("ratingStar" in query) == (sort == 2)
        assert ("commissionRate" in query) == (sort == 2)
    assert len(produtos) == 1
    assert produtos[0].origem_mais_vendidos == (origem != "novidades")
    if origem != "novidades":
        assert produtos[0].vendas == 15000
        assert produtos[0].nota == 4.8
        assert produtos[0].comissao_pct == 0.03
    else:
        assert queries[0] == (Path(__file__).parent / "fixtures/shopee_query_relevancia.graphql").read_text(
            encoding="utf-8"
        )


def test_filtros_mais_vendidos_e_regras_atuais():
    filtros = {"max_vendas": 20, "min_vendas": 100, "desconto_minimo": 15}
    assert passa_nos_filtros(oferta(origem_mais_vendidos=True, vendas=15000, desconto=30), filtros)[0]
    assert "mínimo" in passa_nos_filtros(
        oferta(origem_mais_vendidos=True, vendas=99, desconto=30), filtros
    )[1]
    assert "sem desconto" in passa_nos_filtros(oferta(origem_mais_vendidos=True), filtros)[1]
    assert not passa_nos_filtros(oferta(origem_mais_vendidos=True, desconto=14), filtros)[0]
    assert not passa_nos_filtros(oferta(vendas=15000, desconto=30), filtros)[0]
    assert passa_nos_filtros(oferta(vendas=20), filtros)[0]
    assert passa_nos_filtros(oferta(origem_mais_vendidos=True, vendas=99, desconto=30), {
        **filtros, "min_vendas": 0,
    })[0]
    assert passa_nos_filtros(oferta(origem_mais_vendidos=True, loja="Mercado Livre"), {
        **filtros, "ml_ignora_desconto_e_vendas": True,
    })[0]


@pytest.mark.parametrize("campos,score", [
    ({}, 0), ({"vendas": 20000}, 0.45), ({"desconto": 70}, 0.35),
    ({"nota": 5}, 0.1), ({"comissao_pct": 0.15}, 0.1),
    ({"loja": "Mercado Livre", "posicao_ranking": 1}, 0.45),
    ({"loja": "Mercado Livre", "posicao_ranking": 20}, 0.0225),
    ({"vendas": 40000, "desconto": 90, "nota": 6, "comissao_pct": 0.3}, 1),
])
def test_pontuar(campos, score):
    assert pontuar(oferta(**campos)) == pytest.approx(score)


@pytest.mark.parametrize("origem", ["novidades", "mais_vendidos", "ambos"])
def test_ordem_por_loja_estavel_com_conteudo_preservado(origem):
    baixo, alto, empate = oferta(), oferta(vendas=20000), oferta(vendas=20000)
    ml = oferta(loja="Mercado Livre")
    campanha = oferta(categoria="campanha")
    cupom = oferta(categoria="cupom")
    entrada = [baixo, campanha, ml, alto, empate, cupom]
    resultado = _ordenar_envio(entrada, 4, "Shopee", origem)
    assert resultado == ([cupom, baixo, ml, campanha, alto, empate] if origem == "novidades"
                         else [cupom, alto, ml, campanha, empate, baixo])


@pytest.mark.parametrize("origem", ["novidades", "mais_vendidos", "ambos"])
def test_ciclo_usa_settings_do_banco_e_registra_ranking(monkeypatch, session_factory, origem):
    baixo = oferta(nome="Panela baixa", url="https://shopee.com.br/baixo", vendas=100,
                   desconto=30, origem_mais_vendidos=True)
    alto = oferta(nome="Panela alta", url="https://shopee.com.br/alto", vendas=20000,
                  desconto=30, origem_mais_vendidos=True)
    runtime, enviados = _preparar(monkeypatch, session_factory, [baixo, alto], {
        "origem_produtos": origem, "min_vendas": 100,
    })
    mensagens = []
    monkeypatch.setattr(monitor.logger, "info", mensagens.append)
    with config_provider.usar_bot_runtime(runtime):
        monitor.ciclo()
    assert len(enviados) == 2
    nome = "Panela baixa" if origem == "novidades" else "Panela alta"
    assert all(nome in mensagem for _, mensagem in enviados)
    ranking = [m for m in mensagens if "Mais vendidos Shopee:" in m]
    assert len(ranking) == (0 if origem == "novidades" else 1)
    if ranking:
        assert "2 candidatos" in ranking[0]
        assert ranking[0].index("Panela alta") < ranking[0].index("Panela baixa")
