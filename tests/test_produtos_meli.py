"""Fila manual de produtos ML + pausa do scraper HTML após bloqueio."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import httpx
import pytest

from core.bot_settings import BotSettings, Content
from core.platforms import mercadolivre as ml
from core.platforms.mercadolivre import MercadoLivreScraper, produtos_manuais_de_filtros


@pytest.fixture(autouse=True)
def _limpar_caches():
    ml.limpar_cache_bloqueio_html()
    ml.limpar_cache_mais_vendidos()
    yield
    ml.limpar_cache_bloqueio_html()
    ml.limpar_cache_mais_vendidos()


def test_bot_settings_aceita_produtos_meli_com_preco_string():
    settings = BotSettings.model_validate(
        {
            "content": {
                "produtos_meli": [
                    {
                        "url": "https://www.mercadolivre.com.br/x/p/MLB123456789",
                        "titulo": "Panela",
                        "preco": "89.90",
                        "preco_anterior": "129,90",
                    }
                ]
            }
        }
    )
    item = settings.content.produtos_meli[0]
    assert item["preco"] == "89.90"
    assert item["preco_anterior"] == "129.90"
    assert item["titulo"] == "Panela"


def test_bot_settings_recusa_url_sem_mlb():
    with pytest.raises(ValueError, match="MLB"):
        Content.model_validate(
            {
                "produtos_meli": [
                    {
                        "url": "https://www.mercadolivre.com.br/ofertas",
                        "titulo": "x",
                        "preco": "10",
                    }
                ]
            }
        )


def test_produtos_manuais_viram_oferta():
    agora = __import__("core.relogio", fromlist=["relogio"]).relogio.agora_banco()
    ofertas = produtos_manuais_de_filtros(
        {
            "produtos_meli": [
                {
                    "url": "https://produto.mercadolivre.com.br/MLB-999888777-panela",
                    "titulo": "Panela antiaderente",
                    "preco": "89.90",
                    "preco_anterior": "120",
                    "adicionado_em": agora.isoformat(),
                }
            ]
        }
    )
    assert len(ofertas) == 1
    assert ofertas[0].sku == "MLB999888777"
    assert ofertas[0].nome == "Panela antiaderente"
    assert ofertas[0].preco == 89.9
    assert ofertas[0].preco_anterior == 120.0
    assert ofertas[0].loja == "Mercado Livre"
    assert ofertas[0].desconto is not None


def test_produtos_manuais_vencidos_saem(monkeypatch):
    from core import relogio

    agora = relogio.agora_banco()
    velho = (agora - timedelta(hours=49)).isoformat()
    ofertas = produtos_manuais_de_filtros(
        {
            "produtos_meli": [
                {
                    "url": "https://www.mercadolivre.com.br/p/MLB111",
                    "titulo": "Velho",
                    "preco": "10",
                    "adicionado_em": velho,
                }
            ]
        }
    )
    assert ofertas == []


def test_buscar_inclui_manual_sem_html(monkeypatch):
    agora = __import__("core.relogio", fromlist=["relogio"]).relogio.agora_banco()
    monkeypatch.setattr(
        ml,
        "load_filtros",
        lambda: {
            "origem_produtos": "novidades",
            "produtos_meli": [
                {
                    "url": "https://www.mercadolivre.com.br/p/MLB222",
                    "titulo": "Manual",
                    "preco": "55.00",
                    "adicionado_em": agora.isoformat(),
                }
            ],
        },
    )

    class FakeAuth:
        cookie = ""

    monkeypatch.setattr(
        "core.platforms.affiliate._ml_auth",
        lambda: (None, FakeAuth()),
    )

    def client_get(self, url, **kwargs):
        req = httpx.Request("GET", "https://www.mercadolivre.com.br/gz/account-verification")
        return httpx.Response(200, text="<html>account-verification</html>", request=req)

    monkeypatch.setattr(httpx.Client, "get", client_get)

    ofertas = MercadoLivreScraper().buscar()
    assert len(ofertas) == 1
    assert ofertas[0].sku == "MLB222"
    assert ml._bloqueio_html_ate is not None


def test_html_em_pausa_nao_requisita_de_novo(monkeypatch):
    agora = __import__("core.relogio", fromlist=["relogio"]).relogio.agora_banco()
    monkeypatch.setattr(
        ml,
        "load_filtros",
        lambda: {
            "origem_produtos": "ambos",
            "categorias_meli": ["MLB1574"],
            "termos_busca": ["panela"],
            "produtos_meli": [
                {
                    "url": "https://www.mercadolivre.com.br/p/MLB333",
                    "titulo": "Só manual",
                    "preco": "40",
                    "adicionado_em": agora.isoformat(),
                }
            ],
        },
    )
    ml._bloqueio_html_ate = __import__("time").monotonic() + 3600
    chamadas = {"n": 0}

    def client_get(self, *args, **kwargs):
        chamadas["n"] += 1
        raise AssertionError("não deveria chamar HTML em pausa")

    monkeypatch.setattr(httpx.Client, "get", client_get)
    monkeypatch.setattr(
        "core.platforms.affiliate._ml_auth",
        lambda: (None, MagicMock(cookie="x=1")),
    )

    ofertas = MercadoLivreScraper().buscar()
    assert chamadas["n"] == 0
    assert len(ofertas) == 1
    assert ofertas[0].sku == "MLB333"
